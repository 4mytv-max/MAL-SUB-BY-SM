"""MAL SUB BY SM — merged Malayalam subtitle addon (Stremio/Nuvio).

Sources:
  1. Msone       — LIVE relay of the official addon API
                   (https://addon.malayalamsubtitles.org), 1h cache on hits,
                   5min cache on misses. New Msone subtitles appear immediately.
  2. Team GOAT    — local index data/teamgoat_index.json, refreshed DAILY at
                   12:00 AM IST by tools/crawl_teamgoat.py (live per-request
                   lookup is not possible: no IMDb-searchable API on the site).
  3. Movie Mirror — local index data/moviemirror_index.json, refreshed DAILY at
                   12:00 AM IST by tools/crawl_moviemirror.py (the site sits
                   behind an intermittent JS anti-bot challenge, so live
                   per-request lookup is not reliable).

Subtitle-only addon: no catalogs, no streams, no P2P.
"""
import json
import os
import re
import time

import requests
from flask import Flask, jsonify

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

IMDB_RE = re.compile(r"^tt\d+$")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
    }
)

MSONE_MOVIE_URL = "https://addon.malayalamsubtitles.org/subtitles/movie/{imdb}.json"
MSONE_SERIES_URL = "https://addon.malayalamsubtitles.org/subtitles/series/{imdb}.json"
MSONE_CACHE_TTL = 3600  # 1 hour for hits
MSONE_MISS_TTL = 300    # 5 minutes for misses/failures (don't blank on transient errors)
_msone_cache = {}  # (kind, imdb) -> (timestamp, ttl, [entries])


def load_index(filename):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


TEAMGOAT_INDEX = load_index("teamgoat_index.json")
MOVIEMIRROR_INDEX = load_index("moviemirror_index.json")


def msone_subtitles(imdb, kind):
    """Live-relay the official Msone addon subtitle endpoint (1h cache)."""
    now = time.time()
    key = (kind, imdb)
    hit = _msone_cache.get(key)
    if hit and now - hit[0] < hit[1]:
        return hit[2]

    entries = []
    url = (MSONE_MOVIE_URL if kind == "movie" else MSONE_SERIES_URL).format(imdb=imdb)
    try:
        resp = SESSION.get(url, timeout=10)
        if resp.status_code == 200:
            for s in resp.json().get("subtitles", []):
                surl = s.get("url")
                if not surl:
                    continue
                label = s.get("label") or s.get("id") or "Msone subtitle"
                entries.append(
                    {
                        "id": "msone-{}".format(s.get("id", imdb)),
                        "url": surl,
                        "lang": "mal",
                        "label": "[Msone] {}".format(label),
                    }
                )
    except Exception:
        # One dead source must never break the whole response.
        pass

    ttl = MSONE_CACHE_TTL if entries else MSONE_MISS_TTL
    _msone_cache[key] = (now, ttl, entries)
    return entries


def index_subtitles(index, imdb, source):
    """Subtitles from a local JSON index: {imdb: [{title, url}, ...]}."""
    entries = []
    for item in index.get(imdb, []) or []:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        title = (item.get("title") or imdb).strip()
        entries.append(
            {
                "id": "{}-{}-{}".format(
                    source.lower().replace(" ", ""), imdb, len(entries)
                ),
                "url": url,
                "lang": "mal",
                "label": "[{}] {}".format(source, title),
            }
        )
    return entries


def merged_subtitles(imdb, kind):
    subs = []
    seen_urls = set()

    def add(entries):
        for e in entries:
            if e["url"] in seen_urls:
                continue
            seen_urls.add(e["url"])
            subs.append(e)

    add(msone_subtitles(imdb, kind))            # live
    add(index_subtitles(TEAMGOAT_INDEX, imdb, "Team GOAT"))
    add(index_subtitles(MOVIEMIRROR_INDEX, imdb, "Movie Mirror"))
    return {"subtitles": subs}


@app.route("/manifest.json")
def manifest():
    return jsonify(
        {
            "id": "org.sm.malsub",
            "version": "1.0.0",
            "name": "MAL SUB BY SM",
            "description": "Malayalam subtitles from Msone, Team GOAT and Movie Mirror.",
            "resources": ["subtitles"],
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
            "behaviorHints": {"configurable": False, "p2p": False},
        }
    )


@app.route("/subtitles/movie/<imdb>.json")
def subtitles_movie(imdb):
    if not IMDB_RE.match(imdb):
        return jsonify({"subtitles": []})
    return jsonify(merged_subtitles(imdb, "movie"))


@app.route("/subtitles/series/<imdb>.json")
def subtitles_series(imdb):
    if not IMDB_RE.match(imdb):
        return jsonify({"subtitles": []})
    return jsonify(merged_subtitles(imdb, "series"))


@app.route("/subtitles/series/<imdb>:<season>:<episode>.json")
def subtitles_episode(imdb, season, episode):
    if not IMDB_RE.match(imdb):
        return jsonify({"subtitles": []})
    # Episode-level: return the merged series set; players match by filename.
    return jsonify(merged_subtitles(imdb, "series"))


@app.route("/")
def home():
    return (
        "<h3>MAL SUB BY SM</h3>"
        "<p>Malayalam subtitles from Msone (live), Team GOAT and Movie Mirror (daily refresh).</p>"
        "<p>Team GOAT titles indexed: {}<br>Movie Mirror titles indexed: {}</p>"
        '<p>Install in Stremio/Nuvio: <a href="/manifest.json">manifest.json</a></p>'.format(
            len(TEAMGOAT_INDEX), len(MOVIEMIRROR_INDEX)
        )
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
