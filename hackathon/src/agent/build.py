"""
LangGraph knowledge-graph builder.

Architecture:
    discover → review_discover (interrupt) → fan_out → enrich (per company via Send)
    → review_enrich (interrupt) → summarize → END

Usage:
    cd hackathon
    uv run python -m src.agent.build "Electric Vehicles" 3
"""

import json
import os
import sys

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.agent.state import BuildState, CompanyTask
from src.agent.tools import DISCOVER_TOOLS, ENRICH_TOOLS
from src.graph import db as graph_db

load_dotenv()


# ── LLM ───────────────────────────────────────────────────────────────────────

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


# ── Agent loop helper ─────────────────────────────────────────────────────────

def _run_agent_loop(system_prompt: str, tools: list, label: str, max_rounds: int = 20) -> list:
    """LLM calls tools until done. Returns message history."""
    llm = _get_llm().bind_tools(tools)
    tool_map = {t.name: t for t in tools}
    messages = [SystemMessage(content=system_prompt)]

    for _ in range(max_rounds):
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            if response.content:
                print(f"\n[{label}] {str(response.content)[:300]}")
            break

        for tc in response.tool_calls:
            print(f"  -> {tc['name']}({str(tc['args'])[:100]})")
            try:
                result = str(tool_map[tc["name"]].invoke(tc["args"]))
            except Exception as e:
                result = f"Error: {e}"
            print(f"  <- {result[:200]}")
            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    return messages


# ── Prompts ───────────────────────────────────────────────────────────────────

DISCOVER_PROMPT = """You are a financial research agent building a knowledge graph.

Task: Find {num_companies} major companies in the "{query}" industry.

Steps:
1. Search the web using search_supply_chain_web("top {query} companies") to find major players
2. For each company found, call add_company_to_graph(ticker=TICKER) with the company's stock ticker.
   The tool will fetch and validate data from Yahoo Finance automatically.
   If the tool returns REJECTED, try a different ticker or skip that company.

RULES:
- You MUST add exactly {num_companies} companies. Do not stop early.
- Only use add_company_to_graph — it handles everything (company + industry + operates_in edge).
- If a non-US company has multiple ticker variants (e.g. BYD → BYDDF, BYDDY), try them until one works.
"""

ENRICH_PROMPT = """You are a financial research agent enriching supply chain data for one company.

Company: {company_name} (Ticker: {ticker})

RULES:
- add_company_to_graph requires a stock TICKER — it fetches data from Yahoo Finance.
- add_commodity_to_graph and add_technology_to_graph only accept items from a whitelist.
  If a tool returns REJECTED, do NOT retry with the same value.
- add_relationship_to_graph requires BOTH endpoints to already exist in the graph.
  Add the nodes FIRST, then create the edge.

Do these steps:

1. SUPPLIERS — Call search_supply_chain_web("{company_name} major suppliers") AND
   search_supply_chain_web("{company_name} supply chain partners")
   - Find named supplier COMPANIES (e.g. Panasonic, CATL, Samsung SDI)
   - For non-US companies, try ticker variants: add .T for Tokyo, .SZ for Shenzhen, .HK for Hong Kong
   - For each: call add_company_to_graph(ticker=THEIR_TICKER) to add them
   - Then: add_relationship_to_graph(supplier_name, "company", "supplies_to", "{company_name}", "company")

2. COMMODITIES — Call search_supply_chain_web("{company_name} raw materials inputs commodities")
   - Find raw materials (e.g. lithium, cobalt, semiconductors, steel, copper, aluminum)
   - For each: call add_commodity_to_graph(name) then
     add_relationship_to_graph("{company_name}", "company", "uses_input", commodity_name, "commodity")

3. TECHNOLOGIES — Read the company description below and identify which technologies from the
   allowed list apply to this company. Do NOT call any search tools for this step.
   Allowed technologies: lithium-ion battery, solid-state battery, autonomous driving, solar panel,
   wind turbine, 5g, cloud computing, ai/ml, robotics, lidar, electric motor, fuel cell,
   hydrogen storage, semiconductor fabrication, quantum computing, blockchain, 3d printing,
   gene editing, mrna, carbon capture.
   - For each match: call add_technology_to_graph(name) then
     add_relationship_to_graph("{company_name}", "company", "uses_technology", tech_name, "technology")

Company description:
{description}

Add up to 5 suppliers, 5 commodities, and 3 technologies per company. Be thorough.
"""


