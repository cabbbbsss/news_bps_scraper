import re
import time
import requests
import pymysql  # <-- ganti driver
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_PAGES = 1000


# ======================
# UTILS
# ======================
def get_soup(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"❌ Request failed: {url} -> {e}")
        return None


def extract_date(url):
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if m:
        return datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3))
        ).date()
    return None


def normalize_title(title):
    """
    Normalisasi TANPA mengubah huruf besar/kecil
    """
    title = re.sub(r"\s+", " ", title)
    title = title.strip()
    return title


def title_exists(cursor, title):
    cursor.execute(
        "SELECT 1 FROM news_articles WHERE title = %s LIMIT 1",
        (title,)
    )
    return cursor.fetchone() is not None


# ======================
# ARTICLE SCRAPER
# ======================
def scrape_article(url, date_obj):
    soup = get_soup(url)
    if not soup:
        return None

    # ---- TITLE ----
    title_tag = soup.find("h1", class_="jeg_post_title")
    if not title_tag:
        return None

    raw_title = title_tag.get_text(strip=True)
    title = normalize_title(raw_title)

    # ---- CONTENT ----
    paragraphs = soup.select("div.content-inner p")
    contents = "\n".join(
        p.get_text(strip=True)
        for p in paragraphs
        if p.get_text(strip=True)
    )

    if not contents:
        return None

    # ---- REPORTER ----
    reporter = "-"
    meta_author = soup.find("meta", attrs={"name": "author"})
    if meta_author and meta_author.get("content"):
        reporter = meta_author["content"]
    else:
        author_tag = soup.select_one(".jeg_meta_author a")
        if author_tag:
            reporter = author_tag.get_text(strip=True)

    return {
        "date": date_obj,
        "title": title,          # ✅ TIDAK LOWERCASE
        "contents": contents,
        "reporter": reporter,
        "sources": "GorontaloPost",
        "links": url,
        "impact": "",
        "sector": None,
        "sentiment": None
    }


# ======================
# MAIN SCRAPER
# ======================
def fetch_articles(category_url, start_date, end_date, db_config):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    for page in range(1, MAX_PAGES + 1):
        url = category_url if page == 1 else f"{category_url.rstrip('/')}/page/{page}/"
        print(f"\n🔎 Fetching: {url}")

        soup = get_soup(url)
        if not soup:
            break

        articles = soup.select("article.jeg_post")
        if not articles:
            print("ℹ️ No more articles")
            break

        for art in articles:
            a = art.select_one(".jeg_post_title a")
            if not a:
                continue

            link = a.get("href")
            date_obj = extract_date(link)
            if not date_obj:
                continue

            if date_obj < start_date:
                print("🛑 Stop pagination (older articles reached)")
                cursor.close()
                conn.close()
                return

            if date_obj > end_date:
                continue

            article = scrape_article(link, date_obj)
            if not article:
                continue

            # 🔴 DUPLICATE CHECK (CASE-SENSITIVE)
            if title_exists(cursor, article["title"]):
                print(f"⏩ Duplicate skipped: {article['title']}")
                continue

            cursor.execute("""
                INSERT INTO news_articles
                (date, title, contents, reporter, sources, links, impact, sector, sentiment)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                article["date"],
                article["title"],
                article["contents"],
                article["reporter"],
                article["sources"],
                article["links"],
                article["impact"],
                article["sector"],
                article["sentiment"]
            ))

            conn.commit()
            print(f"✅ Inserted: {article['title']}")
            time.sleep(1)

    cursor.close()
    conn.close()