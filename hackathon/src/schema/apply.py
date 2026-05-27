"""
Apply schema.surql to SurrealDB.
Run: uv run python -m src.schema.apply
"""

import os
from pathlib import Path
from src.graph import db

SCHEMA_PATH = Path(__file__).parent / "schema.surql"


def apply():
    sql = SCHEMA_PATH.read_text()
    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
    print(f"Applying {len(statements)} schema statements to {os.environ['SURREALDB_NS']}/{os.environ['SURREALDB_DB']}...")
    for stmt in statements:
        try:
            db.query(stmt + ";")
        except Exception as e:
            print(f"  WARN: {e} — {stmt[:60]}")
    print("Schema applied.")


if __name__ == "__main__":
    apply()
