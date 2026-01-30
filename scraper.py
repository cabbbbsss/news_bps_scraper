import subprocess
import sys
import csv, os, time
from datetime import datetime, timedelta
from urllib.parse import urlparse
import pymysql
import subprocess

# Scrapers
from scraper_gopost import fetch_articles as fetch_gopost
from scraper_gopos import fetch_articles as fetch_gopos
from scraper_gorontaloprov import fetch_articles as fetch_gorontaloprov
from scraper_antara import fetch_articles as fetch_antara
from scraper_rakyatgorontalo import fetch_articles as fetch_rakyatgorontalo
from scraper_habari import fetch_articles as fetch_habari
from scraper_gosulut import fetch_articles as fetch_gosulut
from scraper_coolturnesia import fetch_articles as fetch_coolturnesia



# === MAIN VARS ===
CATEGORY_FILE = "category.txt"
RUNTIME_FILE = "runtime.txt"
SKIP_RUNTIME = True  # True = skip waiting for runtime.txt, False = use schedule

# Date range
# END_DATE = datetime.strptime("2025-12-31", "%Y-%m-%d").date()
# START_DATE = datetime.strptime("2024-01-01", "%Y-%m-%d").date()

END_DATE = datetime.now().date()
START_DATE = END_DATE - timedelta(days=5)

# MySQL database configuration
db_config = {
    "host": "10.75.0.14",
    "user": "news",
    "password": "P4ssw0rd!",
    "database": "news_database"
}