# ── Graph nodes ───────────────────────────────────────────────────────────────

def discover_node(state: BuildState) -> dict:
    """Single agent discovers companies in an industry."""
    query = state["query"]
    num = state["num_companies"]

    print(f"\n{'='*60}")
    print(f"  DISCOVER: {query} ({num} companies)")
    print(f"{'='*60}\n")

    prompt = DISCOVER_PROMPT.format(query=query, num_companies=num)
    msgs = _run_agent_loop(prompt, DISCOVER_TOOLS, "DISCOVER")
    return {"messages": msgs}


def review_discover(state: BuildState) -> dict:
    """Print what was discovered. Graph pauses here via interrupt_before."""
    rows = _flatten(graph_db.query("SELECT name, ticker FROM company ORDER BY name"))
    print(f"\n{'='*60}")
    print(f"  DISCOVER COMPLETE — {len(rows)} companies")
    for r in rows:
        print(f"    {r.get('name', '?')} ({r.get('ticker', '?')})")
    industries = _flatten(graph_db.query("SELECT name FROM industry"))
    print(f"  Industries: {[r.get('name') for r in industries]}")
    print(f"{'='*60}\n")
    return {}


def fan_out_enrich(state: BuildState) -> list[Send]:
    """Query DB for companies and fan out one enrich agent per company."""
    rows = _flatten(graph_db.query("SELECT name, ticker, wikidata_id, description FROM company ORDER BY name"))
    sends = []
    for r in rows:
        sends.append(Send("enrich_node", CompanyTask(
            company_name=r.get("name", ""),
            ticker=r.get("ticker", ""),
            wikidata_id=r.get("wikidata_id", ""),
            description=r.get("description", ""),
        )))
    print(f"  Fanning out {len(sends)} enrich agents...")
    return sends


def enrich_node(state: CompanyTask) -> dict:
    """Per-company agent: adds suppliers, commodities, technologies."""
    name = state["company_name"]
    ticker = state["ticker"]
    wikidata_id = state["wikidata_id"]
    description = state.get("description", "")

    print(f"\n{'─'*40}")
    print(f"  ENRICH: {name} ({ticker})")
    print(f"{'─'*40}")

    prompt = ENRICH_PROMPT.format(
        company_name=name, ticker=ticker, wikidata_id=wikidata_id,
        description=description or "No description available.",
    )
    try:
        _run_agent_loop(prompt, ENRICH_TOOLS, f"ENRICH:{name}")
        print(f"  [ENRICH] Done: {name}")
    except Exception as e:
        print(f"  [ENRICH] FAILED: {name} — {e}")
    return {"companies_enriched": [name]}


def review_enrich(state: BuildState) -> dict:
    """Print enrichment results. Graph pauses here via interrupt_before."""
    stats = graph_db.graph_stats()
    print(f"\n{'='*60}")
    print(f"  ENRICH COMPLETE")
    print(f"  Companies enriched: {state.get('companies_enriched', [])}")
    print(json.dumps(stats, indent=4))
    print(f"{'='*60}\n")
    return {}


def summarize_node(state: BuildState) -> dict:
    """Final summary — print full graph contents."""
    print(f"\n{'='*60}")
    print(f"  FINAL GRAPH")
    print(f"{'='*60}")

    for table in ["company", "industry", "commodity", "technology"]:
        rows = _flatten(graph_db.query(f"SELECT name FROM {table} ORDER BY name"))
        if rows:
            print(f"\n  {table} ({len(rows)}):")
            for r in rows:
                print(f"    {r.get('name', '?')}")

    for rel in ["operates_in", "supplies_to", "uses_input", "uses_technology"]:
        rows = _flatten(graph_db.query(
            f"SELECT in.name AS src, out.name AS dst FROM {rel}"
        ))
        if rows:
            print(f"\n  {rel} ({len(rows)}):")
            for r in rows:
                print(f"    {r.get('src', '?')} -> {r.get('dst', '?')}")

    print(f"\n{'='*60}\n")
    return {}


