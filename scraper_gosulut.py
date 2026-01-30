import re
import time
import requests
import pymysql
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/138.0.0.0 Safari/537.36"
}

MAX_PAGES = 100


def get_soup(url):
    """Fetch HTML and return BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.HTTPError as e:
        if e.response and e.response.status_code == 404:
            print(f"⚠️ Page not found (404): {url}")
            return None
        print(f"❌ Failed {url}: {e}")
        return None
    except Exception as e:
        print(f"❌ Failed {url}: {e}")
        return None


def extract_date_from_meta(soup_art):
    """Extract date from meta tag article:published_time."""
    meta_date = soup_art.select_one('meta[property="article:published_time"]')
    if meta_date and meta_date.get("content"):
        try:
            dt = datetime.fromisoformat(meta_date["content"].split("T")[0])
            return dt.date()
        except Exception:
            pass
    return None


def extract_reporter(soup_art):
    """Extract reporter from author info."""
    meta_author = soup_art.select_one('meta[name="author"]')
    if meta_author and meta_author.get("content"):
        return meta_author["content"]

    author_link = soup_art.select_one('a[rel="author"]')
    if author_link:
        return author_link.get_text(strip=True)

    author_span = soup_art.select_one('.author a') or soup_art.select_one('.entry-author a')
    if author_span:
        return author_span.get_text(strip=True)

    return "Admin"


def scrape_article(url):
    """Scrape one article and return dict."""
    soup = get_soup(url)
    if not soup:
        return None

    try:
        title_tag = soup.select_one("h1.entry-title") or soup.select_one("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            return None

        date_val = extract_date_from_meta(soup)
        reporter = extract_reporter(soup)

        content_div = soup.select_one("div.entry-content") or soup.select_one("div.post-content")
        contents = ""

        if content_div:
            paragraphs = content_div.find_all("p")
            content_texts = []

            for p in paragraphs:
                text = p.get_text(strip=True)
                if text and len(text) > 20 and not text.startswith("GOSULUT.ID") and "Advertisement" not in text:
                    content_texts.append(text)

            contents = "\n".join(content_texts)

        if not contents:
            all_paragraphs = soup.select("article p, .entry-content p, .post-content p")
            content_texts = [
                p.get_text(strip=True)
                for p in all_paragraphs
                if p.get_text(strip=True) and len(p.get_text(strip=True)) > 20
            ]
            contents = "\n".join(content_texts[:10])

        return {
            "date": date_val.isoformat() if date_val else "",
            "title": title,
            "contents": contents,
            "reporter": reporter,
            "sources": "GOSULUT.ID",
            "links": url,
            "impact": "",
            "sector": None,
            "sentiment": None
        }

    except Exception as e:
        print(f"❌ Failed to parse article {url}: {e}")
        return None


def fetch_articles(category_url, start_date, end_date, db_config=None, max_pages=MAX_PAGES):
    """Scrape articles from GOSULUT.ID category pages."""

    conn = None
    cursor = None

    if db_config:
        try:
            conn = pymysql.connect(**db_config)
            cursor = conn.cursor()
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return

    existing_links = set()
    existing_titles = set()

    if cursor:
        try:
            cursor.execute("SELECT links, title FROM news_articles")
            for link, title in cursor.fetchall():
                existing_links.add(link)
                existing_titles.add(title.strip().lower())
        except Exception as e:
            print(f"⚠️ Failed to fetch existing articles: {e}")

    seen_links = set(existing_links)
    seen_titles = set(existing_titles)

    for page in range(1, max_pages + 1):
        url = category_url if page == 1 else f"{category_url.rstrip('/')}/page/{page}/"
        print(f"Fetching page {page}: {url}")

        soup = get_soup(url)
        if not soup:
            break

        articles = soup.select("h2.entry-title a, h3.entry-title a, article h2 a")
        if not articles:
            print("No more articles found.")
            break

        last_article_date = None

        for a in articles:
            link = a.get("href")
            if not link:
                continue

            if not link.startswith("http"):
                link = f"https://gosulut.id{link}"

            if link in seen_links:
                print(f"Duplicate link: {link}")
                continue

            article = scrape_article(link)
            if not article:
                continue

            article_date = None
            if article["date"]:
                try:
                    article_date = datetime.fromisoformat(article["date"]).date()
                    last_article_date = article_date
                except Exception:
                    continue

            title_key = article["title"].strip().lower()
            if title_key in seen_titles:
                print(f"Duplicate title: {article['title']}")
                continue

            if article_date and (article_date < start_date or article_date > end_date):
                print(f"Skipped: {article['title']} ({article['date']}) — out of range")
                continue

            if cursor:
                try:
                    cursor.execute("""
                        INSERT IGNORE INTO news_articles
                        (date, title, contents, reporter, sources, links,
                         impact, sector, sentiment)
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
                    seen_links.add(link)
                    seen_titles.add(title_key)
                    print(f"Saved: {article['title']} ({article['date']})")
                except Exception as e:
                    print(f"Failed to save article {link}: {e}")
            else:
                print("=" * 90)
                print(f"TITLE   : {article['title']}")
                print(f"DATE    : {article['date']}")
                print(f"REPORTER: {article['reporter']}")
                print(f"URL     : {article['links']}")
                print(f"CONTENT : {article['contents'][:200]}...")
                print("=" * 90)

            time.sleep(1)

        if last_article_date and last_article_date < start_date:
            print(f"Stopping at page {page} because last article is older than start_date")
            break

    if cursor:
        cursor.close()
    if conn:
        conn.close()


if __name__ == "__main__":
    test_category_url = "https://gosulut.id/category/daerah/provinsi-gorontalo/"
    test_start_date = datetime(2025, 1, 1).date()
    test_end_date = datetime.now().date()

    print("Testing GOSULUT.ID scraper in preview mode...")
    fetch_articles(
        test_category_url,
        test_start_date,
        test_end_date,
        db_config=None,
        max_pages=2
    )
