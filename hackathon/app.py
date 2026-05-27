"""
Surreal FA — Supply Chain Shock Simulator UI.

Run:
  cd hackathon
  uv run streamlit run app.py
"""

import sys
from pathlib import Path

# Ensure hackathon/ is on the path so `src.*` and `shock_agent` imports work
_hackathon_dir = str(Path(__file__).resolve().parent)
if _hackathon_dir not in sys.path:
    sys.path.insert(0, _hackathon_dir)

import pandas as pd
import pydeck as pdk
import streamlit as st

from src.graph import db as graph_db

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="Surreal FA — Shock Simulator", layout="wide")

# ── Company coordinates (hardcoded for our 14 companies) ─────────────────────

COMPANY_COORDS = {
    "Tesla, Inc.": (37.39, -122.15),
    "NVIDIA Corporation": (37.37, -122.04),
    "Intel Corporation": (37.39, -121.96),
    "Microsoft Corporation": (47.64, -122.13),
    "Amazon.com, Inc.": (47.62, -122.34),
    "International Business Machines Corporation": (41.11, -73.72),
    "Micron Technology, Inc.": (43.62, -116.21),
    "DuPont de Nemours, Inc.": (39.77, -75.55),
    "Taiwan Semiconductor Manufacturing Company Limited": (24.77, 121.02),
    "BYD Company Limited": (22.55, 114.06),
    "NIO Inc.": (31.23, 121.47),
    "Contemporary Amperex Technology Co., Limited": (26.08, 119.30),
    "Panasonic Holdings Corporation": (34.69, 135.50),
    "Pylon Technologies Co., Ltd.": (31.30, 121.50),
}

# ── Shock presets ────────────────────────────────────────────────────────────

SHOCK_PRESETS = [
    {
        "name": "Taiwan Earthquake — TSMC Halts",
        "query": "TSMC production halts 40% due to earthquake in Taiwan",
        "lat": 23.5,
        "lng": 121.0,
    },
    {
        "name": "Chile Export Ban — Lithium Spike",
        "query": "Lithium prices spike 50% due to Chilean export ban",
        "lat": -33.4,
        "lng": -70.6,
    },
    {
        "name": "Semiconductor Fab Bottleneck",
        "query": "Semiconductor fabrication capacity reduced 30% globally",
        "lat": 24.0,
        "lng": 120.5,
    },
    {
        "name": "Cobalt Supply Disruption — DRC",
        "query": "Cobalt prices spike 60% due to DRC mining halt",
        "lat": -4.0,
        "lng": 22.0,
    },
    {
        "name": "Steel Tariffs — Global",
        "query": "Steel prices increase 40% due to global tariffs",
        "lat": 40.0,
        "lng": -74.0,
    },
]

# ── Helpers ──────────────────────────────────────────────────────────────────

RATING_COLORS = {
    "CRITICAL": [220, 20, 20, 200],
    "HIGH": [255, 120, 0, 200],
    "MODERATE": [255, 200, 0, 200],
    "LOW": [100, 200, 100, 200],
}


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


@st.cache_data(ttl=300)
def load_companies() -> pd.DataFrame:
    """Fetch companies from SurrealDB and merge with coordinates."""
    rows = _flatten(graph_db.query(
        "SELECT name, ticker, market_cap, revenue, hq_country FROM company ORDER BY name"
    ))
    records = []
    for r in rows:
        name = r.get("name", "")
        coords = COMPANY_COORDS.get(name)
        if coords:
            records.append({
                "name": name,
                "ticker": r.get("ticker", ""),
                "market_cap": r.get("market_cap") or 0,
                "revenue": r.get("revenue") or 0,
                "country": r.get("hq_country", ""),
                "lat": coords[0],
                "lng": coords[1],
                "color": [50, 120, 220, 180],
                "radius": max(40000, min(200000, (r.get("market_cap") or 0) / 1e10 * 5000)),
            })
    return pd.DataFrame(records)


def load_graph_stats() -> dict:
    return graph_db.graph_stats()


