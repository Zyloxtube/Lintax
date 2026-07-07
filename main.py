import os
import asyncio
from fastapi import FastAPI, HTTPException, Query
import httpx
from typing import Optional
from playwright.async_api import async_playwright

app = FastAPI(title="TMDB + VidVault API", version="1.0")

TMDB_BASE = "https://tmdb.lewagon.com"

# ---------- Playwright helpers ----------
_browser = None
_playwright = None

async def get_browser():
    global _browser, _playwright
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
    return _browser

async def scrape_vidvault_page(url: str):
    browser = await get_browser()
    context = await browser.new_context(
        accept_downloads=True,
        viewport={'width': 1280, 'height': 720},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    )
    page = await context.new_page()
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_selector('button', timeout=10000)

        # Expand subtitle section
        try:
            sub_btn = await page.query_selector('button:has-text("Subtitle Downloads")')
            if sub_btn:
                await sub_btn.click()
                await page.wait_for_timeout(500)
        except:
            pass

        qualities = await page.evaluate("""
            () => {
                const buttons = document.querySelectorAll('button');
                const results = [];
                const seen = new Set();
                buttons.forEach(btn => {
                    const text = btn.textContent.trim();
                    const match = text.match(/(\\d+)\\s*p/i);
                    if (match) {
                        const quality = match[0].toLowerCase();
                        if (!seen.has(quality)) {
                            seen.add(quality);
                            const sizeMatch = text.match(/[\\(\\[]\\s*([\\d.]+)\\s*(MB|GB)\\s*[\\)\\]]/i);
                            results.push({
                                quality: quality,
                                size: sizeMatch ? sizeMatch[1] + ' ' + sizeMatch[2] : 'Unknown',
                                text: text
                            });
                        }
                    }
                });
                const order = {'360p':0,'480p':1,'720p':2,'1080p':3,'4k':4};
                results.sort((a,b) => (order[a.quality]||999) - (order[b.quality]||999));
                return results;
            }
        """)

        subtitles = await page.evaluate("""
            () => {
                const buttons = document.querySelectorAll('button');
                const results = [];
                const seen = new Set();
                buttons.forEach(btn => {
                    const text = btn.textContent.trim();
                    if (text.toLowerCase().includes('subtitle') || text.toLowerCase().includes('.srt')) {
                        let language = 'Unknown';
                        const langMatch = text.match(/(English|Spanish|French|German|Arabic|Chinese|Japanese|Korean)/i);
                        if (langMatch) language = langMatch[0];
                        const key = text.toLowerCase();
                        if (!seen.has(key)) {
                            seen.add(key);
                            results.push({ text: text, language: language });
                        }
                    }
                });
                return results;
            }
        """)

        return {'qualities': qualities, 'subtitles': subtitles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping error: {str(e)}")
    finally:
        await context.close()

async def get_download_url(url: str, quality: str, subtitle_text: str = None):
    browser = await get_browser()
    context = await browser.new_context(
        accept_downloads=True,
        viewport={'width': 1280, 'height': 720},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    )
    page = await context.new_page()
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_selector(f'button:has-text("{quality}")', timeout=10000)

        async with page.expect_download() as download_info:
            await page.click(f'button:has-text("{quality}")')
        download = await download_info.value
        video_url = download.url
        video_filename = download.suggested_filename or f'video_{quality}.mp4'

        subtitle_url = None
        subtitle_filename = None
        if subtitle_text:
            try:
                sub_expand = await page.query_selector('button:has-text("Subtitle Downloads")')
                if sub_expand:
                    await sub_expand.click()
                    await page.wait_for_timeout(500)
            except:
                pass
            sub_btn = await page.query_selector(f'button:has-text("{subtitle_text}")')
            if sub_btn:
                async with page.expect_download() as sub_info:
                    await sub_btn.click()
                sub_download = await sub_info.value
                subtitle_url = sub_download.url
                subtitle_filename = sub_download.suggested_filename or 'subtitles.srt'

        return {
            'video_url': video_url,
            'video_filename': video_filename,
            'subtitle_url': subtitle_url,
            'subtitle_filename': subtitle_filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download URL error: {str(e)}")
    finally:
        await context.close()

# ---------- TMDB proxy helper ----------
async def forward_tmdb(path: str, params: dict = None):
    url = f"{TMDB_BASE}/{path.lstrip('/')}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TMDB proxy error: {str(e)}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()

# ---------- Root ----------
@app.get("/")
async def root():
    return {
        "message": "TMDB + VidVault API. See /docs for Swagger (if enabled).",
        "endpoints": {
            "health": "/health",
            "test_browser": "/test-browser",
            "movie_details": "/movie/{id}",
            "tv_details": "/tv/{id}",
            "movie_qualities": "/movie/{id}/qualities",
            "movie_subtitles": "/movie/{id}/subtitles",
            "movie_stream": "/movie/{id}/stream?quality=...&subtitle=...",
            "tv_qualities": "/tv/{id}/season/{s}/episode/{e}/qualities",
            "tv_subtitles": "/tv/{id}/season/{s}/episode/{e}/subtitles",
            "tv_stream": "/tv/{id}/season/{s}/episode/{e}/stream?quality=...&subtitle=..."
        }
    }

# ---------- Health and test browser ----------
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/test-browser")
async def test_browser():
    """Test if Playwright can launch Chromium and load a page."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            page = await browser.new_page()
            await page.goto("https://example.com", wait_until="domcontentloaded")
            title = await page.title()
            await browser.close()
            return {"status": "Browser works!", "title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Browser test failed: {str(e)}")

# ---------- TMDB Endpoints ----------
@app.get("/search/multi")
async def search_multi(query: str = Query(...)):
    return await forward_tmdb("search/multi", {"query": query})

@app.get("/search/movie")
async def search_movie(query: str = Query(...)):
    return await forward_tmdb("search/movie", {"query": query})

@app.get("/search/tv")
async def search_tv(query: str = Query(...)):
    return await forward_tmdb("search/tv", {"query": query})

@app.get("/movie/{movie_id}")
async def get_movie(movie_id: int):
    return await forward_tmdb(f"movie/{movie_id}")

@app.get("/movie/{movie_id}/similar")
async def movie_similar(movie_id: int):
    return await forward_tmdb(f"movie/{movie_id}/similar")

@app.get("/movie/{movie_id}/recommendations")
async def movie_recommendations(movie_id: int):
    return await forward_tmdb(f"movie/{movie_id}/recommendations")

@app.get("/movie/{movie_id}/images")
async def movie_images(movie_id: int):
    return await forward_tmdb(f"movie/{movie_id}/images")

@app.get("/movie/{movie_id}/videos")
async def movie_videos(movie_id: int):
    return await forward_tmdb(f"movie/{movie_id}/videos")

@app.get("/tv/{tv_id}")
async def get_tv(tv_id: int):
    return await forward_tmdb(f"tv/{tv_id}")

@app.get("/tv/{tv_id}/season/{season_num}")
async def get_season(tv_id: int, season_num: int):
    return await forward_tmdb(f"tv/{tv_id}/season/{season_num}")

@app.get("/tv/{tv_id}/season/{season_num}/episode/{episode_num}")
async def get_episode(tv_id: int, season_num: int, episode_num: int):
    return await forward_tmdb(f"tv/{tv_id}/season/{season_num}/episode/{episode_num}")

@app.get("/tv/{tv_id}/similar")
async def tv_similar(tv_id: int):
    return await forward_tmdb(f"tv/{tv_id}/similar")

@app.get("/tv/{tv_id}/recommendations")
async def tv_recommendations(tv_id: int):
    return await forward_tmdb(f"tv/{tv_id}/recommendations")

@app.get("/tv/{tv_id}/images")
async def tv_images(tv_id: int):
    return await forward_tmdb(f"tv/{tv_id}/images")

@app.get("/tv/{tv_id}/videos")
async def tv_videos(tv_id: int):
    return await forward_tmdb(f"tv/{tv_id}/videos")

@app.get("/tv/{tv_id}/season/{season_num}/images")
async def season_images(tv_id: int, season_num: int):
    return await forward_tmdb(f"tv/{tv_id}/season/{season_num}/images")

# Trending
@app.get("/trending/all/day")
async def trending_all_day():
    return await forward_tmdb("trending/all/day")

@app.get("/trending/all/week")
async def trending_all_week():
    return await forward_tmdb("trending/all/week")

@app.get("/trending/movie/day")
async def trending_movie_day():
    return await forward_tmdb("trending/movie/day")

@app.get("/trending/movie/week")
async def trending_movie_week():
    return await forward_tmdb("trending/movie/week")

@app.get("/trending/tv/day")
async def trending_tv_day():
    return await forward_tmdb("trending/tv/day")

@app.get("/trending/tv/week")
async def trending_tv_week():
    return await forward_tmdb("trending/tv/week")

@app.get("/movie/popular")
async def movie_popular():
    return await forward_tmdb("movie/popular")

@app.get("/tv/popular")
async def tv_popular():
    return await forward_tmdb("tv/popular")

@app.get("/movie/top_rated")
async def movie_top_rated():
    return await forward_tmdb("movie/top_rated")

@app.get("/tv/top_rated")
async def tv_top_rated():
    return await forward_tmdb("tv/top_rated")

@app.get("/movie/latest")
async def movie_latest():
    return await forward_tmdb("movie/latest")

@app.get("/tv/latest")
async def tv_latest():
    return await forward_tmdb("tv/latest")

@app.get("/movie/upcoming")
async def movie_upcoming():
    return await forward_tmdb("movie/upcoming")

@app.get("/movie/now_playing")
async def movie_now_playing():
    return await forward_tmdb("movie/now_playing")

@app.get("/tv/airing_today")
async def tv_airing_today():
    return await forward_tmdb("tv/airing_today")

@app.get("/tv/on_the_air")
async def tv_on_the_air():
    return await forward_tmdb("tv/on_the_air")

# ---------- Custom VidVault Endpoints ----------
@app.get("/movie/{movie_id}/qualities")
async def movie_qualities(movie_id: int):
    url = f"https://vidvault.ru/movie/{movie_id}"
    data = await scrape_vidvault_page(url)
    return {"movie_id": movie_id, "qualities": data["qualities"]}

@app.get("/movie/{movie_id}/subtitles")
async def movie_subtitles(movie_id: int):
    url = f"https://vidvault.ru/movie/{movie_id}"
    data = await scrape_vidvault_page(url)
    return {"movie_id": movie_id, "subtitles": data["subtitles"]}

@app.get("/movie/{movie_id}/stream")
async def movie_stream(
    movie_id: int,
    quality: str = Query(..., description="e.g., 360p, 480p, 1080p"),
    subtitle: Optional[str] = Query(None, description="Subtitle text to download")
):
    url = f"https://vidvault.ru/movie/{movie_id}"
    result = await get_download_url(url, quality, subtitle)
    return {
        "movie_id": movie_id,
        "quality": quality,
        "video_url": result["video_url"],
        "video_filename": result["video_filename"],
        "subtitle_url": result.get("subtitle_url"),
        "subtitle_filename": result.get("subtitle_filename")
    }

@app.get("/tv/{tv_id}/season/{season}/episode/{episode}/qualities")
async def tv_qualities(tv_id: int, season: int, episode: int):
    url = f"https://vidvault.ru/tv/{tv_id}/{season}/{episode}"
    data = await scrape_vidvault_page(url)
    return {"tv_id": tv_id, "season": season, "episode": episode, "qualities": data["qualities"]}

@app.get("/tv/{tv_id}/season/{season}/episode/{episode}/subtitles")
async def tv_subtitles(tv_id: int, season: int, episode: int):
    url = f"https://vidvault.ru/tv/{tv_id}/{season}/{episode}"
    data = await scrape_vidvault_page(url)
    return {"tv_id": tv_id, "season": season, "episode": episode, "subtitles": data["subtitles"]}

@app.get("/tv/{tv_id}/season/{season}/episode/{episode}/stream")
async def tv_stream(
    tv_id: int,
    season: int,
    episode: int,
    quality: str = Query(..., description="e.g., 360p, 480p, 1080p"),
    subtitle: Optional[str] = Query(None, description="Subtitle text to download")
):
    url = f"https://vidvault.ru/tv/{tv_id}/{season}/{episode}"
    result = await get_download_url(url, quality, subtitle)
    return {
        "tv_id": tv_id,
        "season": season,
        "episode": episode,
        "quality": quality,
        "video_url": result["video_url"],
        "video_filename": result["video_filename"],
        "subtitle_url": result.get("subtitle_url"),
        "subtitle_filename": result.get("subtitle_filename")
    }

# ---------- On startup: warm up browser ----------
@app.on_event("startup")
async def startup():
    try:
        await get_browser()
        print("✅ Browser warmed up successfully.")
    except Exception as e:
        print(f"❌ Browser warm-up failed: {e}")
