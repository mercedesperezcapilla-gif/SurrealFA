# SurrealFA

A prototype that maps how financial shocks travel through a knowledge graph.

Built at the **LangChain × SurrealDB Hackathon in London**, 2026.

---

## The problem

Financial shocks don't move in straight lines — they travel through graphs.

Tensions with Iran spike → oil jumps overnight.

↳ Hop 1: Airlines and shipping — fuel costs surge  
↳ Hop 2: Aircraft maintenance contractors and logistics providers  
↳ Hop 3: A small aerospace component manufacturer loses half its orders

That third hop is where real risk hides. And where most tools stop.

---

## What it does

You describe a disruption in plain English — *"Iran tensions spike oil prices"*.

An AI agent traverses a knowledge graph of ~1,100 companies, generates graph queries dynamically, and produces an analyst-style report: which companies are affected, how severely, and why — including second and third-order cascades.

---

## Architecture

```
SurrealFA/
├── hackathon/          # geo enrichment, news ingestion, shock agent, frontend UI
│   ├── src/            # agents, connectors (FMP, SEC, Tavily, Wikidata, yfinance)
│   ├── app.py
│   ├── geo_enrich.py
│   ├── news_ingest.py
│   └── shock_agent.py
│
└── beary/              # Polymarket connector, graph queries, shock propagation
    ├── src/
    ├── demo_queries.py
    └── docs/
```

---

## Tech stack

- **SurrealDB** — unified graph, document, and vector database
- **LangGraph / LangChain** — agent orchestration
- **Python 3.13** with `uv`
- **Tavily** — real-time web search
- **Polymarket** — probability-weighted scenario analysis
- **yfinance / Wikidata / Wikipedia** — company and industry data

---

## Run the demo queries

```bash
git clone https://github.com/mercedesperezcapilla-gif/SurrealFA
cd SurrealFA/beary
pip install -r requirements.txt
python demo_queries.py
```

---

## Built by

Three people who met at the hackathon, working across two codebases, integrated in 48 hours.

| | |
|--|--|
| **[sparitosh07](https://github.com/sparitosh07)** | Geo enrichment, news ingestion, shock agent, UI |
| **[0xbeary](https://github.com/0xbeary)** | Polymarket connector, graph queries, shock propagation |
| **[mercedesperezcapilla-gif](https://github.com/mercedesperezcapilla-gif)** | Project integration, architecture, documentation |

Original repos: [sparitosh07/SurrealFAHackathon](https://github.com/sparitosh07/SurrealFAHackathon) · [0xbeary/surreal-hackathon](https://github.com/0xbeary/surreal-hackathon)
