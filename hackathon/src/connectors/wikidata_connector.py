"""
Wikidata SPARQL connector — structured knowledge about companies,
their relationships, products, and supply chains.
"""

import requests

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {
    "Accept": "application/sparql-results+json",
    "User-Agent": "SurrealFA/1.0 (hackathon project)",
}


def _sparql(query: str) -> list[dict]:
    """Run a SPARQL query and return the result bindings."""
    try:
        resp = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query, "format": "json"},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        bindings = resp.json()["results"]["bindings"]
        return [{k: v["value"] for k, v in row.items()} for row in bindings]
    except Exception:
        return []


def search_entity(name: str) -> list[dict]:
    """
    Search Wikidata for an entity by name.
    Returns list of {qid, label, description}.
    """
    try:
        resp = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "format": "json",
                "limit": 5,
            },
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        results = []
        for item in resp.json().get("search", []):
            results.append({
                "qid":         item["id"],
                "label":       item.get("label", ""),
                "description": item.get("description", ""),
                "url":         item.get("concepturi", ""),
            })
        return results
    except Exception:
        return []


def get_companies_in_industry(industry_name: str) -> list[dict]:
    """
    Find companies in an industry via Wikidata.
    Returns list of {name, qid, ticker, country}.
    """
    query = f"""
SELECT DISTINCT ?company ?companyLabel ?ticker ?country ?countryLabel WHERE {{
  ?industry ?label "{industry_name}"@en.
  ?company wdt:P31 wd:Q4830453;
           wdt:P452 ?industry.
  OPTIONAL {{ ?company wdt:P249 ?ticker. }}
  OPTIONAL {{ ?company wdt:P17 ?country. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT 30
"""
    rows = _sparql(query)
    return [
        {
            "qid":     r.get("company", "").split("/")[-1],
            "name":    r.get("companyLabel", ""),
            "ticker":  r.get("ticker", ""),
            "country": r.get("countryLabel", ""),
        }
        for r in rows if r.get("companyLabel")
    ]


def get_company_relationships(wikidata_id: str) -> dict:
    """
    Get structured relationships for a company from Wikidata.
    Returns parent, subsidiaries, products, industry, CEO.
    """
    qid = wikidata_id if wikidata_id.startswith("Q") else f"Q{wikidata_id}"
    query = f"""
SELECT ?rel ?relLabel ?target ?targetLabel WHERE {{
  VALUES (?rel ?target) {{
    (wdt:P749 wd:{qid})   # parent org → this company
    (wdt:P355 wd:{qid})   # subsidiary of this company
    (wdt:P452 wd:{qid})   # industry
    (wdt:P169 wd:{qid})   # CEO
    (wdt:P1056 wd:{qid})  # product
  }}
  OPTIONAL {{ ?rel rdfs:label ?relLabel. FILTER(LANG(?relLabel)="en") }}
  OPTIONAL {{ ?target rdfs:label ?targetLabel. FILTER(LANG(?targetLabel)="en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT 50
"""
    # Simpler direct query for the company
    query2 = f"""
SELECT ?parentLabel ?subsidiaryLabel ?industryLabel ?productLabel WHERE {{
  wd:{qid} wdt:P31 wd:Q4830453.
  OPTIONAL {{ wd:{qid} wdt:P749 ?parent. }}
  OPTIONAL {{ wd:{qid} wdt:P355 ?subsidiary. }}
  OPTIONAL {{ wd:{qid} wdt:P452 ?industry. }}
  OPTIONAL {{ wd:{qid} wdt:P1056 ?product. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT 30
"""
    rows = _sparql(query2)
    import re
    _is_qid = re.compile(r"^Q\d+$").match
    result: dict = {"parent": [], "subsidiaries": [], "industries": [], "products": []}
    for r in rows:
        for key, field in [("parent", "parentLabel"), ("subsidiaries", "subsidiaryLabel"),
                           ("industries", "industryLabel"), ("products", "productLabel")]:
            val = r.get(field, "")
            if val and not _is_qid(val):
                result[key].append(val)
    # Deduplicate
    for k in result:
        result[k] = list(set(result[k]))
    return result


def get_supply_chain(wikidata_id: str) -> dict:
    """
    Get supply chain data: what the company produces and uses as inputs.
    """
    qid = wikidata_id if wikidata_id.startswith("Q") else f"Q{wikidata_id}"
    query = f"""
SELECT ?productLabel ?materialLabel WHERE {{
  OPTIONAL {{ wd:{qid} wdt:P1056 ?product. }}
  OPTIONAL {{ wd:{qid} wdt:P2283 ?material. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT 20
"""
    import re
    _is_qid = re.compile(r"^Q\d+$").match
    rows = _sparql(query)
    products  = list({r["productLabel"]  for r in rows if r.get("productLabel")  and not _is_qid(r["productLabel"])})
    materials = list({r["materialLabel"] for r in rows if r.get("materialLabel") and not _is_qid(r["materialLabel"])})
    return {"produces": products, "uses": materials}
