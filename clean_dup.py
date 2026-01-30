import pymysql
from pymysql import Error

# ----------------------
# Database configuration
# ----------------------
db_config = {
    "host": "10.75.0.14",
    "user": "news",
    "password": "P4ssw0rd!",
    "database": "news_database"
}

try:
    # Connect to the database
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    if conn.open:
        print("Connected to the database")

        # Step 0: Count total rows before
        cursor.execute("SELECT COUNT(*) FROM news_articles;")
        total_before = cursor.fetchone()[0]
        print(f"Total rows before cleanup: {total_before}")

        # Step 1: Find duplicate titles
        cursor.execute("""
            SELECT title, COUNT(*) as count
            FROM news_articles
            GROUP BY title
            HAVING COUNT(*) > 1;
        """)
        duplicates = cursor.fetchall()

        if duplicates:
            print(f"Found {len(duplicates)} duplicate titles:")
            for i, (title, count) in enumerate(duplicates, start=1):
                print(f"[{i}/{len(duplicates)}] '{title}' - {count} times")

            # Step 2: Delete duplicates, keep one row per title
            delete_query = """
                DELETE FROM news_articles
                WHERE id NOT IN (
                    SELECT * FROM (
                        SELECT MIN(id)
                        FROM news_articles
                        GROUP BY title
                    ) AS keep_ids
                );
            """
            cursor.execute(delete_query)
            conn.commit()
            print(f"Deleted {cursor.rowcount} duplicate rows, keeping one per title.")
        else:
            print("No duplicates found.")

        # Step 3: Count total rows after
        cursor.execute("SELECT COUNT(*) FROM news_articles;")
        total_after = cursor.fetchone()[0]
        print(f"Total rows after cleanup: {total_after}")

except Error as e:
    print("Error:", e)

finally:
    if cursor:
        cursor.close()
    if conn and conn.open:
        conn.close()
        print("Database connection closed.")