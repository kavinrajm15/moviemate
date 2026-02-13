from flask import Flask, render_template, request,redirect, url_for, session
import sqlite3
from datetime import datetime, timedelta

import requests
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)


app.secret_key = "qwerty"
UPLOAD_FOLDER = os.path.join("static", "posters")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS



DB = "movies.db"
TODAY = datetime.now().strftime("%Y%m%d")

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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
    



    # admin page



@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == "admin" and password == "4321":
            session["admin"] = True
            return redirect(url_for("admin_cities"))
    return render_template("admin_login.html")
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

@app.route("/admin/cities")
def admin_cities():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    conn = get_db()
    cities = conn.execute("""
        SELECT DISTINCT city FROM theatres
        ORDER BY city
    """).fetchall()
    conn.close()

    return render_template("admin_cities.html", cities=cities)

@app.route("/admin/city/<city>")
def admin_city_movies(city):
    search = request.args.get("search", "").strip()

    conn = get_db()
    cur = conn.cursor()

    if search:
        cur.execute("""
            SELECT DISTINCT m.movie_id, m.title, m.image
            FROM movies m
            JOIN showtimes s ON m.movie_id = s.movie_id
            JOIN theatres t ON s.theatre_id = t.theatre_id
            WHERE t.city = ? AND m.title LIKE ?
            ORDER BY m.title
        """, (city.lower(), f"%{search}%"))
    else:
        cur.execute("""
            SELECT DISTINCT m.movie_id, m.title, m.image
            FROM movies m
            JOIN showtimes s ON m.movie_id = s.movie_id
            JOIN theatres t ON s.theatre_id = t.theatre_id
            WHERE t.city = ?
            ORDER BY m.title
        """, (city.lower(),))

    movies = cur.fetchall()
    conn.close()

    return render_template(
        "admin_city_movies.html",
        movies=movies,
        city=city,
        search=search
    )

@app.route("/admin/movie/<int:movie_id>")
def admin_movie_detail(movie_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    city = request.args.get("city")

    conn = get_db()

    movie = conn.execute(
        "SELECT * FROM movies WHERE movie_id=?",
        (movie_id,)
    ).fetchone()

    theatres = conn.execute("""
        SELECT theatre_id, name
        FROM theatres
        WHERE city = ?
        ORDER BY name
    """, (city.lower(),)).fetchall()

    showtimes = conn.execute("""
        SELECT s.showtime_id, t.name, s.show_time, s.format, s.date, s.theatre_id
        FROM showtimes s
        JOIN theatres t ON s.theatre_id = t.theatre_id
        WHERE s.movie_id=? AND t.city=?
        ORDER BY s.date, t.name
    """, (movie_id, city.lower())).fetchall()

    conn.close()

    return render_template(
        "admin_movie_detail.html",
        movie=movie,
        theatres=theatres,
        showtimes=showtimes,
        city=city
    )

@app.route("/admin/theatre/add", methods=["POST"])
def add_theatre():
    name = request.form["name"]
    city = request.form["city"]

    conn = get_db()
    conn.execute(
        "INSERT INTO theatres (name, city) VALUES (?, ?)",
        (name.strip(), city.lower())
    )
    conn.commit()
    conn.close()

    return redirect(request.referrer)

@app.route("/admin/showtime/add", methods=["POST"])
def add_showtime():
    movie_id = request.form["movie_id"]
    theatre_id = request.form["theatre_id"]
    show_time = request.form["show_time"]
    format_ = request.form["format"]
    date = request.form["date"]

    conn = get_db()
    conn.execute("""
        INSERT INTO showtimes
        (movie_id, theatre_id, show_time, format, date)
        VALUES (?, ?, ?, ?, ?)
    """, (movie_id, theatre_id, show_time, format_, date))

    conn.commit()
    conn.close()

    return redirect(request.referrer)

@app.route("/admin/showtime/delete/<int:id>")
def delete_showtime(id):
    conn = get_db()
    conn.execute("DELETE FROM showtimes WHERE showtime_id=?", (id,))
    conn.commit()
    conn.close()

    return redirect(request.referrer)

@app.route("/admin/movie/update_image/<int:movie_id>", methods=["POST"])
def update_movie_image(movie_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    file = request.files.get("image")

    if file and file.filename:
        filename = secure_filename(file.filename)

        # Save new image
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        image_path = f"posters/{filename}"

        conn = get_db()

        # Get old image
        old = conn.execute(
            "SELECT image FROM movies WHERE movie_id=?",
            (movie_id,)
        ).fetchone()

        if old and old["image"]:
            old_path = os.path.join("static", old["image"])
            if os.path.exists(old_path):
                os.remove(old_path)

        conn.execute(
            "UPDATE movies SET image=? WHERE movie_id=?",
            (image_path, movie_id)
        )

        conn.commit()
        conn.close()

    return redirect(request.referrer)





if __name__ == "__main__":
    # app.run(host="192.168.58.245", port=5000, debug=True)
    app.run(host="0.0.0.0", port=5000, debug=True,use_reloader=False)
