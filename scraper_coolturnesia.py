import re
import time
import requests
import mysql.connector
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    )
}

MAX_PAGES = 100

def get_soup(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"Failed {url}: {e}")
        return None

def parse_indonesian_date(date_str):
    """Parse Indonesian date format like 'Kamis, 08 Jan 2026' or '08 Jan 2026'"""
    # Full month names
    full_translations = {
        "Januari": "January", "Februari": "February", "Maret": "March",
        "April": "April", "Mei": "May", "Juni": "June",
        "Juli": "July", "Agustus": "August", "September": "September",
        "Oktober": "October", "November": "November", "Desember": "December"
    }

    # Short month names (3-letter abbreviations used by coolturnesia.com)
    short_translations = {
        "Jan": "January", "Feb": "February", "Mar": "March",
        "Apr": "April", "Mei": "May", "Jun": "June",
        "Jul": "July", "Ags": "August", "Sep": "September",
        "Okt": "October", "Nov": "November", "Des": "December"
    }

    # Clean the date string
    date_str = date_str.strip()

    # Handle format "Kamis, 08 Jan 2026" or "08 Jan 2026"
    # First try full month names
    for indo, eng in full_translations.items():
        date_str = date_str.replace(indo, eng)

    # Then try short month names (for coolturnesia.com)
    for indo, eng in short_translations.items():
        date_str = date_str.replace(indo, eng)

    try:
        # Try with day name: "Kamis, 08 January 2026"
        dt = datetime.strptime(date_str, "%A, %d %B %Y")
        return dt.date()
    except ValueError:
        try:
            # Try without day name: "08 January 2026"
            dt = datetime.strptime(date_str, "%d %B %Y")
            return dt.date()
        except ValueError:
            try:
                # Try format "08 Jan 2026" (short month name)
                dt = datetime.strptime(date_str, "%d %b %Y")
                return dt.date()
            except ValueError:
                try:
                    # Try with day name and short month: "Kamis, 08 Jan 2026"
                    dt = datetime.strptime(date_str, "%A, %d %b %Y")
                    return dt.date()
                except ValueError:
                    print(f"Could not parse date: {date_str}")
                    return None

def scrape_article(url):
    soup = get_soup(url)
    if not soup:
        return None

    try:
        # Get title from breadcrumb or page title
        title = ""
        breadcrumb_title = soup.select_one("h2.page-title")
        if breadcrumb_title:
            title = breadcrumb_title.get_text(strip=True)
        else:
            # Fallback to og:title meta tag
            og_title = soup.select_one("meta[property='og:title']")
            if og_title and og_title.get("content"):
                title = og_title["content"]

        # Get content from blog-details-text
        content_div = soup.select_one("div.blog-details-text")
        contents = ""
        if content_div:
            paragraphs = content_div.find_all("p")
            contents = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

        # Get reporter and date from post-author-area
        reporter = "Admin"
        date_str = ""

        author_area = soup.select_one("div.post-author-area ul.popular-tags")
        if author_area:
            links = author_area.find_all("a")
            if len(links) >= 3:
                # First link is reporter, last link is date
                reporter = links[0].get_text(strip=True) if links[0].get_text(strip=True) else "Admin"
                date_str = links[-1].get_text(strip=True)

        # Parse date
        parsed_date = None
        if date_str:
            parsed_date = parse_indonesian_date(date_str)

        return {
            "date": parsed_date.isoformat() if parsed_date else "",
            "title": title,
            "contents": contents,
            "reporter": reporter,
            "sources": "COOLTURNESIA.COM",
            "links": url,
            "impact": "",
            "sector": None,
            "sentiment": None
        }
    except Exception as e:
        print(f"Failed to parse article {url}: {e}")
        return None

