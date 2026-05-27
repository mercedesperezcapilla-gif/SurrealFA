"""
Supply-Chain Shock Simulator — LangGraph retrieval agent.

Takes a free-text shock statement, explores the SurrealDB knowledge graph,
scores impacts using annotated edge properties (cost_sensitivity, criticality),
and generates an analyst-style report.

Run:
  cd hackathon
  uv run python -m shock_agent "Lithium prices spike 50% due to Chilean export ban"
  uv run python -m shock_agent "TSMC production halts due to earthquake in Taiwan"
  uv run python -m shock_agent "Semiconductor fabrication capacity reduced 30%"
"""

import json
import os
import sys
from typing import TypedDict

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.graph import db as graph_db

load_dotenv()


# ── LLM ──────────────────────────────────────────────────────────────────────

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


# ── State ─────────────────────────────────────────────────────────────────────

class ShockState(TypedDict):
    query: str                    # Free-text shock statement
    shock_type: str               # "commodity" | "company" | "technology"
    shocked_entity: str           # Entity name (e.g., "lithium", "TSMC")
    severity: float               # 0.0–1.0
    affected_edges: list[dict]    # Raw edges from graph traversal
    impact_scores: list[dict]     # Scored impacts per company
    report: str                   # Final analyst report
    geo_concentration: dict       # {score, regions, geo_multiplier}


# ── Node 1: Parse Shock ──────────────────────────────────────────────────────

def parse_shock(state: ShockState) -> dict:
    """LLM extracts shock_type, shocked_entity, and severity from free text."""
    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content="""You extract supply chain shock details from a statement.

Return JSON with exactly three fields:
- "shock_type": one of "commodity", "company", or "technology"
- "shocked_entity": the entity name, lowercase for commodities/technologies
  (e.g. "lithium", "semiconductor fabrication"), proper case for companies (e.g. "TSMC")
- "severity": float 0.0-1.0 (e.g. "prices spike 50%" = 0.5, "complete halt" = 1.0,
  "reduced 30%" = 0.3, "shortage" = 0.6)

Return only valid JSON. No markdown, no explanation."""),
        HumanMessage(content=state["query"]),
    ])
    parsed = json.loads(response.content)
    print(f"\n[1/4] PARSE SHOCK")
    print(f"      Type:     {parsed['shock_type']}")
    print(f"      Entity:   {parsed['shocked_entity']}")
    print(f"      Severity: {parsed['severity']:.0%}")
    return {
        "shock_type": parsed["shock_type"],
        "shocked_entity": parsed["shocked_entity"],
        "severity": parsed["severity"],
    }


# ── Graph schema for the LLM ─────────────────────────────────────────────────

GRAPH_SCHEMA = """
SurrealDB supply chain knowledge graph.

NODE TABLES:
  company    — name (string), ticker, description, market_cap (float), revenue (float),
               employees (int), hq_country, hq_city, website, wikidata_id, founded
  industry   — name (string), sector, description
  commodity  — name (string), category, description, concentration_score (float 0-1)
  technology — name (string), maturity, description
  region     — name (string), country_code, lat (float), lng (float)

EDGE TABLES (directed, from IN to OUT):
  operates_in:    company  → industry
  supplies_to:    company  → company   (cost_sensitivity float 0-1, criticality string)
  uses_input:     company  → commodity (cost_sensitivity float 0-1, criticality string)
  uses_technology: company → technology
  competes_with:  company  → company
  produced_in:    commodity → region   (pct_of_global_supply float 0-1)

QUERY PATTERNS:
  -- All companies using a commodity (with edge annotations):
  SELECT *, in.name AS company, in.ticker AS ticker, in.market_cap AS market_cap,
         in.revenue AS revenue
  FROM uses_input WHERE out.name = 'lithium';

  -- All customers of a supplier company (with edge annotations):
  SELECT *, out.name AS customer, out.ticker AS ticker, out.market_cap AS market_cap
  FROM supplies_to WHERE in.name = 'TSMC';

  -- All companies using a technology:
  SELECT *, in.name AS company, in.ticker AS ticker
  FROM uses_technology WHERE out.name = 'semiconductor fabrication';

  -- Company details:
  SELECT name, ticker, market_cap, revenue, description FROM company WHERE name = 'Tesla';

  -- IMPORTANT: Company names in the DB are full legal names from Yahoo Finance
  -- (e.g. "Taiwan Semiconductor Manufacturing Company Limited" not "TSMC").
  -- Search by partial name match:
  SELECT name, ticker FROM company WHERE string::contains(name, 'Semiconductor');
  -- Or by ticker:
  SELECT name, ticker FROM company WHERE ticker = 'TSM';
  -- Or list all to find the right one:
  SELECT name, ticker FROM company ORDER BY name;
  SELECT name FROM commodity ORDER BY name;
  SELECT name FROM technology ORDER BY name;

  -- Second-hop: customers of customers (cascade):
  SELECT *, out.name AS customer2 FROM supplies_to
  WHERE in.name IN (SELECT out.name FROM supplies_to WHERE in.name = 'TSMC');

  -- All edges for a company:
  SELECT *, out.name AS dst FROM uses_input WHERE in.name = 'Tesla';
  SELECT *, out.name AS dst FROM uses_technology WHERE in.name = 'Tesla';
  SELECT *, in.name AS supplier FROM supplies_to WHERE out.name = 'Tesla';

  -- Geographic concentration: top producing regions for a commodity:
  SELECT pct_of_global_supply, out.name AS region, out.lat AS lat, out.lng AS lng
  FROM produced_in WHERE in.name = 'lithium' ORDER BY pct_of_global_supply DESC;

  -- Commodity concentration score:
  SELECT name, concentration_score FROM commodity WHERE name = 'lithium';

NOTES:
  - Edge annotations cost_sensitivity and criticality are on uses_input and supplies_to edges.
  - cost_sensitivity is 0.0-1.0 (higher = more sensitive to cost changes).
  - criticality is "low", "medium", "high", or "critical".
  - Node IDs are lowercase with underscores: company:`tesla`, commodity:`lithium`.
  - Use `in` for the source node and `out` for the target node in edge queries.
"""


