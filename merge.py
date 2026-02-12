import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB = "movies.db"

JSON_FILES = [
    "tamilnadu_bms.json",
    "tamilnadu_ticketnew.json"
]

# DB SETUP
def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.executescript("""
    DROP TABLE IF EXISTS showtimes;
    DROP TABLE IF EXISTS theatres;
    DROP TABLE IF EXISTS movies;

    CREATE TABLE movies (
        movie_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT UNIQUE,
        image TEXT,
        duration TEXT,
        genres TEXT,
        certificate TEXT
    );

    CREATE TABLE theatres (
        theatre_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        city TEXT,
        UNIQUE(name, city)
    );

    CREATE TABLE showtimes (
        showtime_id INTEGER PRIMARY KEY AUTOINCREMENT,
        movie_id INTEGER,
        theatre_id INTEGER,
        show_time TEXT,
        format TEXT,
        date TEXT,
        UNIQUE(movie_id, theatre_id, show_time, format, date)
    );
    """)

    conn.commit()
    return conn

# HELPERS
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_or_create_movie(cur, m):
    cur.execute("""
        INSERT OR IGNORE INTO movies
        (title, image, duration, genres, certificate)
        VALUES (?, ?, ?, ?, ?)
    """, (
        m["title"].strip(),
        m.get("image"),
        m.get("details", {}).get("duration"),
        ",".join(m.get("details", {}).get("genres", [])),
        m.get("details", {}).get("certificate")
    ))

    cur.execute("SELECT movie_id FROM movies WHERE title = ?", (m["title"].strip(),))
    return cur.fetchone()[0]


def get_or_create_theatre(cur, name, city):
    cur.execute("""
        INSERT OR IGNORE INTO theatres (name, city)
        VALUES (?, ?)
    """, (name.strip(), city.lower()))

    cur.execute("""
        SELECT theatre_id FROM theatres
        WHERE name = ? AND city = ?
    """, (name.strip(), city.lower()))

    return cur.fetchone()[0]

# MERGE LOGIC WITH DATES
def merge_json(conn, data):
    cur = conn.cursor()

    for city, city_data in data.get("cities", {}).items():
        city = city.lower().strip()

        for movie in city_data.get("movies", []):
            movie_id = get_or_create_movie(cur, movie)

            for theatre in movie.get("theatres", []):
                theatre_id = get_or_create_theatre(cur, theatre["name"], city)

                seen = set()
                # Loop over all dates for this theatre
                for show_date, show_list in theatre.get("dates", {}).items():
                    for st in show_list:
                        key = (st["time"], st.get("format"), show_date)
                        if key in seen:
                            continue
                        seen.add(key)

                        cur.execute("""
                            INSERT OR IGNORE INTO showtimes
                            (movie_id, theatre_id, show_time, format, date)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            movie_id,
                            theatre_id,
                            st["time"],
                            st.get("format"),
                            show_date
                        ))

    conn.commit()


if __name__ == "__main__":
    print(" Rebuilding movies.db")
    conn = init_db()

    for jf in JSON_FILES:
        if Path(jf).exists():
            print(f"Merging {jf}")
            merge_json(conn, load_json(jf))
        else:
            print(f" Missing file: {jf}")

    conn.close()
    print("Merge complete. movies.db ready ")