# === FUNCTIONS ===
def ensure_database_and_table(db_config):
    conn = pymysql.connect(
        host=db_config["host"],
        user=db_config["user"],
        password=db_config["password"]
    )
    cursor = conn.cursor()
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{db_config['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cursor.close()
    conn.close()

    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS news_articles (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            date DATE,
            title TEXT,
            contents LONGTEXT,
            reporter VARCHAR(255),
            sources VARCHAR(255),
            links TEXT,
            impact TEXT,
            sector VARCHAR(255),
            sentiment VARCHAR(50),
            UNIQUE KEY unique_title (title(255))
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """
    )

    # Add BPS classification columns if they don't exist
    try:
        cursor.execute("""
            ALTER TABLE news_articles
            ADD COLUMN kategori_bps VARCHAR(10) DEFAULT NULL,
            ADD COLUMN kategori_bps_detail TEXT DEFAULT NULL
        """)
        print("✅ BPS columns (kategori_bps, kategori_bps_detail) added to news_articles table")
    except pymysql.err.OperationalError as e:
        if "Duplicate column name" in str(e):
            print("ℹ️ BPS columns already exist in news_articles table")
        else:
            print(f"⚠️ Could not add BPS columns: {e}")

    cursor.close()
    conn.close()


def read_category_urls(file_path):
    if not os.path.exists(file_path):
        print(f"❌ Category file not found: {file_path}")
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def clean_domain(domain):
    for suffix in [".co.id", ".com", ".id"]:
        if domain.endswith(suffix):
            domain = domain[:-len(suffix)]
    return domain.replace(".", "_")


def read_runtime_file():
    """Read times from runtime.txt and return list of datetime.time objects"""
    if not os.path.exists(RUNTIME_FILE):
        print(f"⚠️ {RUNTIME_FILE} not found")
        return []

    times = []
    with open(RUNTIME_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                dt = datetime.strptime(line, "%I:%M%p")  # e.g., 12:00pm
                times.append(dt.time())
            except ValueError:
                print(f"⚠️ Invalid time format in {RUNTIME_FILE}: {line}")
    return times


def run_scraper_cycle():
    print(f"🚀 Starting multi-source news scraper at {datetime.now().strftime('%Y-%m-%d %I:%M%p')}")
    ensure_database_and_table(db_config)

    category_urls = read_category_urls(CATEGORY_FILE)
    if not category_urls:
        print("❌ No categories to process.")
        return

    article_id_counters = {}

    for url in category_urls:
        print(f"\n📂 Processing category: {url}")
        domain = urlparse(url).netloc.lower()
        clean_name = clean_domain(domain)

        if clean_name not in article_id_counters:
            article_id_counters[clean_name] = 1

        last_id = article_id_counters[clean_name]

        if "antaranews" in domain:
            last_id = fetch_antara(category_url=url, start_date=START_DATE, db_config=db_config, end_date=END_DATE)
        elif "gorontalopost" in domain:
            last_id = fetch_gopost(category_url=url, start_date=START_DATE, db_config=db_config, end_date=END_DATE)
        elif "gopos" in domain:
            last_id = fetch_gopos(category_url=url, start_date=START_DATE, end_date=END_DATE, db_config=db_config)
        elif "gorontaloprov" in domain:
            last_id = fetch_gorontaloprov(category_url=url, start_date=START_DATE, end_date=END_DATE, db_config=db_config, max_pages=1000)
        elif "rakyatgorontalo" in domain:
            last_id = fetch_rakyatgorontalo(category_url=url, start_date=START_DATE, end_date=END_DATE, db_config=db_config, max_pages=1000)
        elif "habari" in domain:
            last_id = fetch_habari(category_url=url, start_date=START_DATE, end_date=END_DATE, db_config=db_config)
        elif "gosulut" in domain:
            last_id = fetch_gosulut(category_url=url, start_date=START_DATE, end_date=END_DATE, db_config=db_config)
        elif "coolturnesia" in domain:
            last_id = fetch_coolturnesia(category_url=url, start_date=START_DATE, end_date=END_DATE, db_config=db_config)
        else:
            print(f"⚠️ Unknown domain, skipping: {url}")
            continue

        article_id_counters[clean_name] = last_id

    print("✅ Scraping cycle completed.")

    # --- Run other Python scripts sequentially ---
    try:
        print("➡️ Running Duplicate Clean-Up")
        subprocess.run([sys.executable, "clean_dup.py"], check=True)
        # print("➡️ Running Classifier")
	# subprocess.run([sys.executable, "classifier_ollama_v4.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running classifier scripts: {e}")


# === SERVICE LOOP ===
if __name__ == "__main__":
    print("🛎️ News scraper service started.")

    if SKIP_RUNTIME:
        print("⚡ SKIP_RUNTIME is True. Running scraper immediately without schedule.")
        run_scraper_cycle()
        print("⚡ Exiting after immediate run due to SKIP_RUNTIME=True.")
        exit(0)

    # Initialize schedule once
    scheduled_times = read_runtime_file()
    if not scheduled_times:
        print("❌ No valid scheduled times. Exiting.")
        exit(1)

    next_run_times = []
    now = datetime.now()
    for t in scheduled_times:
        scheduled_dt = datetime.combine(now.date(), t)
        if scheduled_dt <= now:
            scheduled_dt += timedelta(days=1)
        next_run_times.append(scheduled_dt)

    while True:
        now = datetime.now()

        # 🔄 Re-read runtime.txt for updates
        scheduled_times = read_runtime_file()
        if scheduled_times:
            # Sync with existing next_run_times
            updated_next_run_times = []
            for t in scheduled_times:
                # if already in next_run_times, keep that one
                match = [r for r in next_run_times if r.time() == t]
                if match:
                    updated_next_run_times.append(match[0])
                else:
                    scheduled_dt = datetime.combine(now.date(), t)
                    if scheduled_dt <= now:
                        scheduled_dt += timedelta(days=1)
                    updated_next_run_times.append(scheduled_dt)
            next_run_times = updated_next_run_times

        # Nearest run
        nearest_next_run = min(next_run_times)

        # Countdown
        remaining = nearest_next_run - now
        hrs, rem = divmod(remaining.seconds, 3600)
        mins, secs = divmod(rem, 60)
        print(f"⏳ Next run at {nearest_next_run.strftime('%I:%M%p')} "
              f"(in {hrs:02d}:{mins:02d}:{secs:02d})")

        # Run check
        for i, next_run in enumerate(next_run_times):
            if now >= next_run:
                print(f"\n⏰ Scheduled time reached: {next_run.strftime('%I:%M%p')}")
                run_scraper_cycle()
                next_run_times[i] = next_run + timedelta(days=1)  # push to tomorrow

        time.sleep(15)  # update countdown every 15 sec