def fetch_articles(category_url, start_date, end_date, db_config=None, max_pages=MAX_PAGES):
    conn = None
    cursor = None
    existing_links = set()
    existing_titles = set()

    if db_config:
        try:
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT links, title FROM news_articles")
            for link, title in cursor.fetchall():
                existing_links.add(link)
                existing_titles.add(title.strip().lower())
        except Exception as e:
            print(f"Failed to connect to DB or fetch existing articles: {e}")
            if conn: conn.close()
            conn = None
            cursor = None

    seen_links = set(existing_links)
    seen_titles = set(existing_titles)

    for page in range(1, max_pages + 1):
        # Build pagination URL
        if page == 1:
            url = category_url
        else:
            # Add pagination: /10, /20, /30, etc.
            pagination = (page - 1) * 10
            url = f"{category_url.rstrip('/')}/{pagination}"

        print(f"Fetching page {page}: {url}")

        soup = get_soup(url)
        if not soup:
            break

        # Find all articles on the page
        articles = soup.select("div.single-blog-post.d-flex.align-items-center.mb-50")
        if not articles:
            print("No more articles found.")
            break

        last_article_date = None

        for article in articles:
            # Get article link
            link_elem = article.select_one("a.post-title")
            if not link_elem:
                continue

            link = link_elem.get("href")
            if not link:
                continue

            if not link.startswith("http"):
                link = f"https://coolturnesia.com{link}"

            if link in seen_links:
                print(f"Duplicate link: {link}")
                continue

            # Get title from listing page
            title_elem = article.select_one("a.post-title")
            title = title_elem.get_text(strip=True) if title_elem else ""

            if title.strip().lower() in seen_titles:
                print(f"Duplicate title: {title}")
                continue

            # Get date from listing page
            date_str = ""
            day_elem = article.select_one("a.post-author")
            date_elem = article.select_one("a.post-tutorial")

            if day_elem and date_elem:
                day = day_elem.get_text(strip=True)
                date_part = date_elem.get_text(strip=True)
                date_str = f"{day}, {date_part}"

            # Scrape full article
            article_data = scrape_article(link)
            if not article_data:
                continue

            # Use date from detail page if available, otherwise from listing
            if not article_data["date"] and date_str:
                parsed_date = parse_indonesian_date(date_str)
                if parsed_date:
                    article_data["date"] = parsed_date.isoformat()

            article_date = None
            if article_data["date"]:
                try:
                    article_date = datetime.fromisoformat(article_data["date"]).date()
                    last_article_date = article_date
                except ValueError:
                    print(f"Could not parse date from article: {article_data['date']}")

            if article_date and (article_date < start_date or article_date > end_date):
                print(f"Skipped: {article_data['title']} ({article_data['date']}) — out of range")
                continue

            if conn and cursor:
                try:
                    cursor.execute("""
                        INSERT IGNORE INTO news_articles
                        (date, title, contents, reporter, sources, links, impact, sector, sentiment)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        article_data["date"], article_data["title"], article_data["contents"],
                        article_data["reporter"], article_data["sources"], article_data["links"],
                        article_data["impact"], article_data["sector"], article_data["sentiment"]
                    ))
                    conn.commit()
                    seen_links.add(link)
                    seen_titles.add(title.strip().lower())
                    print(f"Saved: {article_data['title']} ({article_data['date']})")
                except mysql.connector.IntegrityError:
                    print(f"Duplicate (via UNIQUE constraint): {article_data['title']} ({article_data['date']})")
                except Exception as e:
                    print(f"Failed to save article {link}: {e}")
            else:
                print("=" * 90)
                print(f"TITLE   : {article_data['title']}")
                print(f"DATE    : {article_data['date']}")
                print(f"REPORTER: {article_data['reporter']}")
                print(f"URL     : {article_data['links']}")
                print(f"CONTENT : {article_data['contents'][:200]}...")
                print("=" * 90)

            time.sleep(2)  # Polite delay

        if last_article_date and last_article_date < start_date:
            print(f"Stopping at page {page} because last article ({last_article_date}) is older than start_date ({start_date})")
            break

    if conn:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    from datetime import date, timedelta

    # Dummy DB config for testing purposes
    db_config = {
        "host": "localhost",
        "user": "root",
        "password": "P4ssw0rd!",
        "database": "news_database"
    }

    # Define date range for scraping
    end_date = date.today()
    start_date = end_date - timedelta(days=30)  # Scrape last 30 days

    # Test with the main category URL
    test_category_url = "https://coolturnesia.com/coolturnesia/berita/index/coolturpedia"
    print("Testing COOLTURNESIA.COM scraper in preview mode...")
    fetch_articles(test_category_url, start_date, end_date, db_config=None, max_pages=2)
