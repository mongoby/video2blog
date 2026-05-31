#!/usr/bin/env python3
"""
video2blog — Web Backend (Flask API)

Pipeline: upload video → transcribe (whisper) → generate blog (DeepSeek) → edit → export Markdown
"""
import os, sys, re, json, time, uuid, shutil, threading, subprocess, traceback
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

# ── Configuration ────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
JOBS_DIR = PROJECT_DIR / "jobs"
UPLOADS_DIR = JOBS_DIR / "uploads"
TRANSCRIPTS_DIR = JOBS_DIR / "transcripts"
BLOGS_DIR = JOBS_DIR / "blogs"

for d in [JOBS_DIR, UPLOADS_DIR, TRANSCRIPTS_DIR, BLOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Load API key from env or .env
def _load_env():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_load_env()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".mp3", ".wav", ".m4a", ".ogg"}
MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1GB

# Supported video platforms for URL download (yt-dlp)
SUPPORTED_PLATFORMS = [
    "小红书 (XiaoHongShu)", "抖音 (Douyin)", "腾讯短视频",
    "B站 (Bilibili)", "YouTube", "TikTok",
]

TONE_PROMPTS = {
    "professional": "Write in a professional, analytical tone suitable for a tech or business blog. Use data-driven language and maintain objectivity.",
    "casual": "Write in a friendly, conversational tone like a personal blog. Be engaging and relatable. Use simple language.",
    "technical": "Write in a detailed technical tone suitable for a developer blog. Include technical specifics, code references, architecture details.",
    "storytelling": "Write in a narrative, story-driven style. Open with a compelling hook, use vivid descriptions, and structure as a journey.",
}
LENGTH_GUIDE = {
    "short": "Write a concise blog post of approximately 300-500 words. Focus on the single most important takeaway.",
    "medium": "Write a standard blog post of approximately 800-1200 words with 3-5 main sections and clear subheadings.",
}

# ── App ──────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001")
CORS(app, resources={r"/api/*": {"origins": CORS_ALLOWED_ORIGINS}})

# In-memory job state (persisted to JSON)
_jobs: dict = {}
_jobs_lock = threading.Lock()


def _load_jobs():
    global _jobs
    db_path = JOBS_DIR / "jobs.json"
    if db_path.exists():
        try:
            data = json.loads(db_path.read_text(encoding="utf-8"))
            _jobs = data
        except Exception:
            _jobs = {}
    else:
        _jobs = {}