# ── Build the graph ──────────────────────────────────────────────────────────

def create_graph():
    """Create the LangGraph build workflow."""
    workflow = StateGraph(BuildState)

    workflow.add_node("discover_node", discover_node)
    workflow.add_node("review_discover", review_discover)
    workflow.add_node("enrich_node", enrich_node)
    workflow.add_node("review_enrich", review_enrich)
    workflow.add_node("summarize_node", summarize_node)

    workflow.add_edge(START, "discover_node")
    workflow.add_edge("discover_node", "review_discover")
    workflow.add_conditional_edges("review_discover", fan_out_enrich)
    workflow.add_edge("enrich_node", "review_enrich")
    workflow.add_edge("review_enrich", "summarize_node")
    workflow.add_edge("summarize_node", END)

    return workflow.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["review_discover", "review_enrich"],
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def clear_db():
    tables = ['company', 'industry', 'technology', 'commodity', 'policy', 'event',
              'operates_in', 'competes_with', 'supplies_to', 'uses_input', 'uses_technology',
              'subsidiary_of', 'complement_of', 'substitute_for', 'invested_in',
              'demand_driver', 'affected_by_policy']
    for t in tables:
        try:
            graph_db.query(f"DELETE {t}")
        except Exception:
            pass
    print("DB cleared.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _prompt(msg: str) -> bool:
    """Prompt user to continue. Returns False if user quits. Auto-continues if not a TTY."""
    if not sys.stdin.isatty():
        return True
    resp = input(msg).strip().lower()
    return resp != "q"


def run_enrich_thin(min_edges: int = 3):
    """Re-enrich companies that have fewer than min_edges relationships."""
    # Count edges per company
    companies = _flatten(graph_db.query("SELECT name, ticker, description FROM company ORDER BY name"))
    thin = []
    for c in companies:
        name = c.get("name", "")
        count = 0
        for rel in ["supplies_to", "uses_input", "uses_technology"]:
            rows = graph_db.query(
                f"SELECT count() AS n FROM {rel} WHERE in.name = $name OR out.name = $name GROUP ALL",
                {"name": name},
            )
            if rows and isinstance(rows[0], dict):
                count += rows[0].get("n", 0)
        if count < min_edges:
            thin.append(c)

    if not thin:
        print("All companies already well-connected.")
        return

    print(f"\n{'='*60}")
    print(f"  DEEP ENRICH — {len(thin)} thin companies")
    for c in thin:
        print(f"    {c.get('name')} ({c.get('ticker')})")
    print(f"{'='*60}\n")

    for c in thin:
        name = c.get("name", "")
        ticker = c.get("ticker", "")
        description = c.get("description", "")
        print(f"\n{'─'*40}")
        print(f"  ENRICH: {name} ({ticker})")
        print(f"{'─'*40}")
        prompt = ENRICH_PROMPT.format(
            company_name=name, ticker=ticker, wikidata_id="",
            description=description or "No description available.",
        )
        try:
            _run_agent_loop(prompt, ENRICH_TOOLS, f"ENRICH:{name}")
            print(f"  [ENRICH] Done: {name}")
        except Exception as e:
            print(f"  [ENRICH] FAILED: {name} — {e}")

    print()
    summarize_node({})


VALIDATE_PROMPT = """You are a data quality validator for a financial knowledge graph.

Review these relationships and decide which are VALID and which are BOGUS.
A relationship is BOGUS if:
- The company description does NOT support this relationship
- The relationship is factually wrong (e.g. a software company using lithium as raw material)
- The relationship confuses the company with a different entity

For each relationship, respond with EXACTLY one line in this format:
VALID: Company -> relationship -> Target (reason)
BOGUS: Company -> relationship -> Target (reason)

Here are the relationships to validate:

{edges}

Company descriptions for reference:
{descriptions}
"""


def run_validate():
    """Validate all relationships using LLM + company descriptions."""
    print(f"\n{'='*60}")
    print(f"  VALIDATOR AGENT")
    print(f"{'='*60}\n")

    # Gather all edges
    edges_to_check = []
    edge_ids = {}  # key -> id for deletion

    for rel in ["uses_input", "supplies_to", "uses_technology"]:
        rows = _flatten(graph_db.query(
            f"SELECT id, in.name AS src, out.name AS dst FROM {rel}"
        ))
        for r in rows:
            src, dst = r.get("src", ""), r.get("dst", "")
            key = f"{src} -[{rel}]-> {dst}"
            edges_to_check.append(key)
            edge_ids[key] = r.get("id")

    if not edges_to_check:
        print("No edges to validate.")
        return

    # Gather company descriptions
    companies = _flatten(graph_db.query("SELECT name, description FROM company"))
    desc_text = ""
    for c in companies:
        name = c.get("name", "")
        desc = c.get("description", "")
        if desc:
            desc_text += f"\n{name}:\n{desc[:300]}\n"

    # Batch edges (LLM can handle ~50 at a time)
    edges_text = "\n".join(edges_to_check)

    prompt = VALIDATE_PROMPT.format(edges=edges_text, descriptions=desc_text)
    llm = _get_llm()
    response = llm.invoke(prompt)
    result = response.content

    # Parse response
    bogus_count = 0
    valid_count = 0
    for line in result.strip().split("\n"):
        line = line.strip()
        if line.startswith("BOGUS:"):
            # Extract the edge key
            edge_part = line[6:].strip()
            # Find matching key
            for key, eid in edge_ids.items():
                if key in edge_part or edge_part.startswith(key.split(" -[")[0]):
                    # Try exact match first
                    pass
            # Match by checking each known key
            matched = False
            for key, eid in edge_ids.items():
                src = key.split(" -[")[0]
                dst = key.split("]-> ")[1] if "]-> " in key else ""
                if src in edge_part and dst in edge_part:
                    print(f"  REMOVING: {key}")
                    try:
                        graph_db.query(f"DELETE {eid}")
                        bogus_count += 1
                    except Exception as e:
                        print(f"    Error: {e}")
                    matched = True
                    break
            if not matched and "BOGUS" in line:
                print(f"  {line}")
        elif line.startswith("VALID:"):
            valid_count += 1

    print(f"\n  Result: {valid_count} valid, {bogus_count} bogus removed")
    print(f"{'='*60}\n")


ANNOTATE_PROMPT = """You are a financial analyst annotating a supply chain knowledge graph.

For each relationship below, estimate:
- cost_sensitivity (0.0-1.0): How much would a 50% price increase in this input affect the company's costs?
  1.0 = devastating (core to the product, no substitute, large % of COGS)
  0.5 = moderate (important but substitutable or small % of costs)
  0.1 = minimal (minor input, easily substituted)
- criticality: "critical" | "high" | "medium" | "low"
  critical = single-source dependency, production stops without it
  high = major input, hard to substitute quickly
  medium = important but substitutable within months
  low = commodity with many suppliers

Use the company financials and descriptions to ground your estimates.
Companies with LOW gross margins are MORE sensitive to input cost changes.

Respond with EXACTLY one line per relationship in this format:
EDGE: src -> rel -> dst | cost_sensitivity=X.X | criticality=LEVEL

Company data:
{company_data}

Relationships to annotate:
{edges}
"""


def run_annotate():
    """Annotate edges with cost_sensitivity and criticality."""
    from src.connectors.yfinance_connector import get_key_stats

    print(f"\n{'='*60}")
    print(f"  ANNOTATE EDGES")
    print(f"{'='*60}\n")

    # Get company data with margins
    companies = _flatten(graph_db.query("SELECT name, ticker, market_cap, revenue, description FROM company ORDER BY name"))
    company_data = ""
    for c in companies:
        name = c.get("name", "")
        ticker = c.get("ticker", "")
        stats = get_key_stats(ticker) or {}
        gm = stats.get("gross_margin")
        om = stats.get("operating_margin")
        desc = (c.get("description") or "")[:200]
        company_data += (
            f"\n{name} ({ticker}): "
            f"gross_margin={f'{gm:.1%}' if gm else '?'}, "
            f"operating_margin={f'{om:.1%}' if om else '?'}, "
            f"revenue=${c.get('revenue', 0) or 0:,.0f}\n"
            f"  {desc}\n"
        )

    # Gather edges to annotate
    edges_text = ""
    edge_lookup = {}  # "src|rel|dst" -> (rel, edge_id)

    for rel in ["uses_input", "supplies_to"]:
        rows = _flatten(graph_db.query(
            f"SELECT id, in.name AS src, out.name AS dst FROM {rel}"
        ))
        for r in rows:
            src, dst = r.get("src", ""), r.get("dst", "")
            key = f"{src} -> {rel} -> {dst}"
            edges_text += f"{key}\n"
            edge_lookup[key] = (rel, r.get("id"))

    if not edge_lookup:
        print("No edges to annotate.")
        return

    print(f"  Annotating {len(edge_lookup)} edges...")
    prompt = ANNOTATE_PROMPT.format(company_data=company_data, edges=edges_text)
    llm = _get_llm()
    response = llm.invoke(prompt)

    # Parse and update
    updated = 0
    for line in response.content.strip().split("\n"):
        line = line.strip()
        if line.startswith("```") or not line or "|" not in line:
            continue
        line = line.replace("EDGE:", "").strip()
        try:
            parts = line.split("|")
            edge_part = parts[0].strip()
            cs_part = [p for p in parts if "cost_sensitivity" in p][0]
            cr_part = [p for p in parts if "criticality" in p][0]
            cost_sens = float(cs_part.split("=")[1].strip())
            criticality = cr_part.split("=")[1].strip().lower()

            # Find matching edge
            for key, (rel, eid) in edge_lookup.items():
                src = key.split(" -> ")[0]
                dst = key.split(" -> ")[2]
                if src in edge_part and dst in edge_part:
                    graph_db.query(
                        f"UPDATE {eid} SET cost_sensitivity = $cs, criticality = $cr",
                        {"cs": cost_sens, "cr": criticality},
                    )
                    print(f"  {src:40s} -> {dst:20s} cs={cost_sens:.1f} crit={criticality}")
                    updated += 1
                    break
        except Exception:
            continue

    print(f"\n  Updated {updated}/{len(edge_lookup)} edges")
    print(f"{'='*60}\n")


def run_build(query: str, num_companies: int):
    """Run the full build pipeline with interactive pauses."""
    graph = create_graph()
    config = {"configurable": {"thread_id": "build-1"}}

    # Step 1: Discover — runs until interrupt at review_discover
    print("\nStep 1: Discovering companies...\n")
    graph.invoke(
        {"query": query, "num_companies": num_companies, "messages": [], "companies_enriched": []},
        config,
    )
    # Graph paused at review_discover — print results
    review_discover({})

    if not _prompt("Press Enter to enrich, or 'q' to quit: "):
        return

    # Step 2: Resume — runs fan_out → enrich (per company) → pauses at review_enrich
    print("\nStep 2: Enriching companies...\n")
    graph.invoke(None, config)
    # Graph paused at review_enrich — print results
    review_enrich(graph.get_state(config).values)

    if not _prompt("Press Enter to summarize, or 'q' to quit: "):
        return

    # Step 3: Resume — runs summarize → END
    print("\nStep 3: Summary\n")
    graph.invoke(None, config)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  uv run python -m src.agent.build 'Electric Vehicles' 3")
        print("  uv run python -m src.agent.build clear")
        print("  uv run python -m src.agent.build stats")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "clear":
        clear_db()
    elif cmd == "stats":
        summarize_node({})
    elif cmd == "enrich":
        run_enrich_thin()
    elif cmd == "validate":
        run_validate()
    elif cmd == "annotate":
        run_annotate()
    else:
        query = cmd
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        run_build(query, n)
