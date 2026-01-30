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
    """Fetch HTML and return BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"[ERROR] {url} -> {e}")
        return None


def fetch_articles(category_url, start_date, end_date, db_config=None, max_pages=5):
    """Scrape category pages and optionally save to DB."""
    def extract_title(soup_art):
        h1 = soup_art.select_one("h1.entry-title strong")
        return h1.get_text(strip=True) if h1 else None

    def extract_link(soup_art):
        canonical = soup_art.select_one('link[rel="canonical"]')
        return canonical.get("href") if canonical else None

    def extract_date(soup_art):
        meta_date = soup_art.select_one('meta[property="article:modified_time"]')
        if meta_date and meta_date.get("content"):
            return datetime.fromisoformat(meta_date["content"].split("T")[0]).date()
        return None

    def extract_reporter(soup_art):
        meta_author = soup_art.select_one('meta[name="author"]')
        return meta_author.get("content") if meta_author else "-"

    def extract_content(soup_art):
        content_div = soup_art.select_one("div.entry-content.entry-content-single.clearfix")
        if not content_div:
            return None
        paragraphs = content_div.find_all("p")
        texts = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
        return "\n".join(texts)

    # Database connection if provided
    conn = None
    if db_config:
        conn = pymysql.connect(**db_config)

    seen_links = set()  # In-memory deduplication for current run

    for page in range(1, max_pages + 1):
        url_page = category_url if page == 1 else f"{category_url}page/{page}/"
        print(f"[INFO] Fetching page {page}: {url_page}")
        soup = get_soup(url_page)
        if not soup:
            break

        links = soup.select("article h2 a")
        if not links:
            print("[INFO] No more articles, stopping.")
            break

        stop_fetching = False
        for a in links:
            article_url = a.get("href")
            if not article_url or article_url in seen_links:
                continue
            seen_links.add(article_url)

            soup_art = get_soup(article_url)
            if not soup_art:
                continue

            title = extract_title(soup_art)
            link = extract_link(soup_art)
            date_val = extract_date(soup_art)
            reporter = extract_reporter(soup_art)
            contents = extract_content(soup_art)

            if not (title and link and date_val and contents):
                continue

            if date_val < start_date:
                print(f"Skipped: {title} ({date_val}) — older than start_date")
                stop_fetching = True
                continue

            if start_date <= date_val <= end_date:
                row = {
                    "date": date_val.isoformat(),
                    "title": title,
                    "contents": contents,
                    "reporter": reporter,
                    "sources": "RakyatGorontalo.com",
                    "links": link,
                    "impact": "",
                    "sector": None,
                    "sentiment": None
                }

                if conn:
                    try:
                        cursor = conn.cursor()

                        # DB Pre-check for duplicates
                        cursor.execute("SELECT COUNT(*) FROM news_articles WHERE links = %s", (row["links"],))
                        exists = cursor.fetchone()[0] > 0
                        if exists:
                            print(f"Duplicate found in DB: {title}")
                            cursor.close()
                            continue

                        # Insert new article
                        cursor.execute('''
                            INSERT INTO news_articles (date, title, contents, reporter, sources, links, impact, sector, sentiment)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (
                            row["date"], row["title"], row["contents"], row["reporter"],
                            row["sources"], row["links"], row["impact"], row["sector"], row["sentiment"]
                        ))
                        conn.commit()
                        cursor.close()
                        print(f"Saved: {title}")
                    except pymysql.IntegrityError:
                        print(f"Duplicate (via UNIQUE constraint): {title} ({date_val})")
                else:
                    print("=" * 90)
                    print(f"DATE     : {row['date']}")
                    print(f"TITLE    : {row['title']}")
                    print(f"LINK     : {row['links']}")
                    print(f"REPORTER : {row['reporter']}")
                    print(f"CONTENT  : {row['contents']}")
                    print("=" * 90)

            else:
                print(f"Skipped: {title} ({date_val}) — after end_date")

        if stop_fetching:
            print("[INFO] Older articles found, stopping further pages.")
            break

        time.sleep(2)

    if conn:
        conn.close()