def _save_jobs():
    db_path = JOBS_DIR / "jobs.json"
    db_path.write_text(json.dumps(_jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _transcript_path(job_id: str) -> Path:
    return TRANSCRIPTS_DIR / f"{job_id}.json"


def _blog_path(job_id: str) -> Path:
    return BLOGS_DIR / f"{job_id}.md"


def _get_job(job_id: str) -> Optional[dict]:
    _load_jobs()
    return _jobs.get(job_id)


def _word_count(text: str) -> int:
    """Count words correctly for mixed Chinese/English text."""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z0-9]+', text))
    return chinese_chars + english_words


def _update_job(job_id: str, **kwargs):
    with _jobs_lock:
        _load_jobs()
        if job_id not in _jobs:
            return None
        _jobs[job_id].update(kwargs)
        _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_jobs()
    return _jobs[job_id]


def _create_job(title: str = "Untitled", source_url: str = "") -> dict:
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    job = {
        "id": job_id,
        "title": title,
        "source_url": source_url,
        "status": "created",  # created → transcribing → transcribed → generating → done → error
        "progress": 0,        # 0-100
        "message": "",
        "video_file": None,
        "video_size": 0,
        "video_duration": None,
        "whisper_model": "base",
        "language": None,
        "tone": "professional",
        "length": "short",
        "transcript_chars": 0,
        "blog_word_count": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
        _save_jobs()
    return job


# ── Background Tasks ─────────────────────────────────────────────────────

def _download_from_url(job_id: str, url: str):
    """Download video from URL using yt-dlp (first) or you-get (fallback)."""
    SUPPORTED_EXTRACTORS = [
        ("yt-dlp", ["yt-dlp", "-o", str(UPLOADS_DIR / f"{job_id}.%(ext)s"), "--no-playlist", url]),
        ("you-get", ["you-get", "-o", str(UPLOADS_DIR), "-O", job_id, url]),
    ]
    PLAYWRIGHT_SCRIPT = str(BASE_DIR / "playwright_extract.py")
    PYTHON_CMD = "python" if os.name == "nt" else "python3"

    try:
        _update_job(job_id, progress=2, message="Resolving URL...")

        downloaded = None
        last_error = None

        for name, cmd in SUPPORTED_EXTRACTORS:
            _update_job(job_id, progress=3, message=f"Trying {name}...")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if result.returncode == 0:
                    # Find downloaded file
                    for f in os.listdir(str(UPLOADS_DIR)):
                        if f.startswith(job_id):
                            downloaded = os.path.join(str(UPLOADS_DIR), f)
                            break
                    if downloaded and os.path.getsize(downloaded) > 0:
                        break
                last_error = result.stderr.strip() or result.stdout.strip() or f"{name} failed"
            except FileNotFoundError:
                last_error = f"{name} not installed"

        # Fallback: try playwright-based extraction (handles Douyin, etc.)
        if not downloaded:
            _update_job(job_id, progress=3, message="Trying browser extraction...")
            output_path = str(UPLOADS_DIR / f"{job_id}.mp4")
            try:
                pb_result = subprocess.run(
                    [PYTHON_CMD, PLAYWRIGHT_SCRIPT, url, output_path],
                    capture_output=True, text=True, timeout=60,
                )
                if pb_result.returncode == 0:
                    try:
                        pb_data = json.loads(pb_result.stdout)
                        if pb_data.get("size", 0) > 0 and os.path.exists(output_path):
                            downloaded = output_path
                    except (json.JSONDecodeError, Exception):
                        pass
                else:
                    last_error = pb_result.stderr.strip() or "browser extraction failed"
            except FileNotFoundError:
                last_error = "browser extraction: playwright/python not found. Install: pip install playwright && playwright install chromium"
            except Exception as e:
                last_error = f"browser extraction error: {str(e)[:200]}"

        if not downloaded:
            reasons = []
            for name in ["yt-dlp", "you-get"]:
                if name in str(last_error or ""):
                    reasons.append(f"{name}: 不支持此链接")
                elif f"{name} not installed" in str(last_error or ""):
                    reasons.append(f"{name}: 未安装")
            if "playwright" in str(last_error or "").lower() or "browser extraction" in str(last_error or ""):
                reasons.append("Playwright: 未安装或提取失败")
            if not reasons:
                reasons.append(last_error[:200] if last_error else "未知错误")
            err_msg = "；".join(reasons)
            _update_job(job_id, status="error", error=f"下载失败: {err_msg}")
            return

        file_size = os.path.getsize(downloaded)
        if file_size == 0:
            os.remove(downloaded)
            _update_job(job_id, status="error", error="Downloaded file is empty")
            return

        _update_job(
            job_id,
            video_file=downloaded,
            video_size=file_size,
            progress=5,
            message=f"Downloaded ({file_size // 1024 // 1024}MB), starting transcription...",
        )

        # Auto-start transcription
        _run_transcription(job_id)

    except subprocess.TimeoutExpired:
        _update_job(job_id, status="error", error="Download timed out after 1 hour")
    except Exception as e:
        traceback.print_exc()
        _update_job(job_id, status="error", error=str(e))

def _run_transcription(job_id: str):
    """Run whisper transcription in background thread."""
    try:
        job = _get_job(job_id)
        if not job:
            return

        video_path = job.get("video_file")
        if not video_path or not os.path.exists(video_path):
            _update_job(job_id, status="error", error="Video file not found")
            return

        _update_job(job_id, status="transcribing", progress=5, message="Loading whisper model...")

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _update_job(job_id, status="error",
                        error="faster-whisper not installed. Run: pip3 install faster-whisper")
            return

        has_cuda = False
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except ImportError:
            has_cuda = False

        compute = "float16" if has_cuda else "int8"
        device = "cuda" if has_cuda else "cpu"

        model_size = job.get("whisper_model", "base")
        model = WhisperModel(model_size, device=device, compute_type=compute)

        _update_job(job_id, progress=20, message=f"Transcribing with {model_size} (GPU={'RTX 5070' if has_cuda else 'CPU'})...")

        # Use video title as context to improve terminology accuracy
        title_context = job.get("title", "")
        initial_prompt = None
        if title_context:
            initial_prompt = f"以下是关于{title_context}的内容。"

        segments, info = model.transcribe(
            video_path,
            language=job.get("language") or None,
            initial_prompt=initial_prompt,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        segments_list = list(segments)

        text_parts = []
        segment_data = []
        for seg in segments_list:
            text = seg.text.strip()
            if text:
                text_parts.append(text)
                segment_data.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text,
                })

        full_text = " ".join(text_parts)
        duration = info.duration
        lang = info.language

        # Detect non-speech videos (music, silent, noise only)
        if duration > 30 and len(full_text.strip()) < 15:
            _update_job(job_id, status="error",
                        error="该视频可能没有语音内容（纯音乐/无声/噪音），无法生成博客文字。请确认视频包含人声说话内容。")
            return

        # Save transcript
        transcript_data = {
            "text": full_text,
            "segments": segment_data,
            "language": lang,
            "duration": duration,
            "model": model_size,
        }
        _transcript_path(job_id).write_text(json.dumps(transcript_data, ensure_ascii=False), encoding="utf-8")

        _update_job(
            job_id,
            status="transcribed",
            progress=50,
            message=f"Transcribed {duration:.0f}s video ({lang}, {len(segment_data)} segments)",
            language=lang,
            video_duration=duration,
            transcript_chars=len(full_text),
        )

    except Exception as e:
        traceback.print_exc()
        _update_job(job_id, status="error", error=str(e))


def _run_blog_generation(job_id: str):
    """Generate blog from transcript in background thread."""
    try:
        job = _get_job(job_id)
        if not job:
            return

        tp = _transcript_path(job_id)
        if not tp.exists():
            _update_job(job_id, status="error", error="Transcript not found")
            return

        transcript_data = json.loads(tp.read_text(encoding="utf-8"))
        transcript_text = transcript_data.get("text", "")
        language = transcript_data.get("language", job.get("language", "en"))

        if not DEEPSEEK_API_KEY:
            _update_job(job_id, status="error", error="No API key configured")
            return

        _update_job(job_id, status="generating", progress=55, message="Sending to AI for blog generation...")

        tone = job.get("tone", "professional")
        tone_guide = TONE_PROMPTS.get(tone, TONE_PROMPTS["professional"])

        # Dynamic length control based on transcript length, max 5000 words
        transcript_len = len(transcript_text)
        if transcript_len < 500:
            length_guide = "Write a very concise blog post of approximately 150-300 words. Focus on the single most important takeaway. Be punchy and direct."
        elif transcript_len < 2000:
            length_guide = "Write a concise blog post of approximately 400-800 words. Include 2-3 clear sections with the key points."
        elif transcript_len < 8000:
            length_guide = "Write a blog post of approximately 1000-2000 words. Structure it with 3-5 sections covering the main topics in depth."
        else:
            length_guide = "Write a comprehensive blog post of approximately 3000-5000 words. Do NOT exceed 5000 words. Cover all major topics with depth and detail, include multiple sections, and explore subtopics thoroughly."

        is_chinese = language in ("zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "wuu", "yue")
        blog_lang = "Write the blog post in Chinese (Simplified)." if is_chinese else \
                    "Write the blog post in English."

        # Truncate long transcripts
        max_chars = 60000
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars]

        import httpx

        system_prompt = f"""You are an expert content writer who converts video transcripts into blog posts written by a real human, not an AI.

{blog_lang}

{tone_guide}

{length_guide}

Style rules (CRITICAL):
- Write like a real person, NOT an AI. No "总的来说", "让我们来", "值得一提的是", "请持续关注" etc.
- No summary/conclusion phrases at the end like "总的来说", "综上所述", "让我们拭目以待"
- Use natural transitions between paragraphs
- Vary sentence lengths. Mix short and long sentences.
- If the transcript mentions specific names (companies, products, people), keep them accurate
- Do NOT add information that wasn't in the transcript
- Do NOT fabricate quotes, statistics, or sources

Structure:
- A compelling title
- A short intro paragraph (2-3 sentences max)
- Body paragraphs organized by topic
- End naturally — no "finally" or "in conclusion" padding

Output in Markdown format.

⚠️ End with exactly this disclaimer line:
---
*本内容由 AI 基于视频转录生成，仅供参考。关键信息（如名称、数据、引用等）请以原始视频为准。*"""

        user_prompt = f"""Video transcript to convert into a blog post.

Title/Source: {job.get('title', 'Untitled')}

Transcript:
{transcript_text}

Write a blog post based on this transcript. Keep it natural, no AI clichés."""

        response = httpx.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 8192,
            },
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # Strip code fences
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        content = content.strip()

        # Build full markdown with frontmatter (JSON is valid YAML)
        import json as _json
        frontmatter = {
            "title": job.get("title", "Untitled"),
            "source": job.get("video_file", ""),
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tone": tone,
            "language": language,
            "transcript_chars": len(transcript_text),
            "model": LLM_MODEL,
        }
        word_count = _word_count(content)
        # Compute dynamic length label
        dyn_length = "short" if word_count < 600 else "medium" if word_count < 1500 else "long"
        # Write blog with frontmatter including actual word count
        frontmatter["length"] = f"{word_count} words ({dyn_length})"
        _blog_path(job_id).write_text(_json.dumps(frontmatter, ensure_ascii=False, indent=2) + "\n\n" + content, encoding="utf-8")

        _update_job(
            job_id,
            status="done",
            progress=100,
            message=f"Blog generated ({word_count} words, {dyn_length}, {tone})",
            blog_word_count=word_count,
        )

    except Exception as e:
        traceback.print_exc()
        _update_job(job_id, status="error", error=str(e))


