"""
LangChain tools for the build agent.
Wraps data connectors and GraphBuilder into @tool-callable functions.
"""

import json
from langchain_core.tools import tool

from src.connectors.yfinance_connector import get_company_info, get_company_by_name, get_key_stats
from src.connectors.wikidata_connector import (
    get_companies_in_industry,
    get_company_relationships,
    get_supply_chain,
    search_entity,
)
from src.connectors.tavily_connector import search_supply_chain, search_company_events
from src.connectors.fmp_connector import get_company_profile
from src.connectors.sec_connector import get_sec_supply_chain
from src.graph.builder import GraphBuilder
from src.graph import db as graph_db

_builder = GraphBuilder()


# ── Data source tools ──────────────────────────────────────────────────────────

@tool
def lookup_company_by_ticker(ticker: str) -> str:
    """Look up a company by stock ticker (e.g. TSMC, NVDA, AAPL).
    Returns name, description, market cap, sector, industry."""
    info = get_company_info(ticker)
    return json.dumps(info, indent=2, default=str) if info else f"No company found for ticker {ticker}"


@tool
def search_company_by_name(name: str) -> str:
    """Search for a company by name. Returns company info if found on Yahoo Finance."""
    info = get_company_by_name(name)
    return json.dumps(info, indent=2, default=str) if info else f"No company found for '{name}'"


@tool
def get_company_financials(ticker: str) -> str:
    """Get financial ratios for a company (margins, revenue). Useful for cost sensitivity."""
    stats = get_key_stats(ticker)
    return json.dumps(stats, indent=2, default=str) if stats else f"No financials for {ticker}"


@tool
def find_companies_in_industry_wikidata(industry_name: str) -> str:
    """Find companies in an industry via Wikidata structured knowledge.
    Returns companies with Wikidata IDs and tickers."""
    companies = get_companies_in_industry(industry_name)
    return json.dumps(companies[:20], indent=2) if companies else f"No companies found for '{industry_name}' on Wikidata"


@tool
def get_company_wikidata_relationships(wikidata_id: str) -> str:
    """Get relationships for a company from Wikidata (Q-ID e.g. 'Q478214').
    Returns parent companies, subsidiaries, products, industries."""
    rels = get_company_relationships(wikidata_id)
    return json.dumps(rels, indent=2) if rels else f"No relationships for {wikidata_id}"


@tool
def get_company_supply_chain_wikidata(wikidata_id: str) -> str:
    """Get what a company produces and what raw inputs it uses, from Wikidata."""
    chain = get_supply_chain(wikidata_id)
    return json.dumps(chain, indent=2) if any(chain.values()) else f"No supply chain data for {wikidata_id}"


@tool
def search_wikidata_entity(name: str) -> str:
    """Search Wikidata for an entity by name. Returns Q-IDs and descriptions.
    Use this to find Wikidata IDs for companies, technologies, commodities."""
    results = search_entity(name)
    return json.dumps(results, indent=2) if results else f"No Wikidata entities found for '{name}'"


# ── Additional data source tools ───────────────────────────────────────────────

@tool
def search_supply_chain_web(company_name: str) -> str:
    """Search the live web (via Tavily) for a company's known suppliers and customers.
    Use this when Wikidata supply chain data is empty — it finds relationships from
    news articles, industry reports, and company pages.
    Returns text snippets the LLM should parse to extract supplier/customer names."""
    results = search_supply_chain(company_name)
    if not results:
        return f"No web results found for '{company_name}' supply chain"
    return json.dumps(results, indent=2)


@tool
def search_industry_events_web(company_or_industry: str) -> str:
    """Search the live web (via Tavily) for recent supply disruptions, shocks, or
    geopolitical events affecting a company or industry. Use to discover event nodes."""
    results = search_company_events(company_or_industry)
    if not results:
        return f"No event results found for '{company_or_industry}'"
    return json.dumps(results, indent=2)


@tool
def get_company_profile_fmp(ticker: str) -> str:
    """Get enriched company profile from Financial Modeling Prep (FMP).
    Returns market cap, beta, sector, industry, CIK, exchange — supplements yfinance data.
    Use when yfinance lookup fails or for additional fields."""
    profile = get_company_profile(ticker)
    if not profile:
        return f"No FMP profile found for ticker {ticker}"
    return json.dumps(profile, indent=2)


@tool
def search_sec_filings(company_name: str) -> str:
    """Search SEC EDGAR 10-K filings for a company's disclosed suppliers and customers.
    Returns text snippets from official filings — the most credible source for
    supply chain relationships. Parse the snippets to extract company names."""
    result = get_sec_supply_chain(company_name)
    if not result.get("snippets"):
        return f"No SEC 10-K supply chain data found for '{company_name}'"
    return json.dumps(result, indent=2)


# ── Graph write tools ──────────────────────────────────────────────────────────

@tool
def add_company_to_graph(
    ticker: str,
    wikidata_id: str = "",
) -> str:
    """Add a company to the knowledge graph by ticker symbol.
    The company data is fetched from Yahoo Finance automatically.
    REQUIRES a valid ticker (e.g. TSLA, NVDA, TSM).
    If the ticker is invalid or not found, the company will NOT be added."""
    from src.connectors.yfinance_connector import get_company_info
    info = get_company_info(ticker)
    if not info:
        return f"REJECTED: ticker '{ticker}' not found on Yahoo Finance. Try a different ticker."
    if not info.get("market_cap") or info["market_cap"] <= 0:
        return f"REJECTED: '{ticker}' has no market cap data. Not a valid public company."

    if wikidata_id:
        info["wikidata_id"] = wikidata_id

    company_id = _builder.add_company(info)
    industry = info.get("industry")
    if industry:
        _builder.add_industry(industry, {"sector": info.get("sector")})
        _builder.link_company_to_industry(company_id, industry)

    return (f"Added company '{info['name']}' ({info['ticker']}) "
            f"market_cap=${info['market_cap']:,.0f} "
            f"industry='{industry or 'unknown'}' "
            f"country='{info.get('hq_country', '?')}'")



ALLOWED_RELATIONSHIPS = {
    "operates_in", "supplies_to", "complement_of",
    "substitute_for", "subsidiary_of", "uses_technology", "invested_in",
    "uses_input", "demand_driver", "affected_by_policy",
}

@tool
def add_relationship_to_graph(
    from_name: str,
    from_type: str,
    relationship: str,
    to_name: str,
    to_type: str,
    properties: str = "{}",
) -> str:
    """Add a relationship between two EXISTING entities in the knowledge graph.
    BOTH endpoints must already exist in the graph — this tool will NOT create phantom nodes.
    from_type / to_type: company, industry, technology, commodity, policy, event
    relationship: operates_in, supplies_to, complement_of,
                  substitute_for, subsidiary_of, uses_technology, invested_in,
                  uses_input, demand_driver, affected_by_policy
    properties: JSON string e.g. '{"cost_sensitivity": 0.8}'"""
    if relationship not in ALLOWED_RELATIONSHIPS:
        return f"REJECTED: '{relationship}' is not a valid relationship type. Allowed: {', '.join(sorted(ALLOWED_RELATIONSHIPS))}"
    from_node = graph_db.find_node(from_type, from_name)
    if not from_node:
        return f"REJECTED: {from_type} '{from_name}' does not exist in the graph. Add it first."
    to_node = graph_db.find_node(to_type, to_name)
    if not to_node:
        return f"REJECTED: {to_type} '{to_name}' does not exist in the graph. Add it first."
    props = json.loads(properties) if properties and properties != "{}" else None
    graph_db.create_relationship(from_type, from_name, relationship, to_type, to_name, props)
    return f"Created {from_name} -[{relationship}]-> {to_name}"


ALLOWED_TECHNOLOGIES = {
    "lithium-ion battery", "solid-state battery", "autonomous driving",
    "solar panel", "wind turbine", "5g", "cloud computing", "ai/ml",
    "robotics", "lidar", "electric motor", "fuel cell", "hydrogen storage",
    "semiconductor fabrication", "quantum computing", "blockchain",
    "3d printing", "gene editing", "mrna", "carbon capture",
}

@tool
def add_technology_to_graph(name: str, maturity: str = "") -> str:
    """Add a technology to the knowledge graph. maturity: emerging, growing, mature, declining.
    ONLY allowed values (lowercase): 3d printing, 5g, ai/ml, autonomous driving, blockchain,
    carbon capture, cloud computing, electric motor, fuel cell, gene editing, hydrogen storage,
    lidar, lithium-ion battery, mrna, quantum computing, robotics, semiconductor fabrication,
    solar panel, solid-state battery, wind turbine."""
    name_lower = name.lower().strip()
    if name_lower not in ALLOWED_TECHNOLOGIES:
        return f"REJECTED: '{name}' is not in the allowed technologies list. Allowed: {', '.join(sorted(ALLOWED_TECHNOLOGIES))}"
    _builder.add_technology(name_lower, {"maturity": maturity or None})
    return f"Added technology '{name_lower}'"


