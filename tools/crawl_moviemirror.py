#!/usr/bin/env python3
"""Movie Mirror (moviemirrorsubtitles.com) subtitle index crawler.

Builds a JSON index: {"tt1234567": [{"title": "Post Title", "url": "..."}]}.

Phase 1: enumerate all posts via the WP REST API (per_page=100, walk pages).
Phase 2: fetch each post's HTML page and extract:
    - IMDb ID from the movie-info table (imdb.com/title/ttXXXXXXX)
    - direct .srt URL from the url-decoded ?custom_download= target
      (fallback: any .srt under /wp-content/uploads/, then /download/{id}/ as-is)

HARD STOP: on HTTP 403/429 the script saves partial progress and exits(2).

Usage: python3 crawl_moviemirror.py
Deps: stdlib + requests
"""
import html
import json
import os
import re
import sys
import time
from urllib.parse import unquote, urlparse

import requests

BASE = "https://moviemirrorsubtitles.com"
API = BASE + "/wp-json/wp/v2/posts"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 20

ROOT = os.path.expanduser("~/workspace/malsub-by-sm")
DATA = os.path.join(ROOT, "data")
INDEX_PATH = os.path.join(DATA, "moviemirror_index.json")
CHECKPOINT_PATH = os.path.join(DATA, "crawl_checkpoint.json")

os.makedirs(DATA, exist_ok=True)

sess = requests.Session()
sess.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


class BlockedError(RuntimeError):
    pass


def polite_get(url, label):
    """GET with hard stop on 403/429. Returns response or raises BlockedError."""
    try:
        r = sess.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        return None, "request-error: %s" % e
    if r.status_code in (403, 429):
        raise BlockedError("%s -> HTTP %s on %s" % (label, r.status_code, url))
    time.sleep(1)  # polite delay after every request
    return r, None


def load_checkpoint():
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posts": [], "done_ids": [], "failed": {}, "warned": []}


def save_checkpoint(cp):
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=1)


def save_index(index):
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)


def phase1_enumerate(cp):
    if cp["posts"]:
        print("Phase 1 already done: %d posts from checkpoint." % len(cp["posts"]),
              flush=True)
        return cp
    posts = []
    page = 1
    while True:
        r, err = polite_get("%s?per_page=100&page=%d" % (API, page),
                            "api-page-%d" % page)
        if r is None:
            print("API page %d failed (%s); stopping enumeration." % (page, err),
                  flush=True)
            break
        items = r.json()
        if not isinstance(items, list) or not items:
            if isinstance(items, dict):
                print("API page %d returned object (%s); stopping enumeration."
                      % (page, items.get("code", "?")), flush=True)
            break
        for p in items:
            if not isinstance(p, dict):
                continue
            posts.append({
                "id": p.get("id"),
                "title": html.unescape((p.get("title") or {}).get("rendered") or "").strip(),
                "link": p.get("link", ""),
                "slug": p.get("slug", ""),
            })
        print("API page %d: %d posts (total %d)" % (page, len(items), len(posts)),
              flush=True)
        page += 1
    cp["posts"] = posts
    save_checkpoint(cp)
    return cp


IMDB_RE = re.compile(r"imdb\.com/title/(tt\d{6,})", re.I)
CD_RE = re.compile(r'href="([^"]*custom_download=([^"&]+)[^"]*)"', re.I)
SRT_HREF_RE = re.compile(r'href="([^"]*\.srt[^"]*)"', re.I)
DL_ROUTE_RE = re.compile(r'href="([^"]*/download/\d+/?[^"]*)"', re.I)
POST_ID_RE = re.compile(r"[?&]post_id=(\d+)")


