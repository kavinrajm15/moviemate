import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import os
import re
from datetime import datetime

BASE_URL = "https://ticketnew.com"

# --------------------------------------------------
# PATH SETUP
# --------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
POSTER_DIR = os.path.join(STATIC_DIR, "posters")
os.makedirs(POSTER_DIR, exist_ok=True)

# --------------------------------------------------
# TAMIL NADU CITIES
# --------------------------------------------------
TAMILNADU_CITIES = [
    "chennai","coimbatore","madurai","salem","tirupur","trichy","vellore",
    "tirunelveli","erode","rajapalayam","chengalpattu","kanchipuram","ooty",
    "pondicherry","villupuram","karur","nagercoil","thanjavur","hosur",
    "dindigul","pudukkottai","pollachi","panruti","cuddalore","dharmapuri",
    "kallakurichi","kovilpatti","krishnagiri","kumbakonam","namakkal",
    "perambalur","ramanathapuram","ranipet","sathyamangalam","sivakasi",
    "sivaganga","tindivanam","tiruchengode","tuticorin","udumalpet","ambur",
    "arakkonam","bhavani","devakottai","gobichettipalayam","mettupalayam",
    "musiri","oddanchathiram","palladam","sankarankovil","thiruvannamalai",
    "pallipalayam","sankagiri"
]

# --------------------------------------------------
today = datetime.now().strftime("%Y%m%d")
json_file = os.path.join(BASE_DIR, "tamilnadu_ticketnew.json")

# --------------------------------------------------
# SAFE FILENAME FROM MOVIE TITLE
# --------------------------------------------------
def safe_filename(title: str, ext: str = ".jpg") -> str:
    name = title.lower()
    name = re.sub(r"\(\d+\)", "", name)      # remove (1), (2011)
    name = re.sub(r"[^a-z0-9]+", "_", name)  # clean symbols
    name = name.strip("_")
    return f"{name}{ext}"

# --------------------------------------------------
async def download_poster(page, poster_url, movie_title):
    if not poster_url:
        return None

    path = urlparse(poster_url).path
    ext = os.path.splitext(path)[1] or ".jpg"

    filename = safe_filename(movie_title, ext)
    filepath = os.path.join(POSTER_DIR, filename)

    if not os.path.exists(filepath):
        response = await page.request.get(poster_url)
        content = await response.body()
        with open(filepath, "wb") as f:
            f.write(content)

    return f"posters/{filename}"

# --------------------------------------------------
async def get_today_movies(page, city):
    await page.goto(
        f"{BASE_URL}/movies/{city}",
        wait_until="domcontentloaded",
        timeout=60000
    )

    soup = BeautifulSoup(await page.content(), "lxml")
    movies = []

    for card in soup.find_all("div", class_="item-cards"):
        a = card.find("a", href=True)
        if not a or "movie-detail" not in a["href"]:
            continue

        title = a.find("h5")
        if not title:
            continue

        movies.append({
            "title": title.get_text(strip=True),
            "url": urljoin(BASE_URL, a["href"])
        })

    return movies

# --------------------------------------------------
async def get_movie_details(page, movie_url):
    try:
        await page.goto(movie_url, wait_until="domcontentloaded", timeout=60000)
    except:
        return None

    soup = BeautifulSoup(await page.content(), "lxml")

    # ---------- POSTER ----------
    poster_url = None
    img = soup.select_one("div[class*='MovieDetailWidget_textImgCon'] img")
    if img and img.get("src"):
        poster_url = urljoin(BASE_URL, img["src"])

    # ---------- META ----------
    certificate = duration = None
    info = soup.select_one("div[class*='MovieDetailWidget_subHeading']")
    if info:
        raw = info.get_text(" ", strip=True)

        dur = re.search(r"\d+\s*hr.*?\d*\s*min?", raw, re.I)
        if dur:
            duration = dur.group()

        cert = re.search(r"\b(U|UA|UA13\+|A)\b", raw)
        if cert:
            certificate = cert.group()

    # ---------- THEATRES ----------
    theatres = []
    blocks = soup.select("li[class*='MovieSessionsListing_movieSessions']")

    for block in blocks:
        name = block.select_one("div[class*='MovieSessionsListing_titleFlex'] a")
        if not name:
            continue

        showtimes = []
        for t in block.select("div.greenCol"):
            time_text = t.find(string=True, recursive=False)
            fmt = t.find("span")

            if time_text:
                showtimes.append({
                    "time": time_text.strip(),
                    "format": fmt.get_text(strip=True) if fmt else "2D"
                })

        if showtimes:
            theatres.append({
                "name": name.get_text(strip=True),
                "showtimes": showtimes
            })

    if not theatres:
        return None

    return {
        "poster_url": poster_url,
        "certificate": certificate,
        "duration": duration,
        "theatres": theatres
    }

# --------------------------------------------------
async def run_all_cities():
    final_data = {
        "date": today,
        "cities": {}
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for city in TAMILNADU_CITIES:
            print(f"\n🌆 CITY: {city}")
            movies = await get_today_movies(page, city)
            city_movies = []

            for movie in movies:
                print("  🎬", movie["title"])
                details = await get_movie_details(page, movie["url"])
                if not details:
                    continue

                poster_path = await download_poster(
                    page,
                    details["poster_url"],
                    movie["title"]
                )

                city_movies.append({
                    "title": movie["title"],
                    "image": poster_path,
                    "certificate": details["certificate"],
                    "duration": details["duration"],
                    "theatres": details["theatres"]
                })

            if city_movies:
                final_data["cities"][city] = {"movies": city_movies}

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=4, ensure_ascii=False)

        await browser.close()

    print("\nScraping complete")
    print("Posters:", POSTER_DIR)
    print(" JSON:", json_file)

# --------------------------------------------------
if __name__ == "__main__":
    asyncio.run(run_all_cities())
