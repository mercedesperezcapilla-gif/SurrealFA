"""
Geographic Concentration Enrichment — populates region nodes and
produced_in edges for commodities in the knowledge graph.

For each commodity, uses Tavily web search to find production-by-country
data, LLM to parse it into structured JSON, then writes region nodes,
produced_in edges, and computes a Herfindahl concentration_score.

Run:
  cd hackathon
  uv run python -m geo_enrich
  uv run python -m geo_enrich lithium cobalt steel
"""

import json
import os
import sys

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from src.connectors.tavily_connector import _get_client
from src.graph import db as graph_db
from src.graph.builder import GraphBuilder

load_dotenv()

_builder = GraphBuilder()

# ── Country coordinates (major producing nations) ────────────────────────────

COUNTRY_COORDS = {
    "Chile": (-33.45, -70.67), "Australia": (-25.27, 133.78),
    "China": (35.86, 104.20), "Argentina": (-38.42, -63.62),
    "DR Congo": (-4.04, 21.76), "DRC": (-4.04, 21.76),
    "Congo": (-4.04, 21.76), "Indonesia": (-0.79, 113.92),
    "Philippines": (12.88, 121.77), "Russia": (61.52, 105.32),
    "Canada": (56.13, -106.35), "South Africa": (-30.56, 22.94),
    "Brazil": (-14.24, -51.93), "India": (20.59, 78.96),
    "United States": (37.09, -95.71), "USA": (37.09, -95.71),
    "Peru": (-9.19, -75.02), "Mexico": (23.63, -102.55),
    "Japan": (36.20, 138.25), "South Korea": (35.91, 127.77),
    "Taiwan": (23.70, 120.96), "Germany": (51.17, 10.45),
    "Saudi Arabia": (23.89, 45.08), "Myanmar": (21.91, 95.96),
    "Zambia": (-13.13, 27.85), "Zimbabwe": (-19.02, 29.15),
    "New Caledonia": (-20.90, 165.62), "Cuba": (-21.52, -77.78),
    "Turkey": (38.96, 35.24), "Kazakhstan": (48.02, 66.92),
    "Morocco": (31.79, -7.09), "Thailand": (15.87, 100.99),
    "Vietnam": (14.06, 108.28), "Norway": (60.47, 8.47),
    "Ukraine": (48.38, 31.17), "Poland": (51.92, 19.15),
    "Iran": (32.43, 53.69), "Malaysia": (4.21, 101.98),
    "Bolivia": (-16.29, -63.59), "Colombia": (4.57, -74.30),
    "Papua New Guinea": (-6.31, 143.96), "Spain": (40.46, -3.75),
    "Italy": (41.87, 12.57), "United Kingdom": (55.38, -3.44),
    "Sweden": (60.13, 18.64), "Finland": (61.92, 25.75),
}

COUNTRY_CODES = {
    "Chile": "CL", "Australia": "AU", "China": "CN", "Argentina": "AR",
    "DR Congo": "CD", "DRC": "CD", "Congo": "CD", "Indonesia": "ID",
    "Philippines": "PH", "Russia": "RU", "Canada": "CA",
    "South Africa": "ZA", "Brazil": "BR", "India": "IN",
    "United States": "US", "USA": "US", "Peru": "PE", "Mexico": "MX",
    "Japan": "JP", "South Korea": "KR", "Taiwan": "TW", "Germany": "DE",
    "Saudi Arabia": "SA", "Myanmar": "MM", "Zambia": "ZM",
    "Zimbabwe": "ZW", "New Caledonia": "NC", "Cuba": "CU", "Turkey": "TR",
    "Kazakhstan": "KZ", "Bolivia": "BO", "Norway": "NO", "Ukraine": "UA",
    "Poland": "PL", "Iran": "IR", "Malaysia": "MY", "Colombia": "CO",
    "Thailand": "TH", "Vietnam": "VN", "Morocco": "MA",
    "Papua New Guinea": "PG", "Spain": "ES", "Italy": "IT",
    "United Kingdom": "GB", "Sweden": "SE", "Finland": "FI",
}


def _get_llm() -> AzureChatOpenAI:
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return AzureChatOpenAI(
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_ad_token_provider=token_provider,
        temperature=0,
    )


def _flatten(result) -> list[dict]:
    if not result:
        return []
    rows = []
    for item in (result if isinstance(result, list) else [result]):
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list):
            rows.extend(r for r in item if isinstance(r, dict))
    return rows


def _search_commodity_production(commodity_name: str) -> str:
    """Search Tavily for production-by-country data for a commodity."""
    client = _get_client()
    query = f"{commodity_name} production by country percentage global share 2025"
    result = client.search(query, max_results=5, search_depth="advanced")
    snippets = []
    for r in result.get("results", []):
        snippets.append(r.get("content", ""))
    return "\n\n".join(snippets)


