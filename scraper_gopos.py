import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import pymysql  # <-- ganti driver
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
}

MAX_PAGES = 1000

def get_soup(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            print(f"⚠️ Page not found (404): {url}")
            return None
        print(f"❌ Failed {url}: {e}")
        return None
    except Exception as e:
        print(f"❌ Failed {url}: {e}")
        return None

def extract_date_from_url(url):
    """Extract date from URL pattern /YYYY/MM/DD/"""
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if m:
        y, mth, d = map(int, m.groups())
        return datetime(y, mth, d).date()
    return None

def scrape_article(url):
    soup = get_soup(url)
    if not soup:
        return None

    try:
        title = soup.find("meta", property="og:title")["content"].strip()
        content_container = soup.select_one("div.content-inner")
        contents = ""
        if content_container:
            paragraphs = content_container.find_all("p")
            contents = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

        reporter = "-"
        reporter_tag = soup.select_one("span.author-name")
        if reporter_tag:
            reporter = reporter_tag.get_text(strip=True)

        date_str = ""
        published_raw = soup.find("meta", property="article:published_time")
        if published_raw:
            try:
                dt = datetime.fromisoformat(published_raw["content"].replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                date_str = published_raw["content"]

        return {
            "date": date_str,
            "title": title,
            "contents": contents,
            "reporter": reporter,
            "sources": "GoPOS.id",
            "links": url,
            "impact": ""
        }
    except Exception as e:
        print(f"❌ Failed to parse article {url}: {e}")
        return None

def fetch_articles(category_url, start_date, end_date, db_config):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    # Fetch existing links and titles to avoid duplicates
    cursor.execute("SELECT links, title FROM news_articles")
    existing_links = set()
    existing_titles = set()
    for link, title in cursor.fetchall():
        existing_links.add(link)
        existing_titles.add(title.strip().lower())

    # In-memory dedup sets
    seen_links = set(existing_links)
    seen_titles = set(existing_titles)

    for page in range(1, MAX_PAGES + 1):
        url = category_url if page == 1 else f"{category_url.rstrip('/')}/page/{page}/"
        print(f"Fetching page {page}: {url}")
        soup = get_soup(url)
        if not soup:
            break

        articles = soup.select('h3.jeg_post_title a')
        if not articles:
            print("No more articles found.")
            break

        last_article_date = None

        for a in articles:
            link = a.get("href")
            if not link:
                continue

            # Skip duplicates by link
            if link in seen_links:
                print(f"Duplicate link : {link}")
                continue

            # Scrape article only if not duplicate
            article = scrape_article(link)
            if not article:
                continue

            # Parse article date
            article_date = None
            if article["date"]:
                try:
                    article_date = datetime.fromisoformat(article["date"]).date()
                    last_article_date = article_date
                except Exception:
                    article_date = extract_date_from_url(link)
                    last_article_date = article_date

            # Skip duplicates by title
            title_key = article["title"].strip().lower()
            if title_key in seen_titles:
                print(f"Duplicate title: {article['title']}")
                continue

            # Date filter
            if article_date and (article_date < start_date or article_date > end_date):
                print(f"Skipped   : {article['title']} ({article['date']}) — out of range")
                continue

            # Save to DB
            try:
                cursor.execute("""
                    INSERT IGNORE INTO news_articles 
                    (date, title, contents, reporter, sources, links, impact) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    article["date"],
                    article["title"],
                    article["contents"],
                    article["reporter"],
                    article["sources"],
                    article["links"],
                    article["impact"]
                ))
                conn.commit()
                seen_links.add(link)
                seen_titles.add(title_key)
                print(f"Saved     : {article['title']} ({article['date']})")
            except Exception as e:
                print(f"Failed to save article {link}: {e}")

            time.sleep(1)

        # Stop fetching next page if last article date on this page is older than start_date
        if last_article_date and last_article_date < start_date:
            print(f"Stopping category at page {page} because last article ({last_article_date}) is older than start_date ({start_date})")
            break

    cursor.close()
    conn.close()