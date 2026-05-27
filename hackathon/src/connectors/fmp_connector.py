"""
Financial Modeling Prep (FMP) connector.
Uses the /stable API (current plan).

Note: /v4/stock_peers is a legacy endpoint no longer available on non-legacy plans.
The stable API provides company profile data with CIK, beta, market cap, sector, industry.

Set FMP_API_KEY in .env
"""

import os
import requests

_BASE  = "https://financialmodelingprep.com"
_TIMEOUT = 10


def _key() -> str:
    return os.environ.get("FMP_API_KEY", "")


def get_stock_peers(ticker: str) -> list[str]:
    """
    Peers endpoint is no longer available on the current FMP plan.
    Returns empty list — use search_supply_chain_web instead for competitor discovery.
    """
    return []


def get_company_profile(ticker: str) -> dict:
    """
    Return company profile from FMP /stable/profile.
    Includes market cap, beta, industry, sector, CIK, exchange.
    """
    try:
        resp = requests.get(
            f"{_BASE}/stable/profile",
            params={"symbol": ticker.upper(), "apikey": _key()},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            p = data[0]
            return {
                "name":        p.get("companyName"),
                "ticker":      p.get("symbol"),
                "sector":      p.get("sector"),
                "industry":    p.get("industry"),
                "exchange":    p.get("exchangeFullName"),
                "cik":         p.get("cik"),
                "country":     p.get("country"),
                "website":     p.get("website"),
                "market_cap":  p.get("marketCap"),
                "beta":        p.get("beta"),
            }
    except Exception:
        pass
    return {}
