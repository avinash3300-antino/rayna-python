"""
AgentState TypedDict for LangGraph StateGraph.
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, str]]
    iteration_count: int
    rag_context: str
    final_reply: str
    tour_carousel: dict[str, Any] | None
    product_carousel: dict[str, Any] | None
    metadata: dict[str, Any] | None
    provider_used: str
    enhanced_system_prompt: str
    done: bool
