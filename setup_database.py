import psycopg2
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DB_CONFIG
from feeder.schema import get_full_schema_ddl


def setup_database(use_partition: bool = True):
    print("KOMPAS.COM DATA WAREHOUSE - DATABASE SETUP")

    ddl = get_full_schema_ddl(use_partition=use_partition)

    print(f"\nConnecting to: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Execute DDL statements one by one
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    success = 0
    errors = 0

    for stmt in statements:
        try:
            cur.execute(stmt + ";")
            conn.commit()
            success += 1
        except Exception as e:
            error_msg = str(e).strip()
            if "already exists" in error_msg:
                success += 1  # Not really an error
            else:
                print(f"  [WARN] {error_msg[:100]}")
                errors += 1
            conn.rollback()

    print(f"\n  Executed {success} statements successfully")
    if errors:
        print(f"  {errors} warnings/errors (non-critical)")

    # Verify tables exist
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"\n  Tables in database:")
    for t in tables:
        print(f"    - {t}")

    # Check extensions
    cur.execute("SELECT extname FROM pg_extension")
    extensions = [row[0] for row in cur.fetchall()]
    print(f"\n  Extensions enabled: {', '.join(extensions)}")

    conn.close()
    print("\nDATABASE SETUP COMPLETE")


if __name__ == "__main__":
    use_part = "--no-partition" not in sys.argv
    setup_database(use_partition=use_part)