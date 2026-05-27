# SurrealFA

**Ask what happens if X. Get the consequences nobody's thinking about.**

A financial knowledge graph that traces economic shockwaves through supply chains, revealing second and third-order effects that analysts typically miss — and that spreadsheets can't find.

---

## The problem

Traditional analysis looks at sectors in isolation. A copper price spike affects copper miners. End of analysis.

Reality: copper flows into printed circuit boards, into electric motors, into washing machines, wind turbines, and smartphones. A 20% copper shock ripples through 37 industries across three hops. Analysts miss this. SurrealFA doesn't.

---

## What it finds

**"TSMC goes offline — what breaks?"**
→ 12 directly dependent industries. 17 companies in immediate trouble. Traced automatically.

**"What do a wine bottle and a smartphone have in common?"**
→ They share 3 industries: Aluminium, Cobalt, Glass. A disruption to either hits both your phone and your wine.

**"How many steps from a washing machine to a neodymium mine?"**
→ 4 hops: Washing machine → Electric Motor → Neodymium Magnet → Neodymium (Inner Mongolia)

**"A bearing factory catches fire — who cares?"**
→ 7 direct industries, 8 cascade, 39 companies affected. Bearings connect bicycles, washing machines, and wind turbines.

**"Copper prices double — what gets more expensive?"**
→ 37 industries affected across 3 hops: Copper → PCB → Semiconductor Fab → Smartphone

---

## The graph

Built from 7 industry trees walked to full depth, then mapped to real companies:

| | |
|--|--|
| **Industry nodes** | 428 |
| **Supply chain edges** | 785 (uses_input relationships) |
| **Companies mapped** | 1,165 |
| **Company → Industry edges** | 3,231 |
| **Demo queries** | 10 — all working |

Key pressure points (most connected industry nodes): Steel (17 dependents), Aluminium (15), Copper (13), Semiconductor Fabrication (12), PCB (10).

---

## How it works

**Graph Engine** — agents walk Wikipedia link trees to build supply chain relationships: what does X use to make itself? Each hop discovers new industries and merges them into the existing graph.

**Shock Propagation** — query a hypothetical scenario and traverse the graph to find all affected industries and companies, hop by hop.

**Polymarket Integration** — real-world probability data weights scenarios so analysis is probabilistic, not theoretical.

---

## Architecture

```
SurrealFA/
├── hackathon/          # geo enrichment, news ingestion, shock agent, frontend UI
│   ├── src/            # agents, connectors (FMP, SEC, Tavily, Wikidata, yfinance)
│   ├── app.py          # main application
│   ├── geo_enrich.py   # geographic enrichment pipeline
│   ├── news_ingest.py  # news ingestion
│   └── shock_agent.py  # shock propagation agent
│
└── beary/              # Polymarket connector, graph queries, shock propagation
    ├── src/            # agent, connectors (Polymarket, Wikidata, yfinance)
    ├── demo_queries.py # 10 working demo queries
    └── docs/           # architecture documentation
```

---

## Tech stack

| | |
|--|--|
| **SurrealDB** | Unified graph, document, and vector database — the query layer that makes multi-hop traversals possible |
| **LangGraph / LangChain** | Agent orchestration |
| **Python 3.13** with `uv` | Runtime |
| **Tavily** | Real-time web search for gap-filling |
| **Polymarket** | Probability-weighted scenario analysis |
| **yfinance / Wikidata / Wikipedia** | Company and industry data sources |

---

## Run the demo queries

```bash
git clone https://github.com/mercedesperezcapilla-gif/SurrealFA
cd SurrealFA/beary
pip install -r requirements.txt
python demo_queries.py
```

Queries include: shock propagation, surprising connections, hub analysis, reverse shock, supply chain depth, conglomerate mapping, cross-sector contagion, crude-to-cure, global trade shock, and glass bottleneck.

---

## Built at SurrealDB Hackathon 2026

Three people who met at the hackathon, working across two codebases, integrated in 48 hours.

| | |
|--|--|
| **[sparitosh07](https://github.com/sparitosh07)** | Geo enrichment, news ingestion, shock agent, frontend UI |
| **[0xbeary](https://github.com/0xbeary)** | Polymarket connector, graph queries, shock propagation engine |
| **[mercedesperezcapilla-gif](https://github.com/mercedesperezcapilla-gif)** | Project integration, graph architecture, documentation |

Original repos: [sparitosh07/SurrealFAHackathon](https://github.com/sparitosh07/SurrealFAHackathon) · [0xbeary/surreal-hackathon](https://github.com/0xbeary/surreal-hackathon)
