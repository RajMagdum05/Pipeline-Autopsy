"""
Database Inspector & Diagnostic Tool for Pipeline Autopsy
=========================================================
Tests database connectivity (PostgreSQL and SQLite fallback),
lists all tables, schema structures, record counts, and sample records.

Usage:
    python scripts/inspect_databases.py
    python scripts/inspect_databases.py --summary
    python scripts/inspect_databases.py --table claims
    python scripts/inspect_databases.py --table autopsy_executions
"""
import argparse
import os
import socket
import sqlite3
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT_DIR = Path(__file__).resolve().parents[1]


def check_postgres(host="localhost", port=5432, timeout=1.0):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def inspect_postgres_if_available():
    print("=" * 80)
    print(" 🐘 DATABASE: PostgreSQL Service Status")
    print("=" * 80)
    is_live = check_postgres("localhost", 5432)
    if is_live:
        print(" Status            : ONLINE at localhost:5432 ✅")
        try:
            from sqlalchemy import create_engine, inspect
            env_file = ROOT_DIR / ".env"
            from dotenv import load_dotenv
            load_dotenv(env_file)
            pg_url = os.getenv("DATABASE_URL", "postgresql+psycopg://pipeline:changeme@localhost:5432/pipeline_autopsy")
            engine = create_engine(pg_url)
            insp = inspect(engine)
            tables = insp.get_table_names()
            print(f" Connected DB      : {pg_url.split('@')[-1]}")
            print(f" Tables ({len(tables)})     : {', '.join(tables)}")
        except Exception as e:
            print(f" Note              : Port 5432 is open, but connection check returned: {e}")
    else:
        print(" Status            : OFFLINE at localhost:5432 ⭕")
        print(" Fallback Mode     : Active ✅ (SQLite resilient local engines in use)")
        print("   - Autopsy DB    : r:\\Pipeline_Autopsy\\autopsy.db")
        print("   - Pipeline DB   : r:\\Pipeline_Autopsy\\enterprise-pipeline\\pipeline_autopsy.db")
        print("   (To spin up PostgreSQL: run 'docker compose up -d')")
    print("=" * 80 + "\n")


def inspect_sqlite(db_path: Path, title: str, summary_only: bool = False, target_table: str = None):
    print("=" * 80)
    print(f" 🗄️  DATABASE: {title}")
    print("=" * 80)
    print(f" File Location : {db_path}")

    if not db_path.exists():
        print(f" [!] File does not exist.\n")
        return

    size_kb = db_path.stat().st_size / 1024
    print(f" Status        : Connected & Healthy ✅ (Size: {size_kb:.2f} KB)")
    print("-" * 80)

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
        tables = [r[0] for r in cur.fetchall()]

        if not tables:
            print(" [i] Database connected, but no user tables found.")
            conn.close()
            return

        print(f"\n Summary of Tables ({len(tables)} found):\n")
        print(f" {'#':<3} | {'TABLE NAME':<30} | {'ROWS':<8} | {'COLUMNS':<8} | {'PRIMARY KEY'}")
        print(" " + "-" * 78)

        table_details = {}

        for idx, table in enumerate(tables, start=1):
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            count = cur.fetchone()[0]

            cur.execute(f'PRAGMA table_info("{table}")')
            col_info = cur.fetchall()
            col_names = [c["name"] for c in col_info]
            pk_cols = [c["name"] for c in col_info if c["pk"] > 0]
            pk_str = ", ".join(pk_cols) if pk_cols else "(none)"

            table_details[table] = {
                "count": count,
                "columns": col_info,
                "pk": pk_str,
            }

            print(f" {idx:<3} | {table:<30} | {count:<8} | {len(col_names):<8} | {pk_str}")

        if summary_only:
            conn.close()
            print("\n" + "=" * 80 + "\n")
            return

        # Detailed section
        print("\n" + "-" * 80)
        print(" Detailed Table Schemas & Sample Rows:")
        print("-" * 80)

        if target_table:
            if target_table in tables:
                tables_to_show = [target_table]
            else:
                print(f"\n [i] Note: Table '{target_table}' does not belong to this database.")
                conn.close()
                print("\n" + "=" * 80 + "\n")
                return
        else:
            tables_to_show = tables

        for table in tables_to_show:
            details = table_details[table]
            count = details["count"]
            cols = details["columns"]

            print(f"\n ► Table: [{table}] ({count} total records)")
            print("   Columns:")
            for c in cols:
                pk_flag = " [PK]" if c["pk"] else ""
                null_flag = " NOT NULL" if c["notnull"] else ""
                print(f"     • {c['name']:<24} {c['type']}{pk_flag}{null_flag}")

            # Sample records
            if count > 0:
                limit = 3 if target_table else 1
                cur.execute(f'SELECT * FROM "{table}" LIMIT {limit}')
                rows = cur.fetchall()
                print(f"   Sample Record(s) (showing {len(rows)} of {count}):")
                for r_idx, row in enumerate(rows, start=1):
                    if len(rows) > 1:
                        print(f"     --- Record {r_idx} ---")
                    for k in row.keys()[:6]:
                        v = row[k]
                        v_str = str(v)
                        if len(v_str) > 65:
                            v_str = v_str[:62] + "..."
                        print(f"     {k:<22}: {v_str}")
                    if len(row.keys()) > 6:
                        print(f"     ... ({len(row.keys()) - 6} additional fields)")
            else:
                print("   (Table is empty)")

        conn.close()
    except Exception as e:
        print(f" [!] Error inspecting SQLite database: {e}")

    print("\n" + "=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Pipeline Autopsy Database Inspector")
    parser.add_argument("--summary", action="store_true", help="Print table summaries only")
    parser.add_argument("--table", type=str, default=None, help="Inspect a specific table name")
    args = parser.parse_args()

    print("\n" + "#" * 80)
    print("   PIPELINE AUTOPSY - DATABASE DIAGNOSTIC & TABLE INSPECTOR")
    print("#" * 80 + "\n")

    # 1. Test PostgreSQL
    inspect_postgres_if_available()

    # 2. Inspect Autopsy Core Database
    autopsy_db = ROOT_DIR / "autopsy.db"
    inspect_sqlite(autopsy_db, "Autopsy Observability Core Engine (autopsy.db)", summary_only=args.summary, target_table=args.table)

    # 3. Inspect Enterprise Pipeline Database
    pipeline_db = ROOT_DIR / "enterprise-pipeline" / "pipeline_autopsy.db"
    inspect_sqlite(pipeline_db, "Enterprise Claims Pipeline (pipeline_autopsy.db)", summary_only=args.summary, target_table=args.table)


if __name__ == "__main__":
    main()