# ── API Routes ───────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok"})


@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    _load_jobs()
    jobs_list = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    total = len(jobs_list)
    start = (page - 1) * per_page
    end = start + per_page
    return jsonify({"jobs": jobs_list[start:end], "total": total, "page": page, "per_page": per_page})


@app.route("/api/jobs", methods=["POST"])
def api_create_job():
    title = request.form.get("title", "Untitled")
    file = request.files.get("file")

    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    # Check Content-Length header before saving
    content_length = request.content_length
    if content_length and content_length > MAX_UPLOAD_SIZE:
        return jsonify({"error": f"File too large (max {MAX_UPLOAD_SIZE // (1024*1024)}MB)"}), 413

    # Create job
    job = _create_job(title=title)

    # Save file with streaming size limit
    safe_name = f"{job['id']}{ext}"
    video_path = str(UPLOADS_DIR / safe_name)

    bytes_written = 0
    chunk_size = 8192
    with open(video_path, 'wb') as f:
        while True:
            chunk = file.stream.read(chunk_size)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_SIZE:
                f.close()
                os.remove(video_path)
                _update_job(job["id"], status="error", error="File too large (max 1GB)")
                return jsonify({"error": "File too large"}), 413
            f.write(chunk)

    file_size = os.path.getsize(video_path)

    # Update job
    whisper_model = request.form.get("model", "base")
    language = request.form.get("language") or None
    tone = request.form.get("tone", "professional")
    length = request.form.get("length", "medium")

    _update_job(
        job["id"],
        video_file=video_path,
        video_size=file_size,
        whisper_model=whisper_model,
        language=language,
        tone=tone,
        length=length,
        progress=1,
        message="File uploaded, ready to transcribe",
    )

    # Auto-start transcription
    thread = threading.Thread(target=_run_transcription, args=(job["id"],), daemon=True)
    thread.start()

    return jsonify({"job": _get_job(job["id"])}), 201


@app.route("/api/jobs/from-url", methods=["POST"])
def api_create_job_from_url():
    """Create a job from a video URL (yt-dlp download)."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Invalid URL"}), 400

    title = data.get("title", url.split("/")[-1][:60] or "From URL")
    whisper_model = data.get("model", "base")
    language = data.get("language") or None
    tone = data.get("tone", "professional")
    length = data.get("length", "short")

    # Create job
    job = _create_job(title=title, source_url=url)
    _update_job(
        job["id"],
        whisper_model=whisper_model,
        language=language,
        tone=tone,
        length=length,
        progress=1,
        message="Queued download from URL...",
    )

    # Start download in background
    thread = threading.Thread(target=_download_from_url, args=(job["id"], url), daemon=True)
    thread.start()

    return jsonify({"job": _get_job(job["id"])}), 201


@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_get_job(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"job": job})


@app.route("/api/jobs/<job_id>/transcribe", methods=["POST"])
def api_transcribe(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] not in ("created", "error"):
        return jsonify({"error": f"Job is in '{job['status']}' state, cannot transcribe"}), 400

    # Update config if provided
    data = request.get_json(silent=True) or {}
    model = data.get("model", job.get("whisper_model", "base"))
    language = data.get("language", job.get("language"))
    _update_job(job_id, whisper_model=model, language=language if language else None)

    thread = threading.Thread(target=_run_transcription, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({"job": _get_job(job_id)})


@app.route("/api/jobs/<job_id>/generate", methods=["POST"])
def api_generate_blog(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] not in ("transcribed", "done", "error"):
        return jsonify({"error": f"Job is in '{job['status']}' state, must be transcribed first"}), 400

    data = request.get_json(silent=True) or {}
    tone = data.get("tone", job.get("tone", "professional"))
    length = data.get("length", job.get("length", "medium"))
    _update_job(job_id, tone=tone, length=length)

    thread = threading.Thread(target=_run_blog_generation, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({"job": _get_job(job_id)})


@app.route("/api/jobs/<job_id>/transcript", methods=["GET"])
def api_get_transcript(job_id: str):
    tp = _transcript_path(job_id)
    if not tp.exists():
        job = _get_job(job_id)
        if job and job.get("status") in ("created", "transcribing"):
            return jsonify({"error": "Transcription in progress", "status": job["status"]}), 202
        return jsonify({"error": "Transcript not found"}), 404

    try:
        data = json.loads(tp.read_text(encoding="utf-8"))
        return jsonify({"transcript": data})
    except Exception:
        return jsonify({"error": "Failed to read transcript"}), 500


@app.route("/api/jobs/<job_id>/blog", methods=["GET"])
def api_get_blog(job_id: str):
    bp = _blog_path(job_id)
    if not bp.exists():
        return jsonify({"error": "Blog not yet generated"}), 404

    content = bp.read_text(encoding="utf-8")
    return jsonify({"blog": {"content": content}})


@app.route("/api/jobs/<job_id>/blog", methods=["PUT"])
def api_update_blog(job_id: str):
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "Content is required"}), 400

    bp = _blog_path(job_id)
    bp.write_text(content, encoding="utf-8")

    word_count = len(content.split())
    _update_job(job_id, blog_word_count=word_count, message="Blog edited by user")
    return jsonify({"status": "saved", "word_count": word_count})


@app.route("/api/jobs/<job_id>/export", methods=["GET"])
def api_export_blog(job_id: str):
    bp = _blog_path(job_id)
    if not bp.exists():
        return jsonify({"error": "Blog not found"}), 404

    job = _get_job(job_id)
    filename = f"{sanitize_filename(job.get('title', 'blog'))}_blog.md" if job else "blog.md"

    return send_file(
        str(bp),
        as_attachment=True,
        download_name=filename,
        mimetype="text/markdown",
    )


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
def api_delete_job(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Clean up files
    video = job.get("video_file")
    if video and os.path.exists(video):
        os.remove(video)
    for p in [_transcript_path(job_id), _blog_path(job_id)]:
        if p.exists():
            os.remove(p)

    with _jobs_lock:
        _load_jobs()
        _jobs.pop(job_id, None)
        _save_jobs()

    return jsonify({"status": "deleted"})


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[^\w\- ]', '', name).strip()
    return name[:80] if name else "blog"


# ── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"🚀 video2blog API server starting on http://0.0.0.0:{port} (debug={'on' if debug_mode else 'off'})")
    app.run(host="0.0.0.0", port=port, debug=debug_mode, threaded=True)
