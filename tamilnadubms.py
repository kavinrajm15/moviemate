import cloudscraper
from bs4 import BeautifulSoup
import json
import os
import time
import random
from datetime import datetime, timedelta
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
POSTER_DIR = os.path.join(STATIC_DIR, "posters")
os.makedirs(POSTER_DIR, exist_ok=True)

def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"\(\d{4}\)", "", t) 
    t = re.sub(r"[:\-–—]", " ", t)  
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip() 
    return t.title()

def random_sleep(a=0.4, b=0.8):
    time.sleep(random.uniform(a, b))

def safe_get(url, **kwargs):
    try:
        r = scraper.get(url, timeout=30, **kwargs)
        if r.status_code != 200 or len(r.text) < 800:
            return None
        return r.text
    except:
        return None

def extract_movie_details(movie_url):
    html = safe_get(movie_url)
    if not html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    box = soup.find("div", class_="sc-2k6tnd-1 dGsSXW")
    if not box:
        return {}
    text = box.get_text(" ", strip=True)
    parts = [p.strip() for p in text.split("•") if p.strip()]
    duration = None
    certificate = None
    for p in parts:
        if re.search(r"\d+h\s*\d+m", p):
            duration = p
        elif re.fullmatch(r"U|UA|A|S", p):
            certificate = p
    genres = [a.get_text(strip=True) for a in box.find_all("a")]
    return {"duration": duration, "genres": genres, "certificate": certificate}

def get_movie_image(movie_url):
    html = safe_get(movie_url)
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    img = soup.find("img", class_="sc-echj48-5 hXdwek")
    return img["src"] if img else None

def download_image(image_url, movie_code):
    if not image_url:
        return None
    filename = f"{movie_code}.jpg"
    filepath = os.path.join(POSTER_DIR, filename)
    if os.path.exists(filepath):
        return f"posters/{filename}"
    r = scraper.get(image_url)
    with open(filepath, "wb") as f:
        f.write(r.content)
    return f"posters/{filename}"

def extract_buy_urls(soup):
    urls = []
    container = soup.find("div", class_="sc-5v6xxo-11 ifgIyO")
    if not container:
        return urls
    for a in container.find_all("a", href=True):
        if "/buytickets/" in a["href"]:
            urls.append("https://in.bookmyshow.com" + a["href"])
    return list(set(urls))

TAMILNADU_CITIES = [
    "chennai","coimbatore","madurai","salem","tirupur","trichy","vellore",
    "tirunelveli","erode","rajapalayam","chengalpattu","kanchipuram","ooty",
    "pondicherry","villupuram","karur","nagercoil","thanjavur","hosur",
    "dindigul","pudukkottai","pollachi","panruti"
]

today = datetime.now().strftime("%Y%m%d")
json_file = os.path.join(BASE_DIR, "tamilnadu_bms.json")

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)

final_data = {"date": today, "cities": {}}

for city in TAMILNADU_CITIES:
    print(f"\n🌆 City: {city}")
    explore_url = f"https://in.bookmyshow.com/explore/movies-{city}?cat=MT"
    html = safe_get(explore_url)
    if not html:
        continue
    soup = BeautifulSoup(html, "lxml")
    random_sleep()

    movies = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if data.get("@type") == "ItemList":
                movies.extend(data.get("itemListElement", []))
        except:
            pass

    final_data["cities"][city] = {"movies": []}

    for movie in movies:
        raw_title = movie.get("name")
        title = normalize_title(raw_title)
        movie_url = movie.get("url")
        movie_code = movie_url.rstrip("/").split("/")[-1]

        print("  🎬", title)

        image_url = get_movie_image(movie_url)
        image_path = download_image(image_url, movie_code)
        details = extract_movie_details(movie_url)

        movie_entry = {"title": title, "image": image_path, "details": details, "theatres": []}

        for delta in range(3):
            show_date = (datetime.now() + timedelta(days=delta)).strftime("%Y%m%d")
            buy_url = f"https://in.bookmyshow.com/movies/{city}/{title.replace(' ','-').lower()}/buytickets/{movie_code}/{show_date}"

            html = safe_get(buy_url, cookies={"bmsAgeGatePassed": "true"})
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            buy_urls = extract_buy_urls(soup) or [buy_url]

            for url in buy_urls:
                html = safe_get(url, cookies={"bmsAgeGatePassed": "true"})
                if not html:
                    continue
                sub = BeautifulSoup(html, "lxml")
                container = sub.find("div", class_="sc-tk4ce6-2 jroiZB")
                if not container:
                    continue

                for th in container.find_all("div", class_="sc-e8nk8f-3 kJBeM"):
                    name_tag = th.find("span", class_="sc-1qdowf4-0 eXSbEM")
                    theatre_name = name_tag.get_text(strip=True) if name_tag else "Unknown"

                    time_box = th.find_next("div", class_="sc-1vhizuf-0 cmhoRs")
                    times = time_box.find_all("div", class_="sc-1vhizuf-2 euWjeN") if time_box else []

                    showtimes = [
                        {"time": t.find(string=True, recursive=False).strip() if t.find(string=True, recursive=False) else "",
                         "format": t.find("span").get_text(strip=True) if t.find("span") else "2D"}
                        for t in times
                    ]

                    if showtimes:
                        theatre = next((th for th in movie_entry["theatres"] if th["name"] == theatre_name), None)
                        if not theatre:
                            theatre = {"name": theatre_name, "dates": {}}
                            movie_entry["theatres"].append(theatre)
                        if show_date not in theatre["dates"]:
                            theatre["dates"][show_date] = showtimes
                        else:
                            existing = theatre["dates"][show_date]
                            for s in showtimes:
                                if s not in existing:
                                    existing.append(s)

        deduped_theatres = {}
        for theatre in movie_entry["theatres"]:
            name = theatre["name"]
            if name not in deduped_theatres:
                deduped_theatres[name] = {"name": name, "dates": theatre["dates"]}
            else:
                for date, shows in theatre["dates"].items():
                    if date in deduped_theatres[name]["dates"]:
                        existing = deduped_theatres[name]["dates"][date]
                        for show in shows:
                            if show not in existing:
                                existing.append(show)
                    else:
                        deduped_theatres[name]["dates"][date] = shows
        movie_entry["theatres"] = list(deduped_theatres.values())

        final_data["cities"][city]["movies"].append(movie_entry)
        random_sleep()
        
with open(json_file, "w", encoding="utf-8") as f:
    json.dump(final_data, f, indent=4, ensure_ascii=False)

print("\n✅ Scraping complete")
print("📁 Posters:", POSTER_DIR)
print("📄 JSON saved to:", json_file)
