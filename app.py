from flask import Flask, render_template, request
import sqlite3
from datetime import datetime, timedelta
import requests

app = Flask(__name__)

DB = "movies.db"
TODAY = datetime.now().strftime("%Y%m%d")

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def normalize_date(d):
    if not d:
        return TODAY
    return d.replace("-", "").strip()


def get_next_dates(days=3):
    base = datetime.now()
    return [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]

@app.template_filter("dayonly")
def dayonly(value):
    return value[-2:]

@app.context_processor
def inject_cities():
    conn = get_db()
    cities = conn.execute(
        "SELECT DISTINCT city FROM theatres ORDER BY city"
    ).fetchall()
    conn.close()
    return dict(cities=cities)

@app.route("/")
def home():
    date = normalize_date(request.args.get("date"))

    conn = get_db()
    movies = conn.execute("""
        SELECT DISTINCT
            m.movie_id,
            m.title,
            m.image,
            m.duration,
            m.genres,
            m.certificate
        FROM movies m
        JOIN showtimes s ON m.movie_id = s.movie_id
        WHERE s.date = ?
        ORDER BY m.title
        LIMIT 6
    """, (date,)).fetchall()
    conn.close()

    return render_template("home.html", movies=movies)

@app.route("/load_movies")
def load_movies():
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 4))
    date = normalize_date(request.args.get("date"))

    conn = get_db()
    movies = conn.execute("""
        SELECT DISTINCT
            m.title,
            m.image
        FROM movies m
        JOIN showtimes s ON m.movie_id = s.movie_id
        WHERE s.date = ?
        ORDER BY m.title
        LIMIT ? OFFSET ?
    """, (date, limit, offset)).fetchall()
    conn.close()

    return {"movies": [dict(m) for m in movies]}

@app.route("/movies")
def movies():
    city = request.args.get("city")
    date = normalize_date(request.args.get("date"))
    dates = get_next_dates(3)

    if not city:
        return render_template(
            "movies.html",
            movies=[],
            city=None,
            date=date,
            dates=dates
        )

    conn = get_db()
    movies = conn.execute("""
        SELECT DISTINCT
            m.movie_id,
            m.title,
            m.image,
            m.duration,
            m.genres,
            m.certificate
        FROM movies m
        JOIN showtimes s ON m.movie_id = s.movie_id
        JOIN theatres t ON s.theatre_id = t.theatre_id
        WHERE t.city = ?
          AND s.date = ?
        ORDER BY m.title
        LIMIT 6
    """, (city, date)).fetchall()
    conn.close()

    return render_template(
        "movies.html",
        movies=movies,
        city=city,
        date=date,
        dates=dates
    )

@app.route("/load_movies_by_city")
def load_movies_by_city():
    city = request.args.get("city")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 6))
    date = normalize_date(request.args.get("date"))

    if not city:
        return {"movies": []}

    conn = get_db()
    movies = conn.execute("""
        SELECT DISTINCT
            m.movie_id,
            m.title,
            m.image,
            m.duration,
            m.genres,
            m.certificate
        FROM movies m
        JOIN showtimes s ON m.movie_id = s.movie_id
        JOIN theatres t ON s.theatre_id = t.theatre_id
        WHERE t.city = ?
          AND s.date = ?
        ORDER BY m.title
        LIMIT ? OFFSET ?
    """, (city, date, limit, offset)).fetchall()
    conn.close()

    return {"movies": [dict(m) for m in movies]}

@app.route("/theatres")
def theatres():
    movie_id = request.args.get("movie_id")
    city = request.args.get("city")
    date = normalize_date(request.args.get("date"))

    conn = get_db()

    # movie details
    movie = conn.execute("""
        SELECT title, duration, genres, certificate,image
        FROM movies
        WHERE movie_id = ?
    """, (movie_id,)).fetchone()


    date_rows = conn.execute("""
    SELECT DISTINCT s.date
    FROM showtimes s
    JOIN theatres t ON s.theatre_id = t.theatre_id
    WHERE s.movie_id = ?
      AND t.city = ?
      AND s.date >= ?
    ORDER BY s.date
     """, (movie_id, city, TODAY)).fetchall()


    dates = []
    for r in date_rows:
        d = r["date"]  
        dt = datetime.strptime(d, "%Y%m%d")

        dates.append({
            "raw": d,
            "day": dt.strftime("%a"),
            "date": dt.strftime("%d"),
            "month": dt.strftime("%b")
        })


    # showtimes for selected date
    rows = conn.execute("""
        SELECT
            t.name,
            s.show_time,
            s.format
        FROM showtimes s
        JOIN theatres t ON s.theatre_id = t.theatre_id
        WHERE s.movie_id = ?
          AND t.city = ?
          AND s.date = ?
        ORDER BY
          t.name,
          CASE
            WHEN s.show_time LIKE '%AM' THEN
              time(substr(s.show_time, 1, length(s.show_time)-3))
            ELSE
              time(substr(s.show_time, 1, length(s.show_time)-3), '+12 hours')
          END
    """, (movie_id, city, date)).fetchall()

    conn.close()

    theatres = {}
    for r in rows:
        theatres.setdefault(r["name"], []).append({
            "time": r["show_time"],
            "format": r["format"]
        })

    return render_template(
        "theatres.html",
        theatres=theatres,
        city=city,
        movie_title=movie["title"],
        movie=movie,
        dates=dates,
        selected_date=date,
        movie_id=movie_id
    )


@app.route("/api/city-autocomplete")
def city_autocomplete():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return []

    url = "https://api.olamaps.io/places/v1/autocomplete"
    headers = {"X-API-Key": "l9HoM1Ojy9lJiva1rW9kGqU1ha5uvzTekDA0ZeCK"}
    params = {"input": query, "components": "country:IN"}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        data = r.json()

        results = []
        for p in data.get("predictions", []):
            main = p.get("structured_formatting", {}).get("main_text", "")
            desc = p.get("description", "")

            if "Tamil Nadu" not in desc:
                continue

            text = (main + " " + desc).lower()
            if any(x in text for x in [
                "junction", "station", "airport", "market",
                "hospital", "terminal", "school","district",
                "bus stand", "busstand","street","main","govt",
                "road"
            ]):
                continue

            if main:
                results.append(main.lower())

        return list(dict.fromkeys(results))

    except Exception as e:
        print("Autocomplete error:", e)
        return []

if __name__ == "__main__":
    # app.run(host="192.168.58.245", port=5000, debug=True)
    app.run(host="0.0.0.0", port=5000, debug=True,use_reloader=False)
