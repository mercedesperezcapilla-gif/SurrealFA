"""
News Ingestion Agent — decomposes a news article and updates the knowledge graph.

Takes a URL or raw text, extracts supply chain entities and relationships,
validates new entities (yfinance for companies, whitelist for commodities/technologies),
validates relationships with LLM, annotates edges, and tracks all changes.

Pipeline: Fetch → Extract → Validate Entities → Create Nodes → Validate Relationships → Insert Edges → Annotate

Run:
  cd hackathon
  uv run python -m news_ingest "https://reuters.com/..."
  uv run python -m news_ingest --text "TSMC announced a new fab in Arizona..."
"""

import json
import os
import sys

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from src.graph import db as graph_db
from src.graph.builder import GraphBuilder

load_dotenv()

_builder = GraphBuilder()

# ── Whitelists (same as src/agent/tools.py) ──────────────────────────────────

ALLOWED_COMMODITIES = {
    "lithium", "cobalt", "nickel", "copper", "steel", "aluminum", "iron ore",
    "semiconductors", "rare earths", "natural gas", "crude oil", "silicon",
    "graphite", "manganese", "platinum", "palladium", "rubber", "glass",
    "polyethylene", "polypropylene", "cotton", "wheat", "corn", "soybeans",
    "timber", "uranium", "zinc", "tin", "gold", "silver",
}

ALLOWED_TECHNOLOGIES = {
    "lithium-ion battery", "solid-state battery", "autonomous driving",
    "solar panel", "wind turbine", "5g", "cloud computing", "ai/ml",
    "robotics", "lidar", "electric motor", "fuel cell", "hydrogen storage",
    "semiconductor fabrication", "quantum computing", "blockchain",
    "3d printing", "gene editing", "mrna", "carbon capture",
}

ALLOWED_RELATIONSHIPS = {
    "operates_in", "supplies_to", "complement_of",
    "substitute_for", "subsidiary_of", "uses_technology", "invested_in",
    "uses_input", "demand_driver", "affected_by_policy", "competes_with",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _fetch_article(url: str) -> str:
    """Fetch article content from a URL using Tavily extract."""
    from src.connectors.tavily_connector import _get_client
    client = _get_client()
    result = client.extract(urls=[url])
    if result and result.get("results"):
        return result["results"][0].get("raw_content", "")
    return ""


def _flatten(result) -> list[dict]:
    """Flatten SurrealDB query results into a flat list of dicts."""
    if not result:
        return []
    rows = []
    for item in (result if isinstance(result, list) else [result]):
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list):
            rows.extend(r for r in item if isinstance(r, dict))
    return rows


def _get_existing_entities() -> dict:
    """Get all existing entity names from the graph for dedup."""
    def flat(lst):
        out = []
        for item in lst:
            if isinstance(item, list):
                out.extend(i for i in item if isinstance(i, str))
            elif isinstance(item, str):
                out.append(item)
        return out

    companies = [r.get("name", "") for r in
                 _flatten(graph_db.query("SELECT name FROM company"))
                 if isinstance(r, dict)]
    commodities = [r.get("name", "") for r in
                   _flatten(graph_db.query("SELECT name FROM commodity"))
                   if isinstance(r, dict)]
    technologies = [r.get("name", "") for r in
                    _flatten(graph_db.query("SELECT name FROM technology"))
                    if isinstance(r, dict)]
    industries = [r.get("name", "") for r in
                  _flatten(graph_db.query("SELECT name FROM industry"))
                  if isinstance(r, dict)]
    return {
        "companies": flat(companies),
        "commodities": flat(commodities),
        "technologies": flat(technologies),
        "industries": flat(industries),
    }


# ── Entity Validation ────────────────────────────────────────────────────────

