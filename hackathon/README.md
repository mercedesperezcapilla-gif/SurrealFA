# Global Shock Simulator

> Supply chain disruption → knowledge graph traversal → stock impact report

Built with **LangGraph** + **SurrealDB** for the LangChain × SurrealDB London Hackathon (March 2026).

---

## What it does

You describe a global shock event in plain English. The agent:

1. **Parses** the event — extracts the affected supplier and severity
2. **Explores** the supply chain knowledge graph — LLM writes its own SurrealQL queries
3. **Calculates** impact scores for downstream companies and stocks
4. **Generates** an analyst-style report

```
"TSMC production drops 40% due to earthquake in Taiwan"
         ↓
[parse]  supplier=tsmc, severity=0.4
         ↓
[graph]  LLM writes SurrealQL → TSMC → semiconductors → GPU → NVIDIA → NVDA
         ↓
[score]  NVDA: 0.35 → MEDIUM risk
         ↓
[report] 3-paragraph analyst report
```

---

## Architecture

### Knowledge graph (SurrealDB)

```
company:tsmc ──[PRODUCES]──▶ resource:semiconductors
                                      │
                                 [USED_IN] (tsmc_share: 0.92)
                                      │
                                      ▼
company:nvidia ──[DEPENDS_ON]──▶ component:gpu  (dep_strength: 0.95)
      │
 [LISTED_AS]
      │
      ▼
stock:nvda
```

Node types: `company`, `resource`, `component`, `stock`
Edge types: `PRODUCES`, `USED_IN`, `DEPENDS_ON`, `LISTED_AS`

### Agent pipeline (LangGraph)

```
parse_shock → traverse_graph → calculate_impact → generate_report
```

| Node | What it does |
|---|---|
| `parse_shock` | LLM extracts `supplier_id` and `severity` from free text |
| `traverse_graph` | LLM writes SurrealQL queries via `query_graph` tool, explores the graph autonomously |
| `calculate_impact` | `score = severity × tsmc_share × dep_strength` → HIGH / MEDIUM / LOW |
| `generate_report` | LLM writes a 3-paragraph analyst report from graph data |

Each run is persisted with a `thread_id` — scenarios can be resumed and compared.

LangSmith traces every step automatically when `LANGCHAIN_TRACING_V2=true`.

---

## Setup

### 1. Install SurrealDB

```bash
brew install surrealdb/tap/surreal
```

### 2. Start SurrealDB

```bash
surreal start --log trace --user root --pass root memory
```

Leave this running in a separate terminal.

### 3. Install Python dependencies

```bash
uv sync
```

### 4. Configure environment

Fill in `.env`:

```
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_API_VERSION=...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...          # from smith.langchain.com

# SurrealDB Cloud (app.surrealdb.com) or local
SURREALDB_URL=wss://your-instance.aws.surrealdb.com
SURREALDB_USER=root
SURREALDB_PASS=your-password
SURREALDB_NS=hackathon
SURREALDB_DB=shock_simulator
```

For local development: `SURREALDB_URL=ws://localhost:8000/rpc`

### 5. Seed the graph

```bash
python seed_graph.py
```

This creates all nodes and edges in SurrealDB and verifies the 4-hop traversal.

### 6. Run the agent

```bash
python shock_agent.py
```

---

## Visualise the graph

Open [Surrealist](https://surrealist.app) and connect:

| Field | Value |
|---|---|
| Host | `http://localhost:8000` |
| Username | `root` |
| Password | `root` |
| Namespace | `hackathon` |
| Database | `shock_simulator` |

Use the **Designer** tab to see the schema, or run in the **Query** tab:

```sql
SELECT
    name,
    ->PRODUCES->resource.name AS produces,
    ->PRODUCES->resource->USED_IN->component.name AS components,
    ->PRODUCES->resource->USED_IN->component<-DEPENDS_ON<-company.name AS companies_at_risk,
    ->PRODUCES->resource->USED_IN->component<-DEPENDS_ON<-company->LISTED_AS->stock.ticker AS stocks
FROM company:tsmc;
```

---

## Extending the graph

Add more nodes to `seed_graph.py` — the agent requires no code changes:

```python
# Apple supply chain
("company", "apple", {"name": "Apple Inc", "tsmc_dependency": 0.90}),
("component", "application_processor", {"name": "Application Processor"}),
...
("company", "apple", "DEPENDS_ON", "component", "application_processor", {"dependency_strength": 0.90}),
("company", "apple", "LISTED_AS",  "stock", "aapl", {}),
```

The LLM discovers and traverses new paths automatically.

---

## Judging criteria

| Criterion | Weight | How this project meets it |
|---|---|---|
| Structured Memory | 30% | Multi-hop knowledge graph in SurrealDB; edges carry dependency weights |
| Agent Workflow | 20% | LangGraph 4-node pipeline; LLM uses `query_graph` tool to write SurrealQL |
| Persistent State | 20% | Scenarios saved by `thread_id`, resumable across runs |
| Practical Use Case | 20% | Real-world supply chain and market risk intelligence |
| Observability | 10% | Full LangSmith traces for every agent step |

---

## Files

```
seed_graph.py   — seeds SurrealDB with the supply chain graph (run once)
shock_agent.py  — LangGraph agent (run to simulate a shock event)
```
