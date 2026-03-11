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
import re
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


def _is_product_item(item: dict[str, Any]) -> bool:
    """Check if a dict looks like a real product (has name + price or url)."""
    has_name = bool(item.get("name") or item.get("title"))
    has_price = any(item.get(k) for k in ("normalPrice", "salePrice", "price", "currentPrice", "originalPrice"))
    has_url = bool(item.get("url") or item.get("productUrl"))
    # Must have a name AND at least price or url to be a real product
    return has_name and (has_price or has_url)


def _find_product_list(data: Any, depth: int = 0) -> list[dict[str, Any]]:
    """Recursively search for a list of product-like dicts in nested API response."""
    if depth > 6:
        return []

    # If it's already a list of dicts that look like real products, return it
    if isinstance(data, list) and data:
        if isinstance(data[0], dict) and _is_product_item(data[0]):
            return data
        # Search within list items
        for item in data:
            if isinstance(item, dict):
                result = _find_product_list(item, depth + 1)
                if result:
                    return result
        return []

    if isinstance(data, dict):
        # Check known keys for product lists first (prioritize "products" key)
        for key in ("products", "packages", "holidays", "cruises", "yachts", "items", "results"):
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict) and _is_product_item(val[0]):
                return val
        # Recurse into dict values (check "data" key last to avoid matching sub-objects)
        for key in ("data",):
            val = data.get(key)
            if isinstance(val, (dict, list)):
                result = _find_product_list(val, depth + 1)
                if result:
                    return result
        # Recurse into other dict values
        for k, val in data.items():
            if k in ("products", "packages", "holidays", "cruises", "yachts", "items", "results", "data"):
                continue  # Already checked above
            if isinstance(val, (dict, list)):
                result = _find_product_list(val, depth + 1)
                if result:
                    return result
    return []


def _extract_product_cards(data: dict[str, Any], carousel_type: str) -> list[dict[str, Any]]:
    """Extract product cards from raw API response for holidays, cruises, yachts."""
    products = _find_product_list(data)

    logger.info(
        "[CardExtract] carousel_type=%s, found %d products, data_keys=%s",
        carousel_type, len(products),
        list(data.keys()) if isinstance(data, dict) else type(data).__name__,
    )
    if products:
        logger.info("[CardExtract] First product keys: %s", list(products[0].keys()))

    cards = []
    for p in products[:12]:
        if not isinstance(p, dict):
            continue
        card = {
            "id": p.get("id") or p.get("productId") or p.get("slug", ""),
            "title": p.get("name") or p.get("title") or "",
            "image": p.get("image") or p.get("imageUrl") or p.get("thumbnail") or "",
            "location": p.get("city") or p.get("location") or p.get("cityName") or "",
            "category": p.get("category") or p.get("productCategory") or p.get("type") or carousel_type.replace("_carousel", ""),
            "originalPrice": _safe_float(p.get("normalPrice") or p.get("originalPrice") or p.get("price")),
            "currentPrice": _safe_float(p.get("salePrice") or p.get("currentPrice") or p.get("price") or p.get("normalPrice")),
            "currency": p.get("currency") or "AED",
            "duration": p.get("duration") or p.get("noOfDays") or "",
            "url": p.get("url") or p.get("productUrl") or "",
            "slug": p.get("slug") or p.get("url") or "",
        }
        # Include amenities/inclusions for holidays
        if carousel_type == "holiday_carousel":
            card["amenities"] = p.get("amenities") or p.get("inclusions") or []
        # Accept card if it has a title (don't filter on price — some may be 0 / free)
        if card["title"]:
            cards.append(card)

    logger.info("[CardExtract] Built %d cards from %d products", len(cards), len(products))
    return cards


