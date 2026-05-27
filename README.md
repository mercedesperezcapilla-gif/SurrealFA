# SurrealFA

A financial analysis system that maps economic shockwaves through a knowledge graph to uncover second- and third-order effects analysts typically miss.

Ask what happens if X. Get the consequences nobody's thinking about.

Built with SurrealDB, LangGraph, and Python — originally developed at the SurrealDB Hackathon 2025.

---

## What it does

Rather than analysing sectors in isolation, SurrealFA maps how a shock — a copper price spike, a geopolitical event, a new carbon tariff — propagates across interconnected industries, supply chains, and commodities.

**Graph Engine** — agents continuously build and enrich a knowledge graph pulling from yfinance, Wikidata, Wikipedia, and news sources.

**Shock Propagation** — query a hypothetical scenario and trace the consequences through the graph, revealing non-obvious third-order impacts.

**Polymarket Integration** — real-world probability data weights scenarios so analysis is probabilistic, not just theoretical.

---

## Repository structure

```
SurrealFA/
├── hackathon/          # sparitosh07 — geo enrichment, news ingestion, shock agent, UI
│   ├── src/            # agent, connectors (FMP, SEC, Tavily, Wikidata, yfinance), graph, schema
│   ├── lib/            # vis.js, tom-select (frontend)
│   ├── app.py
│   ├── geo_enrich.py
│   ├── news_ingest.py
│   └── shock_agent.py
│
└── beary/              # 0xbeary — Polymarket connector, graph queries, shock propagation
    ├── src/            # agent, connectors (Polymarket, Wikidata, yfinance), graph, schema
    ├── docs/
    ├── demo_queries.py
    └── test_chain.py
```

---

## Tech stack

- **SurrealDB** — unified graph, document, and vector database
- **LangGraph / LangChain** — agent orchestration
- **Python 3.13** with `uv`
- **Tavily** — web search
- **Polymarket** — probability-weighted scenario analysis

---

## Sources

- [sparitosh07/SurrealFAHackathon](https://github.com/sparitosh07/SurrealFAHackathon)
- [0xbeary/surreal-hackathon](https://github.com/0xbeary/surreal-hackathon)