def _validate_new_entities(extraction: dict, existing: dict) -> tuple[list[dict], list[dict], list[dict], list[str], list[str]]:
    """
    Validate proposed new entities.
    - Companies: verified via yfinance ticker lookup
    - Commodities: checked against whitelist
    - Technologies: checked against whitelist

    Returns:
        (valid_companies, valid_commodities, valid_technologies, changes, rejected)
    """
    from src.connectors.yfinance_connector import get_company_info, get_company_by_name

    changes = []
    rejected = []
    existing_company_names = {n.lower() for n in existing["companies"]}
    existing_commodity_names = {n.lower() for n in existing["commodities"]}
    existing_tech_names = {n.lower() for n in existing["technologies"]}

    # Validate new companies via yfinance
    valid_companies = []
    for company in extraction.get("new_companies", []):
        name = company.get("name", "")
        ticker = company.get("ticker", "")
        if not name:
            continue
        if name.lower() in existing_company_names:
            print(f"  skip: company '{name}' already in graph")
            continue

        # Try ticker first, then name search
        yf_data = None
        if ticker:
            yf_data = get_company_info(ticker)
        if not yf_data:
            yf_data = get_company_by_name(name)

        if yf_data and yf_data.get("name"):
            valid_companies.append(yf_data)
            print(f"  VERIFIED: {yf_data['name']} ({yf_data.get('ticker', '?')}) via yfinance")
        else:
            rejected.append(f"New company: **{name}** ({ticker}) — not found on Yahoo Finance")
            print(f"  REJECTED: company '{name}' ({ticker}) not found on yfinance")

    # Validate new commodities against whitelist
    valid_commodities = []
    for commodity in extraction.get("new_commodities", []):
        name = commodity if isinstance(commodity, str) else commodity.get("name", "")
        name_lower = name.lower().strip()
        if not name_lower:
            continue
        if name_lower in existing_commodity_names:
            print(f"  skip: commodity '{name_lower}' already in graph")
            continue
        if name_lower in ALLOWED_COMMODITIES:
            valid_commodities.append(name_lower)
            print(f"  VERIFIED: commodity '{name_lower}' (on whitelist)")
        else:
            rejected.append(f"New commodity: **{name}** — not on allowed commodities list")
            print(f"  REJECTED: commodity '{name}' not on whitelist")

    # Validate new technologies against whitelist
    valid_technologies = []
    for tech in extraction.get("new_technologies", []):
        name = tech if isinstance(tech, str) else tech.get("name", "")
        name_lower = name.lower().strip()
        if not name_lower:
            continue
        if name_lower in existing_tech_names:
            print(f"  skip: technology '{name_lower}' already in graph")
            continue
        if name_lower in ALLOWED_TECHNOLOGIES:
            valid_technologies.append(name_lower)
            print(f"  VERIFIED: technology '{name_lower}' (on whitelist)")
        else:
            rejected.append(f"New technology: **{name}** — not on allowed technologies list")
            print(f"  REJECTED: technology '{name}' not on whitelist")

    return valid_companies, valid_commodities, valid_technologies, changes, rejected


# ── Relationship Validation ──────────────────────────────────────────────────