# ── Tool for LLM to query the graph ──────────────────────────────────────────

@tool
def query_graph(sql: str) -> str:
    """Run a SurrealQL query against the supply chain knowledge graph. Returns JSON."""
    try:
        result = graph_db.query(sql)
        return json.dumps(result, default=str, indent=2)
    except Exception as e:
        return f"Query error: {e}"


# ── Node 2: Retrieve Impacts (LLM-driven graph exploration) ──────────────────

def retrieve_impacts(state: ShockState) -> dict:
    """LLM writes SurrealQL queries to find all affected entities."""
    llm = _get_llm().bind_tools([query_graph])

    shock_type = state["shock_type"]
    entity = state["shocked_entity"]
    severity = state["severity"]

    messages = [
        SystemMessage(content=f"""You are a supply chain analyst exploring a knowledge graph
to find all companies affected by a supply chain shock.

{GRAPH_SCHEMA}

TASK:
The shock is: {state['query']}
Shock type: {shock_type} | Entity: {entity} | Severity: {severity:.0%}

Use the query_graph tool to find:

0. RESOLVE NAME — Company names in the DB are full legal names from Yahoo Finance (e.g.
   "Tesla, Inc." not "Tesla", "Taiwan Semiconductor Manufacturing Company Limited" not "TSMC").
   ALWAYS start by finding the entity in the DB:
     SELECT name, ticker FROM company WHERE string::contains(name, 'keyword');
   or by ticker:
     SELECT name, ticker FROM company WHERE ticker = 'TSM';
   or for commodities/technologies:
     SELECT name FROM commodity ORDER BY name;
     SELECT name FROM technology ORDER BY name;
   Use the ACTUAL full name returned in all subsequent queries.

1. DIRECT IMPACTS — all companies directly connected to the shocked entity:
   - If commodity shock: query uses_input edges WHERE out.name = '<actual_name>'
   - If company shock: query supplies_to edges WHERE in.name = '<actual_name>' (find customers)
   - If technology shock: query uses_technology edges WHERE out.name = '<actual_name>'
   IMPORTANT: Include cost_sensitivity and criticality from the edges.

2. SECOND-HOP CASCADE — for each directly affected company, check if other companies
   depend on them via supplies_to edges. This captures cascading effects.

3. COMPANY DETAILS — for key affected companies, fetch their market_cap, revenue,
   and description for the report.

When done exploring, output ONLY a JSON object:
{{
  "direct_impacts": [
    {{"company": "...", "ticker": "...", "market_cap": ..., "revenue": ...,
      "edge_type": "uses_input|supplies_to|uses_technology",
      "cost_sensitivity": ..., "criticality": "...",
      "reason": "short explanation"}}
  ],
  "cascade_impacts": [
    {{"company": "...", "ticker": "...", "market_cap": ...,
      "depends_on": "directly affected company name",
      "edge_type": "supplies_to",
      "cost_sensitivity": ..., "criticality": "...",
      "reason": "short explanation"}}
  ]
}}
No markdown. No explanation. Just the JSON."""),
        HumanMessage(content=f"Analyze shock: {state['query']}"),
    ]

    print(f"\n[2/4] RETRIEVE IMPACTS — exploring graph...")

    for _ in range(15):
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            sql = tc["args"]["sql"]
            print(f"      query: {sql.strip()[:100]}")
            result = query_graph.invoke(tc["args"])
            print(f"      result: {str(result)[:200]}")
            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    # Parse LLM's structured output
    try:
        traversal = json.loads(response.content)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        content = response.content
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            traversal = json.loads(content[start:end])
        else:
            traversal = {"direct_impacts": [], "cascade_impacts": []}

    direct = traversal.get("direct_impacts", [])
    cascade = traversal.get("cascade_impacts", [])
    all_edges = direct + cascade
    print(f"      found: {len(direct)} direct, {len(cascade)} cascade impacts")

    # Fetch geographic concentration for commodity shocks
    geo_data = {"score": 0.0, "regions": [], "geo_multiplier": 1.0}
    if state["shock_type"] == "commodity":
        from geo_enrich import get_concentration_score, get_production_regions
        commodity = state["shocked_entity"]
        score = get_concentration_score(commodity)
        regions = get_production_regions(commodity)
        geo_multiplier = round(1 + (score * 0.5), 3)
        geo_data = {
            "score": score,
            "regions": regions,
            "geo_multiplier": geo_multiplier,
        }
        if score > 0:
            print(f"      geo concentration: {score:.3f} → {geo_multiplier:.2f}x multiplier")
            for r in regions[:3]:
                print(f"        {r.get('region', '?')}: {r.get('pct_of_global_supply', 0):.0%}")

    return {"affected_edges": all_edges, "geo_concentration": geo_data}


