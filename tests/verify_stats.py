
from src.database import DatabaseManager
import os

def test_export():
    db_path = "data/news_feed.db"
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    db = DatabaseManager(db_path)
    output_temp = "logs/test_statistics.txt"
    os.makedirs("logs", exist_ok=True)

    print(f"Exporting statistics to {output_temp}...")
    db.export_statistics(output_temp)

    if os.path.exists(output_temp):
        print(f"Export successful. Content of {output_temp}:")
        with open(output_temp, 'r', encoding='utf-8') as f:
            print(f.read())
    else:
        print("Export failed.")

if __name__ == "__main__":
    test_export()
