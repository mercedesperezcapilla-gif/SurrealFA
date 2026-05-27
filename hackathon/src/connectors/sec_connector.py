"""
SEC EDGAR connector — extracts supplier/customer mentions from 10-K filings.
No API key required. SEC requires a User-Agent header with contact email.

Uses:
  - EDGAR full-text search API to find supplier/customer mentions in 10-K filings
  - Returns text snippets the agent can parse for relationship extraction
"""

import os
import re
import requests

_BASE = "https://efts.sec.gov"
_DATA = "https://data.sec.gov"
_HEADERS = {
    "User-Agent": os.environ.get("SEC_USER_AGENT", "SurrealFA hackathon@surreal.com"),
    "Accept": "application/json",
}
_TIMEOUT = 15


def _clean(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_company_cik(company_name: str) -> str | None:
    """
    Look up a company's SEC CIK number by name using EDGAR full-text search.
    Returns a zero-padded 10-digit CIK string, or None if not found.
    """
    try:
        resp = requests.get(
            f"{_BASE}/LATEST/search-index",
            params={"q": company_name, "forms": "10-K", "dateRange": "custom",
                    "startdt": "2023-01-01"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        if hits:
            entity_id = hits[0].get("_source", {}).get("entity_id", "")
            if entity_id:
                return entity_id.lstrip("0").zfill(10)
    except Exception:
        pass
    return None


def search_10k_supply_chain(company_name: str, cik: str | None = None) -> list[str]:
    """
    Search SEC EDGAR for 10-K mentions of suppliers and customers for a company.
    Returns a list of text snippets (up to 5) containing relevant mentions.
    """
    snippets = []
    queries = [
        f'"{company_name}" "principal customers"',
        f'"{company_name}" "principal suppliers"',
        f'"{company_name}" "key suppliers" OR "key customers"',
    ]
    seen: set[str] = set()

    for q in queries:
        if len(snippets) >= 5:
            break
        try:
            params = {
                "q": q,
                "forms": "10-K",
                "dateRange": "custom",
                "startdt": "2023-01-01",
            }
            if cik:
                params["entity"] = cik
            resp = requests.get(
                f"{_BASE}/LATEST/search-index",
                params=params,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            for hit in resp.json().get("hits", {}).get("hits", []):
                highlights = hit.get("highlight", {}).get("file_contents", [])
                for hl in highlights[:2]:
                    clean = _clean(hl)
                    if clean and clean not in seen:
                        seen.add(clean)
                        snippets.append(clean)
                if len(snippets) >= 5:
                    break
        except Exception:
            continue

    return snippets


def get_sec_supply_chain(company_name: str) -> dict:
    """
    High-level function: look up CIK then search 10-K filings.
    Returns {"company": name, "cik": cik, "snippets": [...]}
    """
    cik = get_company_cik(company_name)
    snippets = search_10k_supply_chain(company_name, cik)
    return {
        "company": company_name,
        "cik": cik,
        "snippets": snippets,
    }