# ── Node 3: Calculate Cascade (deterministic scoring) ─────────────────────────

CRIT_MULTIPLIER = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}


def calculate_cascade(state: ShockState) -> dict:
    """Score each affected company using edge annotations + geographic concentration."""
    severity = state["severity"]
    affected = state.get("affected_edges", [])
    is_cascade = {e.get("company") for e in affected if e.get("depends_on")}

    # Geographic concentration multiplier
    geo = state.get("geo_concentration", {})
    geo_multiplier = geo.get("geo_multiplier", 1.0)

    scores = []
    for edge in affected:
        company = edge.get("company", "Unknown")
        ticker = edge.get("ticker", "?")
        market_cap = edge.get("market_cap")
        revenue = edge.get("revenue")

        cs = edge.get("cost_sensitivity") or 0.5
        crit = (edge.get("criticality") or "medium").lower()
        cm = CRIT_MULTIPLIER.get(crit, 0.5)

        # Direct vs cascade scoring
        if edge.get("depends_on"):
            # Second-hop: attenuate by 0.6
            raw_score = severity * cs * cm * 0.6
            hop = 2
        else:
            raw_score = severity * cs * cm
            hop = 1

        # Apply geographic concentration multiplier
        raw_score = raw_score * geo_multiplier

        raw_score = round(raw_score, 3)

        if raw_score > 0.5:
            rating = "CRITICAL"
        elif raw_score > 0.3:
            rating = "HIGH"
        elif raw_score > 0.15:
            rating = "MODERATE"
        else:
            rating = "LOW"

        scores.append({
            "company": company,
            "ticker": ticker,
            "market_cap": market_cap,
            "revenue": revenue,
            "impact_score": raw_score,
            "rating": rating,
            "hop": hop,
            "cost_sensitivity": cs,
            "criticality": crit,
            "depends_on": edge.get("depends_on"),
            "reason": edge.get("reason", ""),
        })

    # Deduplicate: keep highest-scoring entry per company
    best = {}
    for s in scores:
        name = s["company"]
        if name not in best or s["impact_score"] > best[name]["impact_score"]:
            best[name] = s
    scores = sorted(best.values(), key=lambda x: x["impact_score"], reverse=True)

    print(f"\n[3/4] CALCULATE CASCADE")
    if geo.get("score", 0) > 0:
        print(f"      Geographic concentration: {geo['score']:.3f} → {geo_multiplier:.2f}x multiplier")
    print(f"      {'Company':<20} {'Ticker':<8} {'Score':<8} {'Rating':<10} {'Hop'}")
    print(f"      {'─'*20} {'─'*8} {'─'*8} {'─'*10} {'─'*4}")
    for s in scores:
        print(f"      {s['company']:<20} {s['ticker']:<8} {s['impact_score']:<8.3f} {s['rating']:<10} {s['hop']}")

    return {"impact_scores": scores}


