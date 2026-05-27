"""
yfinance connector — fetches company data from Yahoo Finance.
Returns dicts compatible with GraphBuilder.add_company().
"""

import yfinance as yf


def get_company_info(ticker: str) -> dict | None:
    """
    Fetch company metadata for a ticker symbol.
    Returns a dict ready for GraphBuilder.add_company().
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info
        if not info or info.get("quoteType") not in ("EQUITY", "ETF"):
            return None
        return {
            "name":        info.get("longName") or info.get("shortName"),
            "ticker":      ticker.upper(),
            "description": info.get("longBusinessSummary"),
            "market_cap":  info.get("marketCap"),
            "revenue":     info.get("totalRevenue"),
            "employees":   info.get("fullTimeEmployees"),
            "hq_country":  info.get("country"),
            "hq_city":     info.get("city"),
            "website":     info.get("website"),
            "sector":      info.get("sector"),
            "industry":    info.get("industry"),
            "source":      "yfinance",
        }
    except Exception:
        return None


def get_company_by_name(name: str) -> dict | None:
    """
    Try to find a company by name via yfinance search.
    Falls back to None if not found.
    """
    try:
        search = yf.Search(name, max_results=3)
        quotes = search.quotes
        if not quotes:
            return None
        # Take the first EQUITY result
        for q in quotes:
            if q.get("quoteType") == "EQUITY":
                return get_company_info(q["symbol"])
        return get_company_info(quotes[0]["symbol"])
    except Exception:
        return None


def get_competitors(ticker: str) -> list[str]:
    """
    Return a list of competitor tickers for a given company.
    yfinance exposes recommendationKey and some peer data.
    """
    try:
        t = yf.Ticker(ticker)
        # yfinance doesn't have direct competitors, use sector peers heuristic
        info = t.info
        return []  # Wikidata handles relationships better
    except Exception:
        return []


def get_key_stats(ticker: str) -> dict | None:
    """Return key financial ratios useful for cost sensitivity analysis."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return {
            "gross_margin":     info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin":    info.get("profitMargins"),
            "cost_of_revenue":  info.get("costOfRevenue"),
            "revenue":          info.get("totalRevenue"),
        }
    except Exception:
        return None