def extract_from_page(page_html, post_id):
    """Returns (imdb_id or None, list of download urls, list of warnings)."""
    warns = []
    h = html.unescape(page_html)

    ids = IMDB_RE.findall(h)
    uniq = []
    for i in ids:
        if i not in uniq:
            uniq.append(i)
    if len(uniq) > 1:
        warns.append("multiple imdb ids %s" % uniq)
    imdb_id = uniq[0] if uniq else None

    urls = []
    seen = set()

    def add(u):
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    # 1) custom_download targets (preferred): decode, must end in .srt
    for full, enc in CD_RE.findall(h):
        m = POST_ID_RE.search(full)
        if m and int(m.group(1)) != post_id:
            warns.append("custom_download post_id=%s != post %d" % (m.group(1), post_id))
        target = unquote(enc)
        parsed = urlparse(target)
        if parsed.scheme in ("http", "https") and parsed.path.lower().endswith(".srt"):
            add(target)

    # 2) fallback: any .srt under /wp-content/uploads/
    if not urls:
        for href in SRT_HREF_RE.findall(h):
            parsed = urlparse(href)
            if "wp-content/uploads" in parsed.path and parsed.path.lower().endswith(".srt"):
                add(href)

    # 3) fallback: Download Monitor /download/{id}/ route, kept as-is
    if not urls:
        for href in DL_ROUTE_RE.findall(h):
            add(href)

    return imdb_id, urls, warns


def phase2_crawl(cp, index):
    posts = cp["posts"]
    done = set(cp["done_ids"])
    total = len(posts)
    started = len(done)
    print("Phase 2: crawling %d post pages (%d already done)" % (total, started),
          flush=True)
    for n, p in enumerate(posts, 1):
        pid = p.get("id")
        if pid in done or not p.get("link"):
            if pid is not None:
                done.add(pid)
            continue
        try:
            r, err = polite_get(p["link"], "post-%d" % pid)
        except BlockedError as e:
            print("HARD STOP: %s" % e, flush=True)
            save_checkpoint(cp)
            save_index(index)
            sys.exit(2)
        if r is None or r.status_code != 200:
            reason = (err or "http-%s" % (r.status_code if r else "?"))
            cp["failed"][str(pid)] = reason
            # Transient network/server errors are NOT marked done, so the next
            # run retries them instead of silently dropping the titles forever.
            # Only genuine data gaps (no-imdb-id / no-download-url below) are final.
            transient = reason.startswith("request-error:") or (
                r is not None and r.status_code in (429, 500, 502, 503, 504))
            if not transient:
                done.add(pid)
                cp["done_ids"] = sorted(done)
            if n % 50 == 0:
                save_checkpoint(cp)
                save_index(index)
            continue
        imdb_id, urls, warns = extract_from_page(r.text, pid)
        for w in warns:
            cp["warned"].append({"post_id": pid, "warn": w})
        if imdb_id and urls:
            entry_list = index.setdefault(imdb_id, [])
            for u in urls:
                entry_list.append({"title": p["title"], "url": u})
        elif not imdb_id:
            cp["failed"][str(pid)] = "no-imdb-id"
        else:
            cp["failed"][str(pid)] = "no-download-url"
        done.add(pid)
        cp["done_ids"] = sorted(done)
        if n % 50 == 0 or n == total:
            save_checkpoint(cp)
            save_index(index)
            print("  progress %d/%d, index has %d titles" % (n, total, len(index)),
                  flush=True)
    save_checkpoint(cp)
    save_index(index)


def main():
    cp = load_checkpoint()
    try:
        cp = phase1_enumerate(cp)
    except BlockedError as e:
        print("HARD STOP: %s" % e, flush=True)
        save_checkpoint(cp)
        sys.exit(2)
    if not cp["posts"]:
        print("No posts enumerated; nothing to crawl.", flush=True)
        sys.exit(1)
    index = {}
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            index = json.load(f)
    try:
        phase2_crawl(cp, index)
    except BlockedError as e:
        print("HARD STOP: %s" % e, flush=True)
        save_checkpoint(cp)
        save_index(index)
        sys.exit(2)
    save_checkpoint(cp)
    save_index(index)
    failed = len(cp["failed"])
    warned = len(cp["warned"])
    print("DONE: %d titles indexed, %d posts failed, %d warnings." %
          (len(index), failed, warned), flush=True)
    if failed:
        print("Failed post ids:", sorted(cp["failed"].keys()), flush=True)
    print("Index:", INDEX_PATH, flush=True)


if __name__ == "__main__":
    main()