def _safe_float(val: Any) -> float:
    """Convert value to float safely, return 0.0 on failure."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _carousel_title(carousel_type: str, inp: dict[str, Any]) -> str:
    """Generate a nice carousel title."""
    labels = {
        "holiday_carousel": "Holiday Packages",
        "cruise_carousel": "Cruises",
        "yacht_carousel": "Yacht Experiences",
    }
    label = labels.get(carousel_type, "Experiences")
    return f"🌟 {label}"


def _sanitize_reply(text: str) -> str:
    """Strip raw JSON blocks, HTML-like tags, and card markup the LLM may have dumped."""
    if not text:
        return text

    # Remove <CAROUSEL ...>, <holiday-cards>, [HOLIDAY_CARDS], etc. and their contents
    # Pattern: <TAG ...> ... </TAG> or <TAG ... />
    text = re.sub(
        r'<(?:CAROUSEL|holiday-cards|cruise-cards|yacht-cards|tour-cards)[^>]*>.*?</(?:CAROUSEL|holiday-cards|cruise-cards|yacht-cards|tour-cards)>',
        '', text, flags=re.DOTALL | re.IGNORECASE,
    )
    # Self-closing tags: <CAROUSEL ... />
    text = re.sub(
        r'<(?:CAROUSEL|holiday-cards|cruise-cards|yacht-cards|tour-cards)[^>]*/\s*>',
        '', text, flags=re.DOTALL | re.IGNORECASE,
    )
    # Opening tags without closing (LLM sometimes doesn't close): <TAG ...> followed by JSON
    text = re.sub(
        r'<(?:CAROUSEL|holiday-cards|cruise-cards|yacht-cards|tour-cards)[^>]*>',
        '', text, flags=re.IGNORECASE,
    )

    # Remove [HOLIDAY_CARDS], [TOUR_CARDS], etc. bracket markers + JSON block after them
    text = re.sub(
        r'\[(?:HOLIDAY_CARDS|TOUR_CARDS|CRUISE_CARDS|YACHT_CARDS)\]\s*\{.*?\}\s*',
        '', text, flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r'\[(?:HOLIDAY_CARDS|TOUR_CARDS|CRUISE_CARDS|YACHT_CARDS)\]\s*\[.*?\]\s*',
        '', text, flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove large inline JSON blocks (arrays/objects with "products", "name", "price", etc.)
    # Match JSON objects/arrays that look like product data (> 200 chars with product-like keys)
    text = re.sub(
        r'\{"products"\s*:\s*\[.*?\]\s*\}',
        '', text, flags=re.DOTALL,
    )
    # Standalone JSON arrays with product-like objects
    text = re.sub(
        r'\[\s*\{\s*"(?:id|name|title|price|url|image)".*?\}\s*\]',
        '', text, flags=re.DOTALL,
    )

    # Clean up leftover whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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
    product_carousel = state.get("product_carousel")
    metadata = state.get("metadata")

    # Tools that return product lists which should be rendered as cards
    PRODUCT_CARD_TOOLS = {
        "get_city_holiday_packages": "holiday_carousel",
        "get_city_cruises": "cruise_carousel",
        "get_city_yachts": "yacht_carousel",
    }

    async def _run_one(call: dict[str, Any]) -> dict[str, str]:
        result = await ToolRegistry.execute(call["name"], call["input"], session_id)

        nonlocal tour_carousel, product_carousel, metadata

        # Capture tour carousel data (same as Node.js)
        if call["name"] == "get_tour_cards" and result:
            try:
                parsed = json.loads(result) if isinstance(result, str) else result
                if parsed.get("success") and parsed.get("data", {}).get("carousel"):
                    tour_carousel = parsed["data"]["carousel"]
                    product_carousel = tour_carousel
                    metadata = {
                        "hasCards": True,
                        "cardType": "tour_carousel",
                        "cardCount": len(parsed["data"]["carousel"].get("cards", [])),
                        "totalResults": parsed["data"].get("totalResults", 0),
                    }
                    logger.info("[AgentLoop] Tour cards retrieved: %d cards", metadata["cardCount"])
            except Exception:
                logger.exception("[AgentLoop] Error parsing tour cards result")

        # Capture holiday/cruise/yacht data and build carousel
        elif call["name"] in PRODUCT_CARD_TOOLS and result:
            try:
                parsed = json.loads(result) if isinstance(result, str) else result
                logger.info(
                    "[AgentLoop] %s raw result keys: %s, success=%s, has_data=%s",
                    call["name"],
                    list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__,
                    parsed.get("success"),
                    bool(parsed.get("data")),
                )
                if parsed.get("success") and parsed.get("data"):
                    carousel_type = PRODUCT_CARD_TOOLS[call["name"]]
                    cards = _extract_product_cards(parsed["data"], carousel_type)
                    if cards:
                        product_carousel = {
                            "type": carousel_type,
                            "title": _carousel_title(carousel_type, call["input"]),
                            "cards": cards,
                            "totalResults": len(cards),
                        }
                        metadata = {
                            "hasCards": True,
                            "cardType": carousel_type,
                            "cardCount": len(cards),
                            "totalResults": len(cards),
                        }
                        logger.info("[AgentLoop] %s cards retrieved: %d cards", carousel_type, len(cards))
            except Exception:
                logger.exception("[AgentLoop] Error parsing %s result", call["name"])

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
        "product_carousel": product_carousel,
        "metadata": metadata,
    }


async def save_turn(state: AgentState) -> AgentState:
    """Persist message to MongoDB + update in-memory session."""
    assert _session_service is not None
    session_id = state.get("session_id", "")
    final_reply = _sanitize_reply(state.get("final_reply", ""))
    tour_carousel = state.get("tour_carousel")
    product_carousel = state.get("product_carousel")

    _session_service.add_message(session_id, {"role": "assistant", "content": final_reply})

    if is_db_connected():
        await MessageRepository.save(
            session_id=session_id,
            role="assistant",
            content=final_reply,
            tour_carousel=product_carousel or tour_carousel,
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
        "product_carousel": None,
        "metadata": None,
        "provider_used": "",
        "enhanced_system_prompt": SYSTEM_PROMPT,
        "done": False,
    }

    final_state = await graph.ainvoke(initial_state)

    # Sanitize the reply — strip any raw JSON/tags the LLM may have dumped
    reply = _sanitize_reply(final_state.get("final_reply", ""))

    return {
        "reply": reply,
        "session_id": session_id,
        "tourCarousel": final_state.get("tour_carousel"),
        "productCarousel": final_state.get("product_carousel"),
        "metadata": final_state.get("metadata"),
    }