def _validate_relationships(llm, candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Validate extracted relationships using LLM + company descriptions.
    Returns (valid_rels, rejected_rels).
    """
    if not candidates:
        return [], []

    # Get company descriptions for validation context
    companies = _flatten(graph_db.query("SELECT name, description FROM company"))
    desc_text = ""
    for c in companies:
        name = c.get("name", "")
        desc = c.get("description", "")
        if desc:
            desc_text += f"\n{name}:\n{desc[:300]}\n"

    # Build edges text for validation
    edges_text = ""
    for i, rel in enumerate(candidates):
        edges_text += f"{i+1}. {rel['from_name']} -[{rel['relationship']}]-> {rel['to_name']} (reason: {rel.get('reason', 'n/a')})\n"

    response = llm.invoke([
        SystemMessage(content=f"""You are a data quality validator for a financial knowledge graph.

Review these relationships extracted from a news article and decide which are VALID and which are BOGUS.
A relationship is BOGUS if:
- The company description does NOT support this relationship
- The relationship is factually wrong (e.g. a software company using lithium as raw material)
- The relationship confuses the company with a different entity
- The relationship type doesn't make sense (e.g. a commodity "supplies_to" a company)

For each relationship, respond with EXACTLY one line:
VALID: <number>. reason
BOGUS: <number>. reason

Company descriptions for reference:
{desc_text}

Relationships to validate:
{edges_text}"""),
        HumanMessage(content="Validate each relationship. Return one line per relationship."),
    ])

    # Parse validation results
    bogus_indices = set()
    bogus_reasons = {}

    for line in response.content.strip().split("\n"):
        line = line.strip()
        if line.startswith("BOGUS:"):
            try:
                num = int(line.split(".")[0].replace("BOGUS:", "").strip())
                bogus_indices.add(num)
                bogus_reasons[num] = line.split(".", 1)[1].strip() if "." in line else ""
            except (ValueError, IndexError):
                pass

    valid = []
    rejected = []
    for i, rel in enumerate(candidates):
        idx = i + 1
        if idx in bogus_indices:
            rel["reject_reason"] = bogus_reasons.get(idx, "Failed validation")
            rejected.append(rel)
        else:
            valid.append(rel)

    return valid, rejected


# ── Edge Annotation ──────────────────────────────────────────────────────────

def _annotate_new_edges(llm, new_edges: list[dict]) -> list[dict]:
    """
    Annotate newly added edges with cost_sensitivity and criticality using LLM.
    Only annotates uses_input and supplies_to edges.
    """
    annotatable = [e for e in new_edges if e.get("relationship") in ("uses_input", "supplies_to")]
    if not annotatable:
        return []

    companies = _flatten(graph_db.query(
        "SELECT name, ticker, market_cap, revenue, description FROM company ORDER BY name"
    ))
    company_data = ""
    for c in companies:
        name = c.get("name", "")
        desc = (c.get("description") or "")[:200]
        company_data += (
            f"\n{name} ({c.get('ticker', '?')}): "
            f"revenue=${c.get('revenue', 0) or 0:,.0f}\n"
            f"  {desc}\n"
        )

    edges_text = ""
    for e in annotatable:
        edges_text += f"{e['from_name']} -> {e['relationship']} -> {e['to_name']}\n"

    response = llm.invoke([
        SystemMessage(content=f"""You are a financial analyst annotating a supply chain knowledge graph.

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

Respond with EXACTLY one line per relationship:
EDGE: src -> rel -> dst | cost_sensitivity=X.X | criticality=LEVEL

Company data:
{company_data}

Relationships to annotate:
{edges_text}"""),
        HumanMessage(content="Annotate each relationship."),
    ])

    annotations = []
    for line in response.content.strip().split("\n"):
        line = line.strip()
        if "|" not in line:
            continue
        line = line.replace("EDGE:", "").strip()
        try:
            parts = line.split("|")
            edge_part = parts[0].strip()
            cs_part = [p for p in parts if "cost_sensitivity" in p][0]
            cr_part = [p for p in parts if "criticality" in p][0]
            cost_sens = float(cs_part.split("=")[1].strip())
            criticality = cr_part.split("=")[1].strip().lower()

            for e in annotatable:
                from_name = e["from_name"]
                to_name = e["to_name"]
                rel_type = e["relationship"]
                if from_name in edge_part and to_name in edge_part:
                    from_clean = graph_db._clean_id(from_name)
                    to_clean = graph_db._clean_id(to_name)
                    rows = _flatten(graph_db.query(
                        f"SELECT id FROM {rel_type} WHERE in = {e['from_type']}:`{from_clean}` AND out = {e['to_type']}:`{to_clean}` LIMIT 1"
                    ))
                    if rows:
                        eid = rows[0].get("id")
                        graph_db.query(
                            f"UPDATE {eid} SET cost_sensitivity = $cs, criticality = $cr",
                            {"cs": cost_sens, "cr": criticality},
                        )
                        annotations.append({
                            "edge": f"{from_name} -[{rel_type}]-> {to_name}",
                            "cost_sensitivity": cost_sens,
                            "criticality": criticality,
                        })
                    break
        except Exception:
            continue

    return annotations


# ── Main Pipeline ────────────────────────────────────────────────────────────

def ingest_news(url: str | None = None, text: str | None = None) -> dict:
    """
    Decompose a news article and update the knowledge graph.

    Pipeline:
        1. Fetch article content
        2. LLM extracts entities + relationships
        3. Validate new entities (yfinance / whitelist)
        4. Create validated new nodes
        5. Validate relationships (LLM)
        6. Insert validated edges
        7. Annotate edges (cost_sensitivity / criticality)

    Returns:
        {
            "summary": str,
            "changes": list[str],       # What was added (nodes + edges)
            "rejected": list[str],      # What failed validation
            "annotations": list[dict],  # Edge annotations applied
            "graph_diff": dict,         # Before/after graph stats
        }
    """
    # Step 0: Snapshot graph before changes
    stats_before = graph_db.graph_stats()

    # Step 1: Get article content
    if url and not text:
        print(f"[1/7] FETCHING article from {url}...")
        text = _fetch_article(url)
        if not text:
            return {"summary": "Could not fetch article content.", "changes": [],
                    "rejected": [], "annotations": [], "graph_diff": {}}

    if not text:
        return {"summary": "No article content provided.", "changes": [],
                "rejected": [], "annotations": [], "graph_diff": {}}

    article_text = text[:6000]

    # Step 2: Extract entities + relationships with LLM
    print("[2/7] ANALYZING article with LLM...")
    existing = _get_existing_entities()

    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=f"""You are a supply chain analyst. You read news articles and extract
structured supply chain information to update a knowledge graph.

EXISTING ENTITIES IN THE GRAPH (reference these by exact name for relationships):
Companies: {json.dumps(existing['companies'])}
Commodities: {json.dumps(existing['commodities'])}
Technologies: {json.dumps(existing['technologies'])}
Industries: {json.dumps(existing['industries'])}

ALLOWED COMMODITIES (only use these exact names, lowercase):
{', '.join(sorted(ALLOWED_COMMODITIES))}

ALLOWED TECHNOLOGIES (only use these exact names, lowercase):
{', '.join(sorted(ALLOWED_TECHNOLOGIES))}

ALLOWED RELATIONSHIP TYPES:
supplies_to (company → company), uses_input (company → commodity),
uses_technology (company → technology), competes_with (company → company),
operates_in (company → industry), affected_by_policy (company → policy)

TASK: Read the article and extract:
1. A 2-3 sentence summary of the article's supply chain relevance
2. NEW COMPANIES mentioned that are NOT already in the graph (include stock ticker if known)
3. NEW COMMODITIES mentioned that are NOT already in the graph (must be from allowed list)
4. NEW TECHNOLOGIES mentioned that are NOT already in the graph (must be from allowed list)
5. Relationships — can reference EXISTING entities OR new ones you're proposing
6. Events and policy changes

Return JSON:
{{
  "summary": "2-3 sentence summary",
  "new_companies": [
    {{
      "name": "full company name",
      "ticker": "STOCK_TICKER",
      "reason": "why this company is relevant from the article"
    }}
  ],
  "new_commodities": ["commodity_name"],
  "new_technologies": ["technology_name"],
  "new_relationships": [
    {{
      "from_name": "exact entity name (existing or newly proposed)",
      "from_type": "company|commodity|technology|event|policy",
      "relationship": "supplies_to|uses_input|uses_technology|competes_with|operates_in|affected_by_policy",
      "to_name": "exact entity name",
      "to_type": "company|commodity|technology|industry|policy",
      "properties": {{"cost_sensitivity": 0.8, "criticality": "high"}},
      "reason": "why this relationship exists based on the article"
    }}
  ],
  "new_events": [
    {{
      "name": "short event name",
      "event_type": "geopolitical|natural_disaster|trade_war|regulatory|financial|supply_disruption",
      "description": "what happened"
    }}
  ],
  "new_policies": [
    {{
      "name": "policy name",
      "policy_type": "subsidy|tariff|regulation|tax_credit|ban",
      "region": "country or region",
      "description": "what the policy does"
    }}
  ]
}}

IMPORTANT:
- For existing entities, match names EXACTLY as they appear in the lists above
- For new companies, provide the stock ticker so we can verify via Yahoo Finance
- For new commodities/technologies, only use names from the ALLOWED lists
- Only extract information clearly stated or strongly implied by the article
- Return ONLY valid JSON, no markdown"""),
        HumanMessage(content=f"Analyze this article:\n\n{article_text}"),
    ])

    # Parse LLM output
    try:
        extraction = json.loads(response.content)
    except json.JSONDecodeError:
        content = response.content
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            extraction = json.loads(content[start:end])
        else:
            return {"summary": "Failed to parse article.", "changes": [],
                    "rejected": [], "annotations": [], "graph_diff": {}}

    changes = []
    rejected_list = []

    # Step 3: Validate new entities
    print("[3/7] VALIDATING new entities...")
    valid_companies, valid_commodities, valid_technologies, _, entity_rejected = \
        _validate_new_entities(extraction, existing)
    rejected_list.extend(entity_rejected)

    # Step 4: Create validated new nodes
    print("[4/7] CREATING new nodes...")
    for yf_data in valid_companies:
        company_id = _builder.ingest_yfinance_company(yf_data)
        name = yf_data.get("name", "")
        ticker = yf_data.get("ticker", "")
        industry = yf_data.get("industry", "")
        changes.append(f"Added company: **{name}** ({ticker})")
        if industry:
            changes.append(f"Added industry: **{industry}** + linked {name}")
        print(f"  + company: {name} ({ticker})")

    for commodity in valid_commodities:
        _builder.add_commodity(commodity)
        changes.append(f"Added commodity: **{commodity}**")
        print(f"  + commodity: {commodity}")

    for tech in valid_technologies:
        _builder.add_technology(tech)
        changes.append(f"Added technology: **{tech}**")
        print(f"  + technology: {tech}")

    # Add events
    for event in extraction.get("new_events", []):
        name = event.get("name", "")
        if name:
            _builder.add_event(name, {
                "event_type": event.get("event_type"),
                "description": event.get("description"),
            })
            changes.append(f"Added event: **{name}** ({event.get('event_type', '')})")
            print(f"  + event: {name}")

    # Add policies
    for policy in extraction.get("new_policies", []):
        name = policy.get("name", "")
        if name:
            _builder.add_policy(name, {
                "policy_type": policy.get("policy_type"),
                "region": policy.get("region"),
                "description": policy.get("description"),
            })
            changes.append(f"Added policy: **{name}** ({policy.get('policy_type', '')})")
            print(f"  + policy: {name}")

    # Step 5: Validate relationships
    print("[5/7] VALIDATING relationships...")

    # Build name lookup including newly added companies (use yfinance full name)
    new_company_names = {yf.get("name", "").lower() for yf in valid_companies}

    candidates = []
    for rel in extraction.get("new_relationships", []):
        from_name = rel.get("from_name", "")
        to_name = rel.get("to_name", "")
        rel_type = rel.get("relationship", "")
        from_type = rel.get("from_type", "company")
        to_type = rel.get("to_type", "company")

        if not (from_name and to_name and rel_type):
            continue

        if rel_type not in ALLOWED_RELATIONSHIPS:
            rejected_list.append(f"**{from_name}** -[{rel_type}]-> **{to_name}** — invalid relationship type")
            print(f"  skip: invalid relationship type '{rel_type}'")
            continue

        # Check both endpoints exist in graph (including newly added ones)
        from_node = graph_db.find_node(from_type, from_name)
        to_node = graph_db.find_node(to_type, to_name)

        if not from_node:
            print(f"  skip: {from_type} '{from_name}' not in graph")
            rejected_list.append(f"**{from_name}** -[{rel_type}]-> **{to_name}** — '{from_name}' not in graph")
            continue
        if not to_node:
            print(f"  skip: {to_type} '{to_name}' not in graph")
            rejected_list.append(f"**{from_name}** -[{rel_type}]-> **{to_name}** — '{to_name}' not in graph")
            continue

        candidates.append(rel)

    # LLM validation of candidate relationships
    valid_rels, bogus_rels = _validate_relationships(llm, candidates)

    for rel in bogus_rels:
        reason = rel.get("reject_reason", "Failed validation")
        rejected_list.append(f"**{rel['from_name']}** -[{rel['relationship']}]-> **{rel['to_name']}** — {reason}")
        print(f"  REJECTED: {rel['from_name']} -[{rel['relationship']}]-> {rel['to_name']}")

    print(f"  Validation: {len(valid_rels)} valid, {len(bogus_rels)} rejected")

    # Step 6: Insert validated edges
    print("[6/7] INSERTING validated edges...")
    inserted_edges = []
    for rel in valid_rels:
        from_name = rel.get("from_name", "")
        to_name = rel.get("to_name", "")
        rel_type = rel.get("relationship", "")
        from_type = rel.get("from_type", "company")
        to_type = rel.get("to_type", "company")

        props = rel.get("properties")
        graph_db.create_relationship(from_type, from_name, rel_type, to_type, to_name, props)
        reason = rel.get("reason", "")
        changes.append(f"**{from_name}** -[{rel_type}]-> **{to_name}** ({reason})")
        inserted_edges.append(rel)
        print(f"  + {from_name} -[{rel_type}]-> {to_name}")

    # Step 7: Annotate new edges
    print("[7/7] ANNOTATING new edges...")
    annotations = _annotate_new_edges(llm, inserted_edges)
    for a in annotations:
        print(f"  annotated: {a['edge']} cs={a['cost_sensitivity']:.1f} crit={a['criticality']}")

    # Snapshot graph after changes
    stats_after = graph_db.graph_stats()
    graph_diff = {}
    for key in set(list(stats_before.keys()) + list(stats_after.keys())):
        before_val = stats_before.get(key, 0)
        after_val = stats_after.get(key, 0)
        if after_val != before_val:
            graph_diff[key] = {"before": before_val, "after": after_val, "delta": after_val - before_val}

    summary = extraction.get("summary", "Article analyzed.")
    print(f"\n  Summary: {summary}")
    print(f"  Changes: {len(changes)}, Rejected: {len(rejected_list)}, Annotations: {len(annotations)}")

    return {
        "summary": summary,
        "changes": changes,
        "rejected": rejected_list,
        "annotations": annotations,
        "graph_diff": graph_diff,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print('  uv run python -m news_ingest "https://reuters.com/..."')
        print('  uv run python -m news_ingest --text "Article content here..."')
        sys.exit(1)

    if sys.argv[1] == "--text":
        result = ingest_news(text=" ".join(sys.argv[2:]))
    else:
        result = ingest_news(url=sys.argv[1])

    print(f"\nSummary: {result['summary']}")
    print(f"Changes ({len(result['changes'])}):")
    for c in result["changes"]:
        print(f"  - {c}")
    if result["rejected"]:
        print(f"Rejected ({len(result['rejected'])}):")
        for r in result["rejected"]:
            print(f"  - {r}")
