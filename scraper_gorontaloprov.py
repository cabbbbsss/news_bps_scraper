import re
import time
import requests
import pymysql  # <-- ganti driver
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    )
}

def get_soup(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"[ERROR] {url} -> {e}")
        return None

def extract_date_from_url(url):
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if m:
        y, mth, d = map(int, m.groups())
        return datetime(y, mth, d).date()
    return None

def extract_reporter(contents):
    lines = [line.strip() for line in contents.split("\n") if line.strip()]
    if not lines:
        return "-"
    last_line = lines[-1]
    m = re.search(r"Pewarta\s*:\s*(.+)$", last_line, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return "-"

def fetch_articles(category_url, start_date, end_date, db_config, max_pages=50):
    def extract_title(soup_art):
        meta_title = soup_art.select_one('meta[property="og:title"]')
        if meta_title and meta_title.get("content"):
            return meta_title["content"].strip()
        h1 = soup_art.select_one("h1.entry-title")
        return h1.get_text(strip=True) if h1 else None

    def extract_date(soup_art, url):
        meta_date = soup_art.select_one('meta[property="article:published_time"]')
        if meta_date and meta_date.get("content"):
            return datetime.fromisoformat(meta_date["content"].split("T")[0]).date()
        return extract_date_from_url(url)

    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM news_articles")
    db_titles = set(row[0] for row in cursor.fetchall())
    session_titles = set()

    for page in range(1, max_pages + 1):
        url_page = category_url if page == 1 else f"{category_url}page/{page}/"
        print(f"Fetching page {page}: {url_page}")

        soup = get_soup(url_page)
        if not soup:
            break

        links = soup.select("article h2 a")
        if not links:
            print("[INFO] No more articles on this page, stopping.")
            break

        # Assume articles are sorted newest → oldest
        stop_category = False

        for a in links:
            url = a.get("href")
            if not url:
                continue

            date_val = extract_date_from_url(url)
            # If date cannot be parsed from URL, fetch article to get it
            soup_art = None
            if not date_val:
                soup_art = get_soup(url)
                if not soup_art:
                    continue
                date_val = extract_date(soup_art, url)

            if not date_val:
                continue

            if date_val < start_date:
                print(f"Skipped   : {url} ({date_val}) — older than start_date")
                stop_category = True
                break  # stop processing links on this page

            if date_val > end_date:
                print(f"Skipped   : {url} ({date_val}) — after end_date")
                continue

            # Fetch article HTML if not already fetched
            if not soup_art:
                soup_art = get_soup(url)
                if not soup_art:
                    continue

            title = extract_title(soup_art)
            if not title:
                continue

            if title in db_titles or title in session_titles:
                print(f"Duplicate : {title}")
                continue

            paras = soup_art.select("div.elementor-widget-theme-post-content p") \
                    or soup_art.select("article p")
            content_texts = [p.get_text(strip=True) for p in paras if p.get_text(strip=True)]
            if not content_texts:
                continue

            contents = "\n".join(content_texts)
            reporter_name = extract_reporter(contents)

            row = {
                "date": date_val.isoformat(),
                "title": title,
                "contents": contents,
                "reporter": reporter_name,
                "sources": "Berita Pemerintah Daerah Gorontalo",
                "links": url,
                "impact": "",
                "sector": None,
                "sentiment": None
            }

            try:
                cursor.execute("""
                    INSERT INTO news_articles
                    (date, title, contents, reporter, sources, links, impact, sector, sentiment)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    row["date"], row["title"], row["contents"],
                    row["reporter"], row["sources"], row["links"],
                    row["impact"], row["sector"], row["sentiment"]
                ))
                conn.commit()
                session_titles.add(title)
                print(f"Saved     : {title} ({date_val})")
            except pymysql.IntegrityError:
                print(f"Duplicate : {title} ({date_val})")

        if stop_category:
            print("[INFO] Encountered article older than start_date, stopping category scraping.")
            break

        time.sleep(2)

    cursor.close()
    conn.close()