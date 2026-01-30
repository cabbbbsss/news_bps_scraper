import re
import time
import requests
import pymysql
from datetime import datetime
from bs4 import BeautifulSoup

# ===============================
# CONFIG
# ===============================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}
MAX_PAGES = 100

# ===============================
# UTILS
# ===============================
def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"❌ Request error: {url} -> {e}")
        return None


def normalize_title(title):
    return re.sub(r"\s+", " ", title).strip()


def title_exists(cursor, title):
    cursor.execute(
        "SELECT 1 FROM news_articles WHERE title=%s LIMIT 1",
        (title,)
    )
    return cursor.fetchone() is not None


# ===============================
# SCRAPE DETAIL
# ===============================
def scrape_detail(url):
    soup = get_soup(url)
    if not soup:
        return None

    # Judul
    h1 = soup.select_one("h1.entry-title")
    if not h1:
        return None
    title = normalize_title(h1.get_text(strip=True))

    # Tanggal
    time_tag = soup.select_one("time.entry-date[datetime]")
    date_obj = None
    if time_tag:
        date_obj = datetime.fromisoformat(
            time_tag["datetime"]
        ).date()

    # Reporter
    reporter = "-"
    author = soup.select_one(".entry-author span[itemprop='name']")
    if author:
        reporter = author.get_text(strip=True)

    # Konten
    content_div = soup.select_one("div.entry-content-single")
    if not content_div:
        return None

    # Hapus iklan
    for ads in content_div.select(
        ".majalahpro-core-banner-insidecontent, "
        ".majalahpro-core-banner-aftercontent"
    ):
        ads.decompose()

    paragraphs = content_div.select("p")
    contents = "\n".join(
        p.get_text(" ", strip=True)
        for p in paragraphs
        if p.get_text(strip=True)
    )

    if not contents:
        return None

    return {
        "date": date_obj,
        "title": title,
        "contents": contents,
        "reporter": reporter,
        "sources": "Habari.id",
        "links": url,
        "impact": "",
        "sector": None,
        "sentiment": None,
    }


# ===============================
# SCRAPE INDEX + INSERT DB
# ===============================
def fetch_articles(category_url, start_date, end_date, db_config):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    for page in range(1, MAX_PAGES + 1):
        url = category_url if page == 1 else f"{category_url.rstrip('/')}/page/{page}/"
        print(f"\n🔎 Fetching index: {url}")

        soup = get_soup(url)
        if not soup:
            break

        articles = soup.select("main.site-main article.item-infinite")
        if not articles:
            print("ℹ️ Tidak ada artikel di halaman ini")
            break

        for art in articles:
            title_tag = art.select_one("h2.entry-title a")
            if not title_tag:
                continue

            link = title_tag["href"]
            title = normalize_title(title_tag.get_text(strip=True))

            # Tanggal dari index
            time_tag = art.select_one("time[datetime]")
            if not time_tag:
                continue

            date_obj = datetime.fromisoformat(
                time_tag["datetime"]
            ).date()

            # Filter tanggal
            if date_obj < start_date:
                print("🛑 Stop pagination (artikel lama tercapai)")
                cursor.close()
                conn.close()
                return

            if date_obj > end_date:
                continue

            if title_exists(cursor, title):
                print(f"⏩ Skip duplikat: {title}")
                continue

            # Scrape detail
            article = scrape_detail(link)
            if not article:
                print("⚠️ Gagal scrape detail:", link)
                continue

            # Insert DB
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
                article["sentiment"],
            ))

            conn.commit()
            print(f"✅ Inserted: {article['title']} ({article['date']})")
            time.sleep(1)

    cursor.close()
    conn.close()
