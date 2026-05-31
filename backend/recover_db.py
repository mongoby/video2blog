#!/usr/bin/env python3
"""Recover lost job records from existing video/transcript/blog files."""
import json, os, re, glob

JOBS_DIR = "/mnt/d/video2blog/jobs"
UPLOADS = f"{JOBS_DIR}/uploads"
TRANSCRIPTS = f"{JOBS_DIR}/transcripts"
BLOGS = f"{JOBS_DIR}/blogs"
DB = f"{JOBS_DIR}/jobs.json"

# Load existing jobs
existing = json.loads(open(DB).read()) if os.path.exists(DB) else {}

# Find all unique job IDs from files
ids = set()
for d in [UPLOADS, TRANSCRIPTS, BLOGS]:
    for f in glob.glob(f"{d}/*"):
        name = os.path.basename(f).split(".")[0]
        if name and not name.endswith("_part") and not name.endswith(".ytdl"):
            ids.add(name)

recovered = 0
for jid in sorted(ids):
    if jid in existing:
        continue  # already in DB

    job = {"id": jid, "title": jid, "source_url": "", "status": "created",
           "progress": 0, "message": "", "video_file": None, "video_size": 0,
           "video_duration": None, "whisper_model": "base", "language": None,
           "tone": "professional", "length": "short", "transcript_chars": 0,
           "blog_word_count": 0, "error": None,
           "created_at": "2026-05-29T00:00:00+00:00",
           "updated_at": "2026-05-29T00:00:00+00:00"}

    # Video file
    for ext in [".mp4", ".mkv", ".webm", ".mov", ".avi"]:
        vp = f"{UPLOADS}/{jid}{ext}"
        if os.path.exists(vp):
            job["video_file"] = vp
            job["video_size"] = os.path.getsize(vp)
            break

    # Transcript
    tp = f"{TRANSCRIPTS}/{jid}.json"
    if os.path.exists(tp):
        try:
            t = json.loads(open(tp).read())
            job["transcript_chars"] = len(t.get("text", ""))
            job["video_duration"] = t.get("duration")
            job["language"] = t.get("language")
            job["status"] = "transcribed"
            job["message"] = f"Transcribed {t.get('duration',0):.0f}s video"
        except: pass

    # Blog
    bp = f"{BLOGS}/{jid}.md"
    if os.path.exists(bp):
        try:
            text = open(bp).read()
            words = len(re.findall(r'[\u4e00-\u9fff]', text)) + len(re.findall(r'[a-zA-Z0-9]+', text))
            job["blog_word_count"] = words
            job["status"] = "done"
            job["progress"] = 100
            job["message"] = f"Blog generated ({words} words)"
        except: pass

    existing[jid] = job
    recovered += 1

open(DB, "w").write(json.dumps(existing, ensure_ascii=False, indent=2))
print(f"Recovered {recovered} jobs. Total: {len(existing)}")
for jid, j in sorted(existing.items()):
    print(f"  {jid}: {j['status']} - {j.get('message','')[:50]}")
