import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import os
import re
from datetime import datetime, timedelta

BASE_URL = "https://ticketnew.com"

# ---------------- PATH SETUP ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
POSTER_DIR = os.path.join(STATIC_DIR, "posters")
os.makedirs(POSTER_DIR, exist_ok=True)
JSON_FILE = os.path.join(BASE_DIR, "tamilnadu_ticketnew.json")
TODAY = datetime.now().strftime("%Y-%m-%d")

# ---------------- CITIES ----------------
TAMILNADU_CITIES = [
    "chennai","coimbatore","madurai","salem","tirupur","trichy","vellore",
    "tirunelveli","erode","rajapalayam","kanchipuram","villupuram","karur",
    "nagercoil","thanjavur","hosur","dindigul","pudukkottai","pollachi",
    "panruti","cuddalore","dharmapuri","kallakurichi","kovilpatti",
    "krishnagiri","kumbakonam","namakkal","ramanathapuram","ranipet",
    "sathyamangalam","sivakasi","tindivanam","tiruchengode","tuticorin",
    "udumalpet","ambur","arakkonam","devakottai","gobichettipalayam",
    "mettupalayam","palladam","sankarankovil","thiruvannamalai",
    "pallipalayam","sankagiri"
]

# ---------------- HELPERS ----------------
def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"\(\d{4}\)", "", t)
    t = re.sub(r"[:\-–—]", " ", t)
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.title()

def safe_filename(title, ext=".jpg"):
    name = title.lower()
    name = re.sub(r"\(\d+\)", "", name)
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_") + ext

def save_json(data):
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

async def download_poster(page, poster_url, movie_title):
    if not poster_url:
        return None
    poster_url = poster_url.split("?")[0]
    ext = os.path.splitext(poster_url)[1] or ".jpg"
    filename = safe_filename(movie_title, ext)
    filepath = os.path.join(POSTER_DIR, filename)
    if not os.path.exists(filepath):
        r = await page.request.get(poster_url)
        with open(filepath, "wb") as f:
            f.write(await r.body())
    return f"posters/{filename}"

# ---------------- GET MOVIES ----------------
async def get_movies(page, city):
    url = f"{BASE_URL}/movies/{city}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    
    # Scroll to load all movies
    prev_count = 0
    for _ in range(20):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1200)
        soup = BeautifulSoup(await page.content(), "lxml")
        cards = soup.select("div.item-cards")
        if len(cards) == prev_count:
            break
        prev_count = len(cards)
    
    soup = BeautifulSoup(await page.content(), "lxml")
    movies = {}
    for card in soup.select("div.item-cards a[href*='movie-detail']"):
        title_tag = card.find("h5")
        if not title_tag:
            continue

        # Skip upcoming movies if "Coming Soon" badge exists
        coming_soon = card.select_one("span.coming-soon")  # may need class adjustment
        if coming_soon:
            continue

        name = title_tag.get_text(strip=True)
        movies[name] = {"title": name, "url": urljoin(BASE_URL, card["href"])}
    
    print(f"🎞️ Found {len(movies)} released movies in {city}")
    return list(movies.values())

# ---------------- GET MOVIE DETAILS & SHOWTIMES ----------------
async def get_movie_details(page, movie_url):
    theatres_dict = {}
    poster_url = certificate = duration = None
    
    await page.goto(movie_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)  # wait for JS
    
    # Grab poster & meta info
    if not poster_url:
        img = await page.query_selector("div[class*='MovieDetailWidget_textImgCon'] img")
        if img:
            poster_url = urljoin(BASE_URL, await img.get_attribute("src"))
        meta = await page.query_selector("div[class*='MovieDetailWidget_subHeading']")
        if meta:
            txt = await meta.inner_text()
            if m := re.search(r"\d+\s*hr.*?\d*\s*min?", txt, re.I):
                duration = m.group()
            if m := re.search(r"\b(U|UA|UA13\+|A)\b", txt):
                certificate = m.group()
    
    # Get date buttons (today + next 2 days)
    dates_container = await page.query_selector("div.DatesMobileV2_cinemaDatesDiv__d8LsL")
    if not dates_container:
        return None
    
    date_buttons = await dates_container.query_selector_all("div.DatesMobileV2_date__A7QWu")
    for delta in range(3):
        if delta >= len(date_buttons):
            continue
        btn = date_buttons[delta]
        show_date = (datetime.now() + timedelta(days=delta)).strftime("%Y%m%d")
        await btn.click()
        await page.wait_for_timeout(1500)  # wait JS to render showtimes
        
        # Parse theatres for this date
        soup = BeautifulSoup(await page.content(), "lxml")
        for block in soup.select("li[class*='MovieSessionsListing_movieSessions']"):
            tname = block.select_one("div[class*='MovieSessionsListing_titleFlex'] a")
            if not tname:
                continue
            theatre_name = tname.get_text(strip=True)
            shows = []
            for t in block.select("div.greenCol"):
                time = t.find(string=True, recursive=False)
                fmt = t.find("span")
                if time:
                    shows.append({
                        "time": time.strip(),
                        "format": fmt.get_text(strip=True) if fmt else "2D"
                    })
            if shows:
                if theatre_name not in theatres_dict:
                    theatres_dict[theatre_name] = {}
                if show_date not in theatres_dict[theatre_name]:
                    theatres_dict[theatre_name][show_date] = []
                existing = theatres_dict[theatre_name][show_date]
                for s in shows:
                    if s not in existing:
                        existing.append(s)
    
    # Skip if no showtimes
    if not theatres_dict:
        return None

    theatres = [{"name": k, "dates": v} for k, v in theatres_dict.items()]
    return {"poster_url": poster_url, "certificate": certificate, "duration": duration, "theatres": theatres}

# ---------------- MAIN ----------------
async def run_all_cities():
    final_data = {"date": TODAY, "cities": {}}
    save_json(final_data)  # fresh file
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for city in TAMILNADU_CITIES:
            print(f"\n🌆 CITY: {city}")
            context = await browser.new_context()
            page = await context.new_page()
            
            try:
                movies = await get_movies(page, city)
                city_movies = []
                
                for movie in movies:
                    title = normalize_title(movie["title"])
                    print("  🎬", title)
                    
                    details = await get_movie_details(page, movie["url"])
                    if not details:
                        continue
                    
                    poster = await download_poster(page, details["poster_url"], title)
                    city_movies.append({
                        "title": title,
                        "image": poster,
                        "details": {
                            "duration": details["duration"],
                            "certificate": details["certificate"]
                        },
                        "theatres": details["theatres"]
                    })
                
                if city_movies:
                    final_data["cities"][city] = {"movies": city_movies}
                    save_json(final_data)
                    print(f"💾 Saved {city}")
            
            except Exception as e:
                print(f"❌ Error in {city}: {e}")
            
            await context.close()
        await browser.close()
    
    print("\n✅ Scraping finished")
    print("📄 JSON:", JSON_FILE)
    print("🖼️ Posters:", POSTER_DIR)

# ---------------- RUN ----------------
if __name__ == "__main__":
    asyncio.run(run_all_cities())
