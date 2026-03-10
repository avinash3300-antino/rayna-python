"""
LangGraph StateGraph — replaces runAgentLoop() (max 5 iterations).

Nodes:
  enrich_prompt  → RAGService — query Pinecone, inject context into system prompt
  call_llm       → invoke Claude/OpenAI/Groq based on LLM_PROVIDER
  execute_tools  → run all requested tools in PARALLEL via asyncio.gather()
  save_turn      → persist message to MongoDB + update in-memory session

Edges:
  enrich_prompt → call_llm
  call_llm → execute_tools  (if tool_calls present)
  call_llm → save_turn      (if no tool_calls — final reply)
  execute_tools → call_llm  (loop back with tool results)
  iteration >= 5 → save_turn (force exit)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.provider import LLMProvider, LLMResponse, create_llm_provider
from app.agent.state import AgentState
from app.memory.repositories import (
    ConversationRepository,
    MessageRepository,
    is_db_connected,
)
from app.memory.session import SessionService
from app.prompts.system import SYSTEM_PROMPT
from app.rag.pipeline import RAGService
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5

# Module-level singletons (initialised once in main.py lifespan)
_llm: LLMProvider | None = None
_rag: RAGService | None = None
_session_service: SessionService | None = None


def init_agent(session_service: SessionService) -> None:
    global _llm, _rag, _session_service
    _llm = create_llm_provider()
    _rag = RAGService()
    _session_service = session_service


# ─────────────────────────────────────────────────────────
# Graph Nodes
# ─────────────────────────────────────────────────────────


async def enrich_prompt(state: AgentState) -> AgentState:
    """RAGService — query Pinecone, inject context into system prompt."""
    assert _rag is not None
    messages = state.get("messages", [])
    user_query = ""
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            user_query = m["content"]
            break
    enhanced = await _rag.get_enhanced_system_prompt(SYSTEM_PROMPT, user_query)
    return {**state, "enhanced_system_prompt": enhanced}


async def call_llm(state: AgentState) -> AgentState:
    """Invoke the configured LLM provider."""
    assert _llm is not None
    messages = state.get("messages", [])
    system_prompt = state.get("enhanced_system_prompt", SYSTEM_PROMPT)
    tools = ToolRegistry.get_all_schemas()

    iteration = state.get("iteration_count", 0) + 1
    logger.info("[AgentLoop] Iteration %d", iteration)

    response: LLMResponse = await _llm.chat(messages, system_prompt, tools)

    # Append assistant message to conversation
    new_messages = messages + [{"role": "assistant", "content": response.raw_content}]

    provider_name = type(_llm).__name__

    if not _llm.is_tool_use(response):
        # Final text reply — no more tools
        return {
            **state,
            "messages": new_messages,
            "iteration_count": iteration,
            "final_reply": response.text,
            "provider_used": provider_name,
            "done": True,
        }

    # LLM wants to call tools
    tool_calls = _llm.extract_tool_calls(response)
    logger.info("[AgentLoop] Tool calls requested: %s", [tc["name"] for tc in tool_calls])

    return {
        **state,
        "messages": new_messages,
        "iteration_count": iteration,
        "tool_results": [{"id": tc["id"], "name": tc["name"], "input": tc["input"]} for tc in tool_calls],
        "provider_used": provider_name,
        "done": False,
    }


async def execute_tools(state: AgentState) -> AgentState:
    """Run all requested tools in PARALLEL via asyncio.gather()."""
    assert _llm is not None
    tool_calls = state.get("tool_results", [])
    session_id = state.get("session_id", "")
    tour_carousel = state.get("tour_carousel")
    metadata = state.get("metadata")

    async def _run_one(call: dict[str, Any]) -> dict[str, str]:
        result = await ToolRegistry.execute(call["name"], call["input"], session_id)

        # Capture tour carousel data (same as Node.js)
        if call["name"] == "get_tour_cards" and result:
            try:
                parsed = json.loads(result) if isinstance(result, str) else result
                if parsed.get("success") and parsed.get("data", {}).get("carousel"):
                    nonlocal tour_carousel, metadata
                    tour_carousel = parsed["data"]["carousel"]
                    metadata = {
                        "hasCards": True,
                        "cardCount": len(parsed["data"]["carousel"].get("cards", [])),
                        "totalResults": parsed["data"].get("totalResults", 0),
                    }
                    logger.info("[AgentLoop] Tour cards retrieved: %d cards", metadata["cardCount"])
            except Exception:
                logger.exception("[AgentLoop] Error parsing tour cards result")

        logger.info("[AgentLoop] Tool '%s' completed", call["name"])
        return {"id": call["id"], "content": result if isinstance(result, str) else json.dumps(result)}

    results = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

    tool_result_message = _llm.build_tool_result_message(list(results))
    messages = state.get("messages", []) + [tool_result_message]

    return {
        **state,
        "messages": messages,
        "tool_results": [],
        "tour_carousel": tour_carousel,
        "metadata": metadata,
    }


async def save_turn(state: AgentState) -> AgentState:
    """Persist message to MongoDB + update in-memory session."""
    assert _session_service is not None
    session_id = state.get("session_id", "")
    final_reply = state.get("final_reply", "")
    tour_carousel = state.get("tour_carousel")

    _session_service.add_message(session_id, {"role": "assistant", "content": final_reply})

    if is_db_connected():
        await MessageRepository.save(
            session_id=session_id,
            role="assistant",
            content=final_reply,
            tour_carousel=tour_carousel,
        )
        await ConversationRepository.increment_count(session_id)

    return state


# ─────────────────────────────────────────────────────────
# Routing logic
# ─────────────────────────────────────────────────────────


def after_call_llm(state: AgentState) -> str:
    if state.get("done"):
        return "save_turn"
    if state.get("iteration_count", 0) >= MAX_ITERATIONS:
        logger.warning("[AgentLoop] Max iterations reached — forcing exit")
        return "force_exit"
    return "execute_tools"


async def force_exit(state: AgentState) -> AgentState:
    """Force exit at iteration limit with fallback message."""
    return {
        **state,
        "final_reply": (
            "I'm having trouble processing that right now. "
            "Please try again or visit raynatours.com for assistance."
        ),
        "done": True,
    }


# ─────────────────────────────────────────────────────────
# Build the StateGraph
# ─────────────────────────────────────────────────────────


def build_agent_graph() -> Any:
    graph = StateGraph(AgentState)

    graph.add_node("enrich_prompt", enrich_prompt)
    graph.add_node("call_llm", call_llm)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("save_turn", save_turn)
    graph.add_node("force_exit", force_exit)

    graph.set_entry_point("enrich_prompt")
    graph.add_edge("enrich_prompt", "call_llm")
    graph.add_conditional_edges("call_llm", after_call_llm, {
        "save_turn": "save_turn",
        "execute_tools": "execute_tools",
        "force_exit": "force_exit",
    })
    graph.add_edge("execute_tools", "call_llm")
    graph.add_edge("force_exit", "save_turn")
    graph.add_edge("save_turn", END)

    return graph.compile()


# ─────────────────────────────────────────────────────────
# Public API — called by ChatService / API route
# ─────────────────────────────────────────────────────────

_compiled_graph: Any = None


def get_graph() -> Any:
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph


async def run_agent(
    session_id: str, user_message: str, user_id: str | None = None
) -> dict[str, Any]:
    """
    Main entry point — replaces ChatService.chat().
    Mirrors exact behavior: save user msg → run graph → return reply.
    """
    assert _session_service is not None

    # 1. Save user message to in-memory session
    _session_service.add_message(session_id, {"role": "user", "content": user_message}, user_id)

    # 1b. Persist user message + upsert conversation to MongoDB
    if is_db_connected():
        await ConversationRepository.upsert(session_id, user_message)
        await MessageRepository.save(session_id=session_id, role="user", content=user_message)

    # 2. Get context (last N messages)
    messages = _session_service.get_context(session_id)

    # 3. Run the LangGraph agent loop
    graph = get_graph()
    initial_state: AgentState = {
        "session_id": session_id,
        "messages": messages,
        "tool_results": [],
        "iteration_count": 0,
        "rag_context": "",
        "final_reply": "",
        "tour_carousel": None,
        "metadata": None,
        "provider_used": "",
        "enhanced_system_prompt": SYSTEM_PROMPT,
        "done": False,
    }

    final_state = await graph.ainvoke(initial_state)

    return {
        "reply": final_state.get("final_reply", ""),
        "session_id": session_id,
        "tourCarousel": final_state.get("tour_carousel"),
        "metadata": final_state.get("metadata"),
    }