# ── Node 4: Generate Report ──────────────────────────────────────────────────

def generate_report(state: ShockState) -> dict:
    """LLM writes a concise analyst-style impact report."""
    llm = _get_llm()

    # Build geographic context
    geo = state.get("geo_concentration", {})
    geo_context = ""
    if geo.get("score", 0) > 0:
        regions = geo.get("regions", [])
        top_regions = regions[:5] if regions else []
        region_text = ", ".join(
            f"{r.get('region', '?')} ({r.get('pct_of_global_supply', 0):.0%})"
            for r in top_regions
        )
        geo_context = f"""
GEOGRAPHIC CONCENTRATION:
  Concentration Score (HHI): {geo['score']:.3f} (0=globally distributed, 1=single country)
  Geographic Multiplier Applied: {geo.get('geo_multiplier', 1.0):.2f}x
  Top Producing Regions: {region_text}
"""

    context = f"""SHOCK EVENT: {state['query']}
Type: {state['shock_type']} | Entity: {state['shocked_entity']} | Severity: {state['severity']:.0%}
{geo_context}
IMPACT SCORES (sorted by severity):
{json.dumps(state['impact_scores'], indent=2, default=str)}
"""

    response = llm.invoke([
        SystemMessage(content="""You are a supply chain risk analyst at a major investment bank.
Write a concise, data-driven impact report (5 sections):

1. **Shock Event** — What happened and to which entity. One paragraph.

2. **Geographic Concentration Risk** — If geographic concentration data is provided,
   explain how the geographic distribution of production amplifies or dampens the shock.
   Which countries dominate production? What does this mean for alternative sourcing?
   Skip this section if no geographic data is available.

3. **Direct Impacts** — Which companies are directly affected and why.
   Include their tickers, impact scores, and the supply chain link.
   Focus on CRITICAL and HIGH rated companies.

4. **Cascade Effects** — Second-order impacts through the supply chain.
   Which companies are indirectly affected because they depend on directly-hit companies?

5. **Investment Implications** — Which stocks face the most risk? Any beneficiaries
   (competitors of affected companies)? Actionable takeaways.

Use specific numbers from the data. Write for a portfolio manager audience.
Keep it under 600 words."""),
        HumanMessage(content=context),
    ])

    report = response.content

    print(f"\n{'═'*60}")
    print(f"  SHOCK IMPACT REPORT")
    print(f"{'═'*60}")
    print(report)
    print(f"{'═'*60}\n")

    return {"report": report}


# ── Build the LangGraph pipeline ─────────────────────────────────────────────

def build_shock_agent():
    g = StateGraph(ShockState)
    g.add_node("parse_shock", parse_shock)
    g.add_node("retrieve_impacts", retrieve_impacts)
    g.add_node("calculate_cascade", calculate_cascade)
    g.add_node("generate_report", generate_report)

    g.set_entry_point("parse_shock")
    g.add_edge("parse_shock", "retrieve_impacts")
    g.add_edge("retrieve_impacts", "calculate_cascade")
    g.add_edge("calculate_cascade", "generate_report")
    g.add_edge("generate_report", END)

    return g.compile(checkpointer=MemorySaver())


# ── CLI ───────────────────────────────────────────────────────────────────────

def run_shock(query: str):
    """Run the shock simulator on a free-text query."""
    agent = build_shock_agent()
    config = {"configurable": {"thread_id": f"shock-{hash(query) % 10000}"}}

    result = agent.invoke(
        {
            "query": query,
            "shock_type": "",
            "shocked_entity": "",
            "severity": 0.0,
            "affected_edges": [],
            "impact_scores": [],
            "report": "",
            "geo_concentration": {},
        },
        config=config,
    )
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print('  uv run python -m shock_agent "Lithium prices spike 50%"')
        print('  uv run python -m shock_agent "TSMC production halts due to earthquake"')
        print('  uv run python -m shock_agent "Semiconductor fabrication bottleneck"')
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    run_shock(query)