def run_simulation(query: str) -> dict:
    """Run the shock simulation and return state dict."""
    from shock_agent import run_shock
    # Suppress prints during streamlit run
    import io
    import contextlib
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        result = run_shock(query)
    return result


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Shock Simulator")
    st.caption("LangGraph + SurrealDB Knowledge Graph")

    st.divider()

    # Shock selection
    shock_names = [s["name"] for s in SHOCK_PRESETS] + ["Custom shock..."]
    selected = st.radio("Select a shock event:", shock_names, index=None)

    custom_query = ""
    if selected == "Custom shock...":
        custom_query = st.text_area(
            "Describe the shock:",
            placeholder="e.g. Copper prices spike 30% due to mining strikes",
            height=80,
        )

    # Determine the query
    shock_query = ""
    selected_preset = None
    if selected and selected != "Custom shock...":
        selected_preset = next(s for s in SHOCK_PRESETS if s["name"] == selected)
        shock_query = selected_preset["query"]
        st.info(f'"{shock_query}"')
    elif custom_query:
        shock_query = custom_query

    run_clicked = st.button(
        "Run Simulation",
        type="primary",
        disabled=not shock_query,
        use_container_width=True,
    )

    st.divider()

    # Graph stats
    with st.expander("Graph Stats"):
        stats = load_graph_stats()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Companies", stats.get("company", 0))
            st.metric("Industries", stats.get("industry", 0))
            st.metric("Commodities", stats.get("commodity", 0))
        with col2:
            st.metric("Technologies", stats.get("technology", 0))
            st.metric("Regions", stats.get("region", 0))
            st.metric("Supply Edges", stats.get("rel_supplies_to", 0))


# ── Run simulation ───────────────────────────────────────────────────────────

if run_clicked and shock_query:
    with st.spinner("Running shock simulation..."):
        result = run_simulation(shock_query)
    st.session_state["shock_result"] = result
    st.session_state["shock_query"] = shock_query
    st.session_state["selected_preset"] = selected_preset


# ── Main content ─────────────────────────────────────────────────────────────

companies_df = load_companies()
result = st.session_state.get("shock_result")
active_preset = st.session_state.get("selected_preset")

# Build map layers
layers = []

# Company markers — update colors if we have results
if result and result.get("impact_scores"):
    impact_lookup = {}
    for score in result["impact_scores"]:
        company = score.get("company", "")
        if company not in impact_lookup or score["impact_score"] > impact_lookup[company]["impact_score"]:
            impact_lookup[company] = score

    colored_records = []
    for _, row in companies_df.iterrows():
        record = row.to_dict()
        impact = impact_lookup.get(record["name"])
        if impact:
            record["color"] = RATING_COLORS.get(impact["rating"], [50, 120, 220, 180])
            record["radius"] = max(80000, record["radius"] * 1.5)
        colored_records.append(record)
    map_df = pd.DataFrame(colored_records)
else:
    map_df = companies_df

if not map_df.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=map_df,
        get_position=["lng", "lat"],
        get_radius="radius",
        get_fill_color="color",
        pickable=True,
        auto_highlight=True,
    ))

# Shock event markers (red dots)
shock_df = pd.DataFrame([
    {"lat": s["lat"], "lng": s["lng"], "name": s["name"]}
    for s in SHOCK_PRESETS
])
layers.append(pdk.Layer(
    "ScatterplotLayer",
    data=shock_df,
    get_position=["lng", "lat"],
    get_radius=60000,
    get_fill_color=[220, 40, 40, 160],
    get_line_color=[255, 255, 255, 200],
    line_width_min_pixels=2,
    stroked=True,
    pickable=True,
))

# Active shock highlight
if active_preset:
    highlight_df = pd.DataFrame([{
        "lat": active_preset["lat"],
        "lng": active_preset["lng"],
        "name": active_preset["name"],
    }])
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=highlight_df,
        get_position=["lng", "lat"],
        get_radius=150000,
        get_fill_color=[255, 0, 0, 80],
        pickable=False,
    ))

