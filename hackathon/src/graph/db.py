"""
SurrealDB client — blocking sync wrapper for Surreal FA.
Uses the blocking WebSocket client (not async) for simplicity.
"""

import json
import os
import ssl

import certifi
from dotenv import load_dotenv
from surrealdb import Surreal

load_dotenv()

# Patch macOS SSL cert verification for wss:// connections
_real_create = ssl.create_default_context
def _patched_create(*args, **kwargs):
    ctx = _real_create(*args, **kwargs)
    ctx.load_verify_locations(certifi.where())
    return ctx
ssl.create_default_context = _patched_create

DB_URL  = os.environ["SURREALDB_URL"]
DB_USER = os.environ.get("SURREALDB_USER", "root")
DB_PASS = os.environ.get("SURREALDB_PASS", "root")
DB_NS   = os.environ["SURREALDB_NS"]
DB_DB   = os.environ["SURREALDB_DB"]


def _clean_id(raw: str) -> str:
    """Clean a string for use as a SurrealDB record ID."""
    return (raw.lower()
            .replace(" ", "_").replace("-", "_").replace(".", "")
            .replace(",", "").replace("'", "").replace('"', "")
            .replace("(", "").replace(")", "").replace("/", "_")
            .replace("&", "and").replace("é", "e").replace("ü", "u"))


def query(sql: str, vars: dict | None = None) -> list:
    """Run a raw SurrealQL query and return results."""
    with Surreal(DB_URL) as db:
        db.signin({"username": DB_USER, "password": DB_PASS})
        db.use(DB_NS, DB_DB)
        return db.query(sql, vars or {})


def upsert_node(table: str, node_id: str, data: dict) -> str:
    """
    Create or update a node. Returns the clean record ID.
    e.g. upsert_node("company", "Tesla", {...}) → "company:tesla"
    """
    clean = _clean_id(node_id)
    data = {k: v for k, v in data.items() if v is not None}
    with Surreal(DB_URL) as db:
        db.signin({"username": DB_USER, "password": DB_PASS})
        db.use(DB_NS, DB_DB)
        db.query(f"UPSERT {table}:`{clean}` MERGE $data", {"data": data})
    return clean


def create_relationship(
    from_table: str,
    from_id: str,
    rel_type: str,
    to_table: str,
    to_id: str,
    properties: dict | None = None,
) -> None:
    """
    Create a RELATE edge between two nodes.
    e.g. create_relationship("company", "tesla", "operates_in", "industry", "electric_vehicles")
    """
    cf = _clean_id(from_id)
    ct = _clean_id(to_id)
    with Surreal(DB_URL) as db:
        db.signin({"username": DB_USER, "password": DB_PASS})
        db.use(DB_NS, DB_DB)
        # Deduplicate: skip if this exact edge already exists
        existing = db.query(
            f"SELECT id FROM {rel_type} WHERE in = {from_table}:`{cf}` AND out = {to_table}:`{ct}` LIMIT 1"
        )
        if existing and existing[0]:
            return
        if properties:
            props = {k: v for k, v in properties.items() if v is not None}
            db.query(
                f"RELATE {from_table}:`{cf}`->{rel_type}->{to_table}:`{ct}` CONTENT $data",
                {"data": props},
            )
        else:
            db.query(f"RELATE {from_table}:`{cf}`->{rel_type}->{to_table}:`{ct}`")


def find_node(table: str, name: str) -> dict | None:
    """Find a node by its name field."""
    result = query(f"SELECT * FROM {table} WHERE name = $name LIMIT 1", {"name": name})
    if result and isinstance(result, list) and result[0]:
        rows = result[0] if isinstance(result[0], list) else [result[0]]
        return rows[0] if rows else None
    return None


def graph_stats() -> dict:
    """Return counts of nodes and edges in the graph."""
    stats = {}
    for table in ["company", "industry", "technology", "commodity", "policy", "event", "region"]:
        result = query(f"SELECT count() AS n FROM {table} GROUP ALL")
        try:
            stats[table] = result[0]["n"] if result else 0
        except (IndexError, KeyError, TypeError):
            stats[table] = 0

    for rel in ["operates_in", "competes_with", "supplies_to", "uses_input",
                "complement_of", "uses_technology", "produced_in"]:
        result = query(f"SELECT count() AS n FROM {rel} GROUP ALL")
        try:
            stats[f"rel_{rel}"] = result[0]["n"] if result else 0
        except (IndexError, KeyError, TypeError):
            stats[f"rel_{rel}"] = 0

    return stats
