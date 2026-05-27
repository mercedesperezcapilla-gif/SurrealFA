"""
Tavily web search connector — finds supply chain relationships and news events
from the live web that structured databases (Wikidata, yfinance) miss.
"""

import os
from tavily import TavilyClient

_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    return _client


def search_supply_chain(company_name: str) -> list[dict]:
    """
    Search the web for a company's known suppliers and customers.
    Returns a list of {url, title, content} dicts with relevant snippets.
    """
    client = _get_client()
    query = f"{company_name} major suppliers customers supply chain relationships"
    result = client.search(query, max_results=5, search_depth="basic")
    return [
        {"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("content", "")}
        for r in result.get("results", [])
    ]


def search_company_events(company_name: str, topic: str = "") -> list[dict]:
    """
    Search for recent events or shocks affecting a company or industry.
    Returns a list of {url, title, content} dicts.
    """
    client = _get_client()
    query = f"{company_name} {topic} supply disruption event shock 2024 2025" if topic else f"{company_name} major risk event supply disruption 2024 2025"
    result = client.search(query, max_results=5, search_depth="basic")
    return [
        {"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("content", "")}
        for r in result.get("results", [])
    ]


def search_shock_news(entity: str, shock_description: str) -> list[dict]:
    """
    Search for live news about a specific shock event and its impact.
    More targeted than search_company_events — uses advanced search depth.
    Returns a list of {url, title, content} dicts.
    """
    client = _get_client()
    query = f"{entity} {shock_description} impact supply chain 2025 2026"
    result = client.search(query, max_results=5, search_depth="advanced")
    return [
        {"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("content", "")}
        for r in result.get("results", [])
    ]