# Supply chain arcs (after simulation)
if result and result.get("impact_scores"):
    # Determine shock source location
    source_coords = None
    if active_preset:
        source_coords = (active_preset["lat"], active_preset["lng"])
    elif result.get("shocked_entity"):
        source_coords = COMPANY_COORDS.get(result["shocked_entity"])

    if source_coords:
        arc_records = []
        for s in result["impact_scores"]:
            target_coords = COMPANY_COORDS.get(s["company"])
            if target_coords:
                is_direct = s.get("hop") == 1
                arc_records.append({
                    "source_lat": source_coords[0],
                    "source_lng": source_coords[1],
                    "target_lat": target_coords[0],
                    "target_lng": target_coords[1],
                    "source_color": [220, 20, 20, 180] if is_direct else [255, 140, 0, 140],
                    "target_color": [220, 20, 20, 100] if is_direct else [255, 140, 0, 80],
                    "width": max(2, int((s.get("cost_sensitivity") or 0.5) * 8)),
                })
        if arc_records:
            layers.append(pdk.Layer(
                "ArcLayer",
                data=pd.DataFrame(arc_records),
                get_source_position=["source_lng", "source_lat"],
                get_target_position=["target_lng", "target_lat"],
                get_source_color="source_color",
                get_target_color="target_color",
                get_width="width",
            ))

# Production region markers (purple dots for commodity shocks)
if result and result.get("geo_concentration", {}).get("regions"):
    geo_regions = result["geo_concentration"]["regions"]
    region_records = []
    for r in geo_regions:
        lat = r.get("lat")
        lng = r.get("lng")
        if lat and lng:
            pct = r.get("pct_of_global_supply", 0)
            region_records.append({
                "lat": lat,
                "lng": lng,
                "name": f"{r.get('region', '?')} ({pct:.0%})",
                "radius": max(40000, int(pct * 500000)),
                "color": [180, 60, 220, 160],
            })
    if region_records:
        region_df = pd.DataFrame(region_records)
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=region_df,
            get_position=["lng", "lat"],
            get_radius="radius",
            get_fill_color="color",
            pickable=True,
            auto_highlight=True,
        ))
        # Arcs from production regions to affected companies
        if result.get("impact_scores"):
            supply_arcs = []
            for region in region_records:
                for s in result["impact_scores"][:5]:
                    target = COMPANY_COORDS.get(s["company"])
                    if target:
                        supply_arcs.append({
                            "source_lat": region["lat"],
                            "source_lng": region["lng"],
                            "target_lat": target[0],
                            "target_lng": target[1],
                            "source_color": [180, 60, 220, 120],
                            "target_color": [180, 60, 220, 60],
                            "width": 2,
                        })
            if supply_arcs:
                layers.append(pdk.Layer(
                    "ArcLayer",
                    data=pd.DataFrame(supply_arcs),
                    get_source_position=["source_lng", "source_lat"],
                    get_target_position=["target_lng", "target_lat"],
                    get_source_color="source_color",
                    get_target_color="target_color",
                    get_width="width",
                ))

# Render map
view_state = pdk.ViewState(latitude=25, longitude=50, zoom=1.5, pitch=0)
deck = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    tooltip={"text": "{name}\n{ticker}"},
    map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
)
st.pydeck_chart(deck, use_container_width=True, height=500)

# ── Results ──────────────────────────────────────────────────────────────────

if result and result.get("impact_scores"):
    st.divider()

    shock_query_display = st.session_state.get("shock_query", "")
    st.subheader(f"Shock: {shock_query_display}")

    # Summary metrics row
    scores = result["impact_scores"]
    critical = sum(1 for s in scores if s["rating"] == "CRITICAL")
    high = sum(1 for s in scores if s["rating"] == "HIGH")
    moderate = sum(1 for s in scores if s["rating"] == "MODERATE")
    low = sum(1 for s in scores if s["rating"] == "LOW")

    geo = result.get("geo_concentration", {})
    geo_score = geo.get("score", 0)
    geo_mult = geo.get("geo_multiplier", 1.0)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Critical", critical)
    c2.metric("High", high)
    c3.metric("Moderate", moderate)
    c4.metric("Low", low)
    if geo_score > 0:
        c5.metric("Geo Concentration", f"{geo_score:.2f}",
                  delta=f"{geo_mult:.2f}x", delta_color="inverse")
    else:
        c5.metric("Geo Concentration", "N/A")

    # ── Tabbed results ───────────────────────────────────────────────────────
    tab_impact, tab_geo, tab_report = st.tabs([
        "Impact Summary", "Geographic Risk", "Analyst Report",
    ])

    with tab_impact:
        table_data = []
        for s in scores:
            mc = s.get("market_cap")
            table_data.append({
                "Company": s.get("company", ""),
                "Ticker": s.get("ticker", ""),
                "Impact Score": f"{s['impact_score']:.3f}",
                "Rating": s["rating"],
                "Hop": "Direct" if s.get("hop") == 1 else "Cascade",
                "Market Cap": f"${mc / 1e9:.1f}B" if mc and mc > 0 else "—",
                "Criticality": s.get("criticality", "—"),
            })
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

    with tab_geo:
        if geo.get("regions"):
            st.markdown(f"**Concentration Score (HHI):** {geo_score:.3f} — "
                        f"Geographic multiplier: **{geo_mult:.2f}x**")
            st.caption("Higher HHI means production is concentrated in fewer countries, "
                       "amplifying shock impact due to limited alternative sources.")
            geo_table = []
            for r in geo["regions"]:
                pct = r.get("pct_of_global_supply", 0)
                geo_table.append({
                    "Country": r.get("region", "?"),
                    "% of Global Supply": f"{pct:.0%}" if pct else "—",
                    "Country Code": r.get("country_code", ""),
                })
            st.dataframe(pd.DataFrame(geo_table), use_container_width=True, hide_index=True)
        else:
            st.info("No geographic concentration data available for this shock type. "
                    "Geographic data is available for commodity shocks.")

    with tab_report:
        if result.get("report"):
            st.markdown(result["report"])
        else:
            st.info("No report generated.")

