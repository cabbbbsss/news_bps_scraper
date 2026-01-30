import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import time
import pymysql  # <-- ganti driver

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
}
MAX_PAGES = 1000


# ----------------------
# UTILS
# ----------------------
def get_soup(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Page not found (404): {url}")
            return None
        print(f"Failed {url}: {e}")
        return None
    except Exception as e:
        #print(f"? Failed {url}: {e}")
        return None


def extract_date_from_url(url):
    match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def parse_indonesian_date(raw_date):
    translations = {
        "Januari": "January", "Februari": "February", "Maret": "March",
        "April": "April", "Mei": "May", "Juni": "June",
        "Juli": "July", "Agustus": "August", "September": "September",
        "Oktober": "October", "November": "November", "Desember": "December",
        "Senin": "Monday", "Selasa": "Tuesday", "Rabu": "Wednesday",
        "Kamis": "Thursday", "Jumat": "Friday", "Sabtu": "Saturday", "Minggu": "Sunday"
    }
    for indo, eng in translations.items():
        raw_date = raw_date.replace(indo, eng)
    try:
        dt = datetime.strptime(raw_date.split(" WIB")[0], "%A, %d %B %Y %H:%M")
        return dt.date()
    except ValueError:
        return None


# ----------------------
# MYSQL SAVE
# ----------------------
def save_article_mysql(article, db_config):
    """Insert article into MySQL; skip if duplicate based on title or link."""
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    try:
        # Check for existing article
        cursor.execute(
            "SELECT id FROM news_articles WHERE title=%s OR links=%s",
            (article["title"], article["links"])
        )
        result = cursor.fetchone()
        if result:
            print(f"Duplicate : {article['title']} ({article['date']})")
            return False

        # Insert new article
        sql = """
            INSERT INTO news_articles
            (date, title, contents, reporter, sources, links, impact)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (
            article["date"],
            article["title"],
            article["contents"],
            article["reporter"],
            article["sources"],
            article["links"],
            article["impact"]
        ))
        conn.commit()
        print(f"Saved     : {article['title']} ({article['date']})")
        return True

    except Exception as e:
        print(f"Failed to save {article['title']}: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


# ----------------------
# SCRAPER
# ----------------------
def fetch_articles(category_url, start_date, end_date, db_config, start_id=1):
    """
    Scrape articles within date range from Antara Gorontalo, save to MySQL.
    Stops fetching new pages if the last article on the current page is out of range.
    """
    id_counter = start_id

    for page in range(1, MAX_PAGES + 1):
        # Correct pagination: page 1 = base URL, page 2+ = /2, /3, ...
        url = category_url if page == 1 else f"{category_url.rstrip('/')}/{page}"
        print(f"Fetching list page: {url}")
        soup = get_soup(url)
        if not soup:
            print("No more pages, stopping scraper.")
            break

        # Find article links
        articles = soup.select("h3 a")
        if not articles:
            print("No more articles found on this page.")
            break

        article_dates = []

        for a in articles:
            link = a.get("href")
            if not link:
                continue

            article = scrape_article(link, id_counter)
            if not article:
                continue

            # Parse article date
            try:
                article_date = datetime.strptime(article["date"], "%Y-%m-%d").date()
            except Exception:
                article_date = None

            if article_date:
                article_dates.append(article_date)
                # Check if article is within range
                if start_date <= article_date <= end_date:
                    saved = save_article_mysql(article, db_config)
                    if saved:
                        id_counter += 1
                else:
                    print(f"Skipped   : {article['title']} [{article['date']}]")
            else:
                print(f"Skipped (no date) : {article['title']}")

            time.sleep(1)  # polite delay between articles

        # After finishing the page, check the last article date
        if article_dates and min(article_dates) < start_date:
            print(f"Last article is older than {start_date}. Stopping scraper.")
            break

    print(f"Scraping finished. Last ID used: {id_counter}")
    return id_counter


def scrape_article(url, id_counter):
    """Scrape one article and return standardized dict."""
    soup = get_soup(url)
    if not soup:
        return None

    try:
        # --- Updated: get title from <h1 class="post-title"> ---
        title_tag = soup.find("h1", class_="post-title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # --- Content ---
        content_div = soup.find("div", class_="post-content")
        paragraphs = content_div.find_all("p") if content_div else []
        contents = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

        # --- Reporter ---
        reporter = ""
        footer = soup.find("div", class_="tags-wrapper")
        if footer and "Pewarta:" in footer.text:
            reporter_line = footer.find(string=lambda t: "Pewarta:" in t)
            if reporter_line:
                reporter = reporter_line.replace("Pewarta:", "").strip()

        # --- Date ---
        date_str = ""
        date_span = soup.find("span", class_="article-date")
        if date_span:
            raw_date = date_span.get_text(strip=True)
            parsed = parse_indonesian_date(raw_date)
            if parsed:
                date_str = parsed.strftime("%Y-%m-%d")

        if not date_str:
            date_str = extract_date_from_url(url)

        return {
            "id": id_counter,
            "date": date_str,
            "title": title,
            "contents": contents,
            "reporter": reporter,
            "sources": "Antara News",
            "links": url,
            "impact": ""  # leave empty for Gemini
        }
    except Exception as e:
        print(f"Failed to parse article {url}: {e}")
        return None