ALLOWED_COMMODITIES = {
    "lithium", "cobalt", "nickel", "copper", "steel", "aluminum", "iron ore",
    "semiconductors", "rare earths", "natural gas", "crude oil", "silicon",
    "graphite", "manganese", "platinum", "palladium", "rubber", "glass",
    "polyethylene", "polypropylene", "cotton", "wheat", "corn", "soybeans",
    "timber", "uranium", "zinc", "tin", "gold", "silver",
}

@tool
def add_commodity_to_graph(name: str, category: str = "") -> str:
    """Add a commodity/raw material to the knowledge graph. category: metal, energy, agricultural, chemical.
    ONLY allowed values (lowercase): aluminum, cobalt, copper, corn, cotton, crude oil, glass, gold,
    graphite, iron ore, lithium, manganese, natural gas, nickel, palladium, platinum, polyethylene,
    polypropylene, rare earths, rubber, semiconductors, silicon, silver, soybeans, steel, timber,
    tin, uranium, wheat, zinc."""
    name_lower = name.lower().strip()
    if name_lower not in ALLOWED_COMMODITIES:
        return f"REJECTED: '{name}' is not in the allowed commodities list. Allowed: {', '.join(sorted(ALLOWED_COMMODITIES))}"
    _builder.add_commodity(name_lower, {"category": category or None})
    return f"Added commodity '{name_lower}'"


@tool
def add_event_to_graph(name: str, event_type: str = "", description: str = "", probability: float = 0) -> str:
    """Add a real-world event or shock to the knowledge graph.
    event_type: geopolitical, natural_disaster, trade_war, regulatory, financial, supply_disruption
    Use this for events found via search_industry_events_web that affect industries."""
    _builder.add_event(name, {
        "event_type":  event_type or None,
        "description": description or None,
        "probability": probability or None,
    })
    return f"Added event '{name}'"


@tool
def add_policy_to_graph(name: str, policy_type: str = "", region: str = "", description: str = "") -> str:
    """Add a government policy/subsidy to the knowledge graph.
    policy_type: subsidy, tariff, regulation, tax_credit, ban"""
    _builder.add_policy(name, {
        "policy_type": policy_type or None,
        "region": region or None,
        "description": description or None,
    })
    return f"Added policy '{name}'"


@tool
def get_graph_stats() -> str:
    """Get current stats of the knowledge graph — node and edge counts."""
    stats = graph_db.graph_stats()
    return json.dumps(stats, indent=2)


@tool
def get_companies_from_graph() -> str:
    """Get all companies currently in the graph with their stored wikidata_id and ticker.
    Call this at the START of the enrich and expand phases to get Wikidata IDs for each company,
    so you can call get_company_wikidata_relationships and get_company_supply_chain_wikidata."""
    result = graph_db.query("SELECT name, ticker, wikidata_id FROM company")
    rows = result if isinstance(result, list) else []
    companies = []
    for row in rows:
        if isinstance(row, dict):
            companies.append(row)
        elif isinstance(row, list):
            companies.extend(row)
    return json.dumps(companies, indent=2) if companies else "No companies in graph yet"


# ── Tool lists ─────────────────────────────────────────────────────────────────

# Focused tool sets for multi-agent architecture

DISCOVER_TOOLS = [
    add_company_to_graph,
    search_supply_chain_web,       # Tavily — discover companies via web
]

ENRICH_TOOLS = [
    search_supply_chain_web,
    add_company_to_graph,
    add_relationship_to_graph,
    add_commodity_to_graph,
    add_technology_to_graph,
]

# Full list (kept for backward compat) — deduplicated by name
_all = {t.name: t for t in DISCOVER_TOOLS + ENRICH_TOOLS + [
    search_company_by_name,
    get_company_financials,
    get_company_profile_fmp,
    add_event_to_graph,
    add_policy_to_graph,
    get_graph_stats,
    get_companies_from_graph,
]}
ALL_TOOLS = list(_all.values())
