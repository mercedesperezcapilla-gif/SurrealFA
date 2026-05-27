"""
GraphBuilder — high-level helpers to add nodes and edges to SurrealDB.
Wraps db.py primitives with domain-specific logic.
"""

from src.graph import db


class GraphBuilder:

    # ── Node builders ─────────────────────────────────────────────────────────

    def add_company(self, data: dict) -> str:
        """Add/update a company node. Returns the record ID."""
        name = data.get("name", "")
        return db.upsert_node("company", name, {
            "name":        name,
            "ticker":      data.get("ticker"),
            "description": data.get("description"),
            "market_cap":  data.get("market_cap"),
            "revenue":     data.get("revenue"),
            "employees":   data.get("employees"),
            "hq_country":  data.get("hq_country"),
            "hq_city":     data.get("hq_city"),
            "website":     data.get("website"),
            "wikidata_id": data.get("wikidata_id"),
            "founded":     data.get("founded"),
            "source":      data.get("source", "agent"),
        })

    def add_industry(self, name: str, data: dict | None = None) -> str:
        props = {"name": name, "source": "agent"}
        if data:
            props.update(data)
        return db.upsert_node("industry", name, props)

    def add_technology(self, name: str, data: dict | None = None) -> str:
        props = {"name": name, "source": "agent"}
        if data:
            props.update(data)
        return db.upsert_node("technology", name, props)

    def add_commodity(self, name: str, data: dict | None = None) -> str:
        props = {"name": name, "source": "agent"}
        if data:
            props.update(data)
        return db.upsert_node("commodity", name, props)

    def add_policy(self, name: str, data: dict | None = None) -> str:
        props = {"name": name, "source": "agent"}
        if data:
            props.update(data)
        return db.upsert_node("policy", name, props)

    def add_event(self, name: str, data: dict | None = None) -> str:
        props = {"name": name, "source": "agent"}
        if data:
            props.update(data)
        return db.upsert_node("event", name, props)

    def add_region(self, name: str, data: dict | None = None) -> str:
        props = {"name": name, "source": "geo_enrich"}
        if data:
            props.update(data)
        return db.upsert_node("region", name, props)

    # ── Relationship builders ─────────────────────────────────────────────────

    def link_company_to_industry(self, company: str, industry: str, props: dict | None = None):
        db.create_relationship("company", company, "operates_in", "industry", industry, props)

    def link_competitors(self, company_a: str, company_b: str, props: dict | None = None):
        db.create_relationship("company", company_a, "competes_with", "company", company_b, props)

    def link_supply_chain(self, supplier: str, customer: str, props: dict | None = None):
        db.create_relationship("company", supplier, "supplies_to", "company", customer, props)

    def link_complements(self, company_a: str, company_b: str, props: dict | None = None):
        db.create_relationship("company", company_a, "complement_of", "company", company_b, props)

    def link_uses_technology(self, company: str, technology: str, props: dict | None = None):
        db.create_relationship("company", company, "uses_technology", "technology", technology, props)

    def link_uses_input(self, company: str, commodity: str, props: dict | None = None):
        db.create_relationship("company", company, "uses_input", "commodity", commodity, props)

    def link_event_to_industry(self, event: str, industry: str, props: dict | None = None):
        db.create_relationship("event", event, "demand_driver", "industry", industry, props)

    def link_policy_to_company(self, company: str, policy: str, props: dict | None = None):
        db.create_relationship("company", company, "affected_by_policy", "policy", policy, props)

    def link_commodity_to_region(self, commodity: str, region: str, props: dict | None = None):
        db.create_relationship("commodity", commodity, "produced_in", "region", region, props)

    # ── Bulk ingest ───────────────────────────────────────────────────────────

    def ingest_yfinance_company(self, yf_data: dict) -> str | None:
        """Create company node + industry link from yfinance data."""
        if not yf_data:
            return None
        company_id = self.add_company(yf_data)
        industry_name = yf_data.get("industry")
        if industry_name:
            self.add_industry(industry_name, {"sector": yf_data.get("sector")})
            self.link_company_to_industry(company_id, industry_name)
        return company_id

    def ingest_llm_extraction(self, extraction: dict):
        """
        Ingest LLM-extracted entities and relationships.
        Expected format:
        {
            "companies":     [{"name": ..., "description": ...}, ...],
            "industries":    ["name", ...],
            "technologies":  [{"name": ..., "maturity": ...}, ...],
            "commodities":   ["name", ...],
            "relationships": [
                {"from": "Tesla", "from_type": "company", "rel": "competes_with",
                 "to": "Rivian", "to_type": "company", "properties": {...}},
                ...
            ]
        }
        """
        for company in extraction.get("companies", []):
            if isinstance(company, str):
                company = {"name": company}
            self.add_company(company)

        for industry in extraction.get("industries", []):
            name = industry if isinstance(industry, str) else industry.get("name", "")
            if name:
                self.add_industry(name, industry if isinstance(industry, dict) else None)

        for tech in extraction.get("technologies", []):
            if isinstance(tech, str):
                tech = {"name": tech}
            self.add_technology(tech["name"], tech)

        for commodity in extraction.get("commodities", []):
            name = commodity if isinstance(commodity, str) else commodity.get("name", "")
            if name:
                self.add_commodity(name)

        for policy in extraction.get("policies", []):
            name = policy if isinstance(policy, str) else policy.get("name", "")
            if name:
                self.add_policy(name, policy if isinstance(policy, dict) else None)

        for rel in extraction.get("relationships", []):
            db.create_relationship(
                rel.get("from_type", "company"), rel["from"],
                rel["rel"],
                rel.get("to_type", "company"), rel["to"],
                rel.get("properties"),
            )