elif result is not None:
    st.info("No impacts found for this shock scenario in the current graph.")


# ── News Ingestion ───────────────────────────────────────────────────────────

st.divider()
st.subheader("News Ingestion")
st.caption("Paste a news article to update the knowledge graph with new information.")

news_url = st.text_input(
    "Article URL:",
    placeholder="https://reuters.com/...",
    key="news_url",
)
news_text = st.text_area(
    "Or paste article text directly:",
    placeholder="Paste the article content here...",
    height=120,
    key="news_text",
)

ingest_clicked = st.button(
    "Ingest Article",
    type="secondary",
    disabled=not (news_url or news_text),
    use_container_width=True,
)

if ingest_clicked and (news_url or news_text):
    with st.spinner("Analyzing, validating, and updating graph..."):
        from news_ingest import ingest_news
        import io, contextlib
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            ingest_result = ingest_news(url=news_url or None, text=news_text or None)
        st.session_state["ingest_result"] = ingest_result
        # Clear company cache so map picks up new nodes
        load_companies.clear()

ingest_result = st.session_state.get("ingest_result")
if ingest_result:
    # Summary
    if ingest_result.get("summary"):
        st.markdown(f"**Summary:** {ingest_result['summary']}")

    # Graph diff — before/after stats
    graph_diff = ingest_result.get("graph_diff", {})
    if graph_diff:
        st.markdown("**Graph Changes:**")
        diff_cols = st.columns(min(len(graph_diff), 4))
        for i, (key, vals) in enumerate(graph_diff.items()):
            label = key.replace("rel_", "").replace("_", " ").title()
            diff_cols[i % len(diff_cols)].metric(
                label,
                vals["after"],
                delta=f"+{vals['delta']}" if vals["delta"] > 0 else str(vals["delta"]),
            )

    # Tabs for details
    tab_added, tab_rejected, tab_annotated = st.tabs([
        f"Added ({len(ingest_result.get('changes', []))})",
        f"Rejected ({len(ingest_result.get('rejected', []))})",
        f"Annotated ({len(ingest_result.get('annotations', []))})",
    ])

    with tab_added:
        changes = ingest_result.get("changes", [])
        if changes:
            for change in changes:
                st.markdown(f"- {change}")
        else:
            st.info("No new information added to the graph.")

    with tab_rejected:
        rejected = ingest_result.get("rejected", [])
        if rejected:
            st.caption("These relationships were extracted but failed validation:")
            for r in rejected:
                st.markdown(f"- {r}")
        else:
            st.success("All extracted relationships passed validation.")

    with tab_annotated:
        annotations = ingest_result.get("annotations", [])
        if annotations:
            st.caption("Edge annotations (cost sensitivity & criticality):")
            ann_data = []
            for a in annotations:
                ann_data.append({
                    "Edge": a["edge"],
                    "Cost Sensitivity": f"{a['cost_sensitivity']:.1f}",
                    "Criticality": a["criticality"],
                })
            st.dataframe(pd.DataFrame(ann_data), use_container_width=True, hide_index=True)
        else:
            st.info("No edges required annotation.")
