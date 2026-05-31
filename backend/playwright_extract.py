#!/usr/bin/env python3
"""
Playwright-based video URL extractor for sites that need browser rendering.
Falls back when yt-dlp/you-get fail due to cookie requirements or DRM.
"""
import sys, json, asyncio, os, re
from playwright.async_api import async_playwright

# Sites that we can handle via Playwright
EXTRACTORS = {
    "douyin": {
        "hosts": ["douyin.com", "iesdouyin.com"],
        "extract": """
            () => {
                // Get video source from page
                const v = document.querySelector('video');
                if (v && v.src && v.src.includes('aweme')) return v.src;
                // Check _ROUTER_DATA for video info
                if (window._ROUTER_DATA) {
                    try {
                        const loader = window._ROUTER_DATA.loaderData;
                        // Find videoInfoRes in any loader key
                        let item = null;
                        for (const key in loader) {
                            if (loader[key] && loader[key].videoInfoRes) {
                                item = loader[key].videoInfoRes.item_list[0];
                                break;
                            }
                        }
                        if (!item) item = Object.values(loader).find(v => v && v.videoInfoRes)?.videoInfoRes?.item_list?.[0];
                        if (item) {
                            const play = item.video && (item.video.play_addr || item.video.play_addr_h265);
                            if (play && play.url_list) return play.url_list[0];
                            // Try video/play_addr directly on item
                            if (item.video && item.video.play_addr && item.video.play_addr.url_list) {
                                return item.video.play_addr.url_list[0];
                            }
                        }
                    } catch(e) {
                        return 'ERROR: ' + e.message;
                    }
                }
                // Last resort: check all video sources on page
                const sources = document.querySelectorAll('source');
                for (const s of sources) {
                    if (s.src && s.src.includes('aweme')) return s.src;
                }
                return null;
            }
        """,
    },
    "kuaishou": {
        "hosts": ["kuaishou.com", "kwai.com"],
        "extract": """
            () => {
                const v = document.querySelector('video');
                return v ? v.src : null;
            }
        """,
    },
    "weibo": {
        "hosts": ["weibo.com", "weibo.cn", "video.weibo.com"],
        "extract": """
            () => {
                const v = document.querySelector('video');
                if (v && v.src) return v.src;
                const sources = document.querySelectorAll('source');
                for (const s of sources) {
                    if (s.src && (s.src.includes('.mp4') || s.src.includes('video'))) return s.src;
                }
                const scripts = document.querySelectorAll('script');
                for (const s of scripts) {
                    if (s.textContent && s.textContent.includes('video_url')) {
                        const m = s.textContent.match(/video_url['\"]?\\s*[:=]\\s*['\"]([^'\"]+)['\"]/);
                        if (m) return m[1];
                    }
                }
                return null;
            }
        """,
    },
}

def _match_extractor(url: str) -> str | None:
    for name, info in EXTRACTORS.items():
        for host in info["hosts"]:
            if host in url:
                return name
    return None

async def extract_video_url(url: str) -> dict:
    """Open the URL in headless Chromium and extract the video source URL."""
    name = _match_extractor(url)
    if not name:
        return {"error": f"No extractor for URL: {url}"}

    info = EXTRACTORS[name]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 13; SM-S9010) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            # Page might have redirected, check current URL
            current_url = page.url
        except Exception:
            current_url = page.url

        # If still on short URL, wait for redirect
        if "v.douyin.com" in page.url or "short" in page.url:
            try:
                await page.wait_for_url(lambda u: "iesdouyin.com" in u or "douyin.com/share" in u, timeout=10000)
            except:
                pass
            await asyncio.sleep(2)

        video_url = await page.evaluate(info["extract"])
        await browser.close()

        if video_url:
            return {"source": name, "video_url": video_url}
        return {"error": f"Could not extract video URL from {name}"}

async def download_video(url: str, output_path: str) -> dict:
    """Extract video URL and download it."""
    result = await extract_video_url(url)
    if "error" in result:
        return result

    video_url = result["video_url"]
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9010) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
        "Referer": "https://www.iesdouyin.com/" if "douyin" in url else f"https://{result['source']}.com/",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
        response = await client.get(video_url, headers=headers)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)

    return {"source": result["source"], "size": len(response.content), "path": output_path}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: playwright_extract.py <url> [output_path]')
        sys.exit(1)

    url = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else None

    if output:
        result = asyncio.run(download_video(url, output))
    else:
        result = asyncio.run(extract_video_url(url))

    print(json.dumps(result, ensure_ascii=False))