def _parse_production_data(llm, commodity_name: str, search_text: str) -> list[dict]:
    """Use LLM to parse search results into structured production data."""
    response = llm.invoke([
        SystemMessage(content="""You extract commodity production data from web search results.

Return a JSON array of objects, each with:
- "region": country name (e.g. "Chile", "Australia", "China")
- "pct": float between 0.0 and 1.0 representing that country's share of global production
  (e.g. 0.32 means 32% of global production)

RULES:
- Only include countries with > 1% share (pct > 0.01)
- Percentages should sum to roughly 0.80-1.00 (top producers)
- If the data says "30%" use 0.30
- Include the top 5-8 producing countries
- If data is unclear, use your best estimate based on known production data
- Return ONLY valid JSON array. No markdown, no explanation."""),
        HumanMessage(content=f"Commodity: {commodity_name}\n\nSearch results:\n{search_text[:3000]}"),
    ])
    try:
        data = json.loads(response.content)
    except json.JSONDecodeError:
        content = response.content
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            data = json.loads(content[start:end])
        else:
            data = []
    return data


def _compute_herfindahl(shares: list[float]) -> float:
    """Compute Herfindahl-Hirschman Index from market shares.
    Returns 0.0 (perfectly distributed) to 1.0 (single producer)."""
    if not shares:
        return 0.5
    return round(min(1.0, sum(s * s for s in shares)), 3)


def enrich_commodity(commodity_name: str, llm=None) -> dict:
    """Enrich a single commodity with geographic production data."""
    if llm is None:
        llm = _get_llm()

    print(f"\n  Searching: {commodity_name} production by country...")
    search_text = _search_commodity_production(commodity_name)

    if not search_text.strip():
        print(f"    No search results for {commodity_name}")
        return {"commodity": commodity_name, "regions": [], "concentration_score": 0.5}

    print(f"    Parsing production data with LLM...")
    production_data = _parse_production_data(llm, commodity_name, search_text)

    if not production_data:
        print(f"    LLM returned no production data for {commodity_name}")
        return {"commodity": commodity_name, "regions": [], "concentration_score": 0.5}

    regions_created = []
    shares = []
    for entry in production_data:
        region_name = entry.get("region", "")
        pct = entry.get("pct", 0.0)
        if not region_name or pct <= 0:
            continue

        coords = COUNTRY_COORDS.get(region_name, (0.0, 0.0))
        country_code = COUNTRY_CODES.get(region_name, "")

        _builder.add_region(region_name, {
            "country_code": country_code,
            "lat": coords[0],
            "lng": coords[1],
        })

        _builder.link_commodity_to_region(
            commodity_name, region_name,
            {"pct_of_global_supply": round(pct, 3), "source": "tavily+llm"},
        )

        shares.append(pct)
        regions_created.append({"region": region_name, "pct": pct})
        print(f"    {region_name}: {pct:.0%}")

    concentration = _compute_herfindahl(shares)
    graph_db.query(
        "UPDATE commodity SET concentration_score = $score WHERE name = $name",
        {"score": concentration, "name": commodity_name},
    )
    print(f"    concentration_score = {concentration:.3f}")

    return {
        "commodity": commodity_name,
        "regions": regions_created,
        "concentration_score": concentration,
    }


def enrich_all_commodities(commodity_names: list[str] | None = None) -> list[dict]:
    """Enrich all (or specific) commodities with geographic production data."""
    if commodity_names is None:
        rows = _flatten(graph_db.query("SELECT name FROM commodity ORDER BY name"))
        commodity_names = [r.get("name", "") for r in rows if r.get("name")]

    if not commodity_names:
        print("No commodities found in graph.")
        return []

    print(f"{'='*60}")
    print(f"  GEO ENRICHMENT — {len(commodity_names)} commodities")
    print(f"{'='*60}")

    llm = _get_llm()
    results = []
    for name in commodity_names:
        result = enrich_commodity(name, llm=llm)
        results.append(result)

    print(f"\n{'='*60}")
    print(f"  GEO ENRICHMENT COMPLETE")
    for r in results:
        print(f"    {r['commodity']}: {r['concentration_score']:.3f} ({len(r['regions'])} regions)")
    print(f"{'='*60}\n")

    return results


# ── Public helpers for shock_agent ───────────────────────────────────────────

def get_concentration_score(commodity_name: str) -> float:
    """Fetch the concentration_score for a commodity. Returns 0.0 if not found."""
    rows = _flatten(graph_db.query(
        "SELECT concentration_score FROM commodity WHERE name = $name",
        {"name": commodity_name},
    ))
    if rows and rows[0].get("concentration_score") is not None:
        return float(rows[0]["concentration_score"])
    return 0.0


def get_production_regions(commodity_name: str) -> list[dict]:
    """Fetch production regions for a commodity.
    Returns [{region, pct_of_global_supply, lat, lng, country_code}]."""
    rows = _flatten(graph_db.query(
        "SELECT pct_of_global_supply, out.name AS region, out.lat AS lat, "
        "out.lng AS lng, out.country_code AS country_code "
        "FROM produced_in WHERE in.name = $name ORDER BY pct_of_global_supply DESC",
        {"name": commodity_name},
    ))
    return rows


if __name__ == "__main__":
    if len(sys.argv) > 1:
        enrich_all_commodities(sys.argv[1:])
    else:
        enrich_all_commodities()
