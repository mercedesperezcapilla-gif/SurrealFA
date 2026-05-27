"""
LangGraph state definitions for the graph-building workflow.
"""

import operator
from typing import Annotated

from typing_extensions import TypedDict
from langgraph.graph import add_messages


class CompanyTask(TypedDict):
    """Input state for a per-company enrich sub-agent (passed via Send)."""
    company_name: str
    ticker: str
    wikidata_id: str
    description: str


class BuildState(TypedDict):
    """Top-level state for the build workflow."""
    query:              str
    num_companies:      int
    messages:           Annotated[list, add_messages]
    companies_enriched: Annotated[list[str], operator.add]
