"""
ToolRegistry — replaces src/chat/tools/index.ts.
Dynamic lookup by name. All 11 tools registered with Anthropic-style schemas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

import httpx

from app.config import get_settings
from app.memory.repositories import ConversionRepository, is_db_connected
from app.tools.visa_service import visa_service

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# HTTP client for Rayna API (replaces RaynaApiService)
# ─────────────────────────────────────────────────────────

_http: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        settings = get_settings()
        _http = httpx.AsyncClient(
            base_url=settings.rayna_api_base_url,
            timeout=15.0,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    return _http


def _trim_response(data: Any) -> Any:
    """Trim large API responses to stay within LLM token limits."""
    if not data or not isinstance(data, dict):
        if isinstance(data, list) and len(data) > 10:
            return {"items": data[:10], "total": len(data), "note": f"Showing 10 of {len(data)} results."}
        return data

    for key in list(data.keys()):
        val = data[key]
        if isinstance(val, list) and len(val) > 10:
            data[key] = val[:10]
            data[f"{key}_note"] = f"Showing 10 of {len(val)} results. Ask user to narrow down if needed."

    serialized = json.dumps(data)
    if len(serialized) > 8000:
        for key in list(data.keys()):
            val = data[key]
            if isinstance(val, list) and len(val) > 5:
                data[key] = val[:5]

    return data


# ─────────────────────────────────────────────────────────
# Tool Implementations (async)
# ─────────────────────────────────────────────────────────


async def _get_available_cities(inp: dict[str, Any], session_id: str | None = None) -> str:
    http = _get_http()
    resp = await http.get("/available-cities", params={"productType": inp.get("productType", "tour")})
    resp.raise_for_status()
    return json.dumps({"success": True, "data": _trim_response(resp.json())})


async def _get_all_products(inp: dict[str, Any], session_id: str | None = None) -> str:
    http = _get_http()
    resp = await http.get("/all-products", params={
        "productType": inp.get("productType"),
        "cityId": inp.get("cityId"),
        "cityName": inp.get("cityName"),
        "countryName": inp.get("countryName"),
    })
    resp.raise_for_status()
    return json.dumps({"success": True, "data": _trim_response(resp.json())})


async def _get_city_products(inp: dict[str, Any], session_id: str | None = None) -> str:
    http = _get_http()
    resp = await http.get("/city/products", params={"cityId": inp.get("cityId")})
    resp.raise_for_status()
    return json.dumps({"success": True, "data": _trim_response(resp.json())})


async def _get_city_holiday_packages(inp: dict[str, Any], session_id: str | None = None) -> str:
    http = _get_http()
    resp = await http.get("/city/holiday", params={"cityId": inp.get("cityId")})
    resp.raise_for_status()
    return json.dumps({"success": True, "data": _trim_response(resp.json())})


async def _get_city_cruises(inp: dict[str, Any], session_id: str | None = None) -> str:
    http = _get_http()
    resp = await http.get("/city/cruise", params={"cityId": inp.get("cityId")})
    resp.raise_for_status()
    return json.dumps({"success": True, "data": _trim_response(resp.json())})


async def _get_city_yachts(inp: dict[str, Any], session_id: str | None = None) -> str:
    http = _get_http()
    resp = await http.get("/city/yacht", params={"cityId": inp.get("cityId")})
    resp.raise_for_status()
    return json.dumps({"success": True, "data": _trim_response(resp.json())})


async def _get_product_details(inp: dict[str, Any], session_id: str | None = None) -> str:
    http = _get_http()
    resp = await http.get("/product-details", params={"url": inp.get("url")})
    resp.raise_for_status()
    return json.dumps({"success": True, "data": _trim_response(resp.json())})


async def _get_visas(inp: dict[str, Any], session_id: str | None = None) -> str:
    result = await visa_service.get_visas(
        country=inp.get("country"),
        limit=inp.get("limit"),
    )
    return json.dumps({
        "success": True,
        "data": {
            "success": True,
            "message": f"Found {len(result)} visa(s)",
            "data": result,
        },
    })


async def _get_popular_visas(inp: dict[str, Any], session_id: str | None = None) -> str:
    result = await visa_service.get_popular_visas()
    limited = result[: inp.get("limit", 8)]
    return json.dumps({
        "success": True,
        "data": {
            "success": True,
            "message": f"Found {len(limited)} popular visa destinations",
            "data": limited,
        },
    })


async def _get_tour_cards(inp: dict[str, Any], session_id: str | None = None) -> str:
    from app.tools.get_tour_cards import get_tour_cards
    return await get_tour_cards(inp)


async def _convert_currency(inp: dict[str, Any], session_id: str | None = None) -> str:
    amount = inp.get("amount", 0)
    from_cur = inp.get("fromCurrency", "AED")
    to_cur = inp.get("toCurrency", "USD")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"https://api.exchangerate-api.com/v4/latest/{from_cur}")
        resp.raise_for_status()
        rates = resp.json().get("rates", {})

    exchange_rate = rates.get(to_cur)
    if not exchange_rate:
        raise ValueError(f"Currency {to_cur} not supported")

    converted = round(float(amount) * exchange_rate, 2)
    rate_rounded = round(exchange_rate, 4)

    if is_db_connected() and session_id:
        await ConversionRepository.save(
            session_id=session_id,
            amount=float(amount),
            from_currency=str(from_cur).upper(),
            to_currency=str(to_cur).upper(),
            converted_amount=converted,
            exchange_rate=rate_rounded,
        )

    from datetime import datetime, timezone
    return json.dumps({
        "success": True,
        "data": {
            "originalAmount": amount,
            "fromCurrency": from_cur,
            "toCurrency": to_cur,
            "exchangeRate": rate_rounded,
            "convertedAmount": converted,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })


# ─────────────────────────────────────────────────────────
# Tool Schema Definitions (Anthropic format)
# ─────────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_available_cities",
        "description": (
            "Fetch all available cities for a specific product type on Rayna Tours.\n"
            "Use this when:\n"
            "- User asks \"where can I go\", \"what destinations are available\"\n"
            "- User asks about cities for tours, activities, holidays, cruises, or yachts\n"
            "- You need a city ID before fetching products (always call this first if you don't know the city ID)\n\n"
            "Returns: List of countries with their cities and city IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "productType": {
                    "type": "string",
                    "enum": ["tour", "activities", "holiday", "cruise", "yacht"],
                    "description": "Type of product to get cities for. Default to 'tour' if not specified.",
                },
            },
            "required": ["productType"],
        },
    },
    {
        "name": "get_all_products",
        "description": (
            "Fetch all tours, activities, holidays, cruises, or yachts available in a specific city.\n"
            "Use this when:\n"
            "- User asks \"show me tours in Dubai\", \"what activities are in Bangkok\"\n"
            "- User wants to browse options in a destination\n\n"
            "IMPORTANT: You need cityId, cityName and countryName.\n"
            "If you don't have the cityId, call get_available_cities first.\n\n"
            "Returns: List of products with name, type, normalPrice, salePrice, currency, URL and image."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "productType": {"type": "string", "enum": ["tour", "activities", "holiday", "cruise", "yacht"], "description": "Type of product to fetch"},
                "cityId": {"type": "number", "description": "Numeric city ID (e.g. 13668 for Dubai). Get from get_available_cities if unknown."},
                "cityName": {"type": "string", "description": "City name (e.g. Dubai, Singapore, Bangkok)"},
                "countryName": {"type": "string", "description": "Country name (e.g. United Arab Emirates, Thailand)"},
            },
            "required": ["productType", "cityId", "cityName", "countryName"],
        },
    },
    {
        "name": "get_city_products",
        "description": "Fetch general products available in a city by its ID.\nRequires cityId. Use get_available_cities first if you don't have the cityId.",
        "input_schema": {
            "type": "object",
            "properties": {"cityId": {"type": "number", "description": "Numeric city ID (e.g. 13668 for Dubai)"}},
            "required": ["cityId"],
        },
    },
    {
        "name": "get_city_holiday_packages",
        "description": "Fetch holiday packages available for a specific city.\nUse when user asks about holiday packages, vacation packages, travel packages.\nRequires cityId.",
        "input_schema": {
            "type": "object",
            "properties": {"cityId": {"type": "number", "description": "Numeric city ID"}},
            "required": ["cityId"],
        },
    },
    {
        "name": "get_city_cruises",
        "description": "Fetch cruise options available in a specific city.\nUse when user asks about cruises, dinner cruise, boat tours.\nRequires cityId.",
        "input_schema": {
            "type": "object",
            "properties": {"cityId": {"type": "number", "description": "Numeric city ID"}},
            "required": ["cityId"],
        },
    },
    {
        "name": "get_city_yachts",
        "description": "Fetch yacht rental/charter options available in a specific city.\nUse when user asks about yacht, yacht rental, private yacht.\nRequires cityId.",
        "input_schema": {
            "type": "object",
            "properties": {"cityId": {"type": "number", "description": "Numeric city ID"}},
            "required": ["cityId"],
        },
    },
    {
        "name": "get_product_details",
        "description": "Fetch detailed information about a specific tour or product using its URL.\nUse when user wants full description, inclusions, itinerary of a specific product.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full product page URL from Rayna Tours"}},
            "required": ["url"],
        },
    },
    {
        "name": "get_visas",
        "description": "Get visa information for different countries. Use when users ask about visa requirements, travel documents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Filter by specific country (e.g., 'dubai', 'usa', 'schengen'). Optional."},
                "limit": {"type": "number", "description": "Maximum number of visas to return (default 10, max 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_popular_visas",
        "description": "Get the most popular visa destinations offered by Rayna Tours. Use for general visa inquiries without specific country.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "number", "description": "Maximum number of popular visas to return (default 8, max 15)"}},
            "required": [],
        },
    },
    {
        "name": "get_tour_cards",
        "description": "Get tours in card format for display in carousel. Use this when users ask for tour recommendations, popular tours, or want to browse activities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Filter by city (Dubai, Abu Dhabi, Bangkok, Phuket, Bali, Singapore, etc.)"},
                "category": {"type": "string", "description": "Filter by category (desert safari, city tour, theme park, water park, adventure, cruise, cultural, etc.)"},
                "carouselType": {
                    "type": "string",
                    "enum": ["featured", "discount", "location", "category", "all"],
                    "description": "Type of carousel to create",
                },
                "limit": {"type": "number", "description": "Maximum number of tour cards (default 6, max 12)"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "convert_currency",
        "description": "Convert currency amounts using live exchange rates.\nUse when user asks to convert prices or see amounts in their local currency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "The amount to convert"},
                "fromCurrency": {"type": "string", "description": "Source currency code (e.g., 'AED', 'USD')"},
                "toCurrency": {"type": "string", "description": "Target currency code (e.g., 'INR', 'USD')"},
            },
            "required": ["amount", "fromCurrency", "toCurrency"],
        },
    },
]


# ─────────────────────────────────────────────────────────
# ToolRegistry — dynamic lookup by name
# ─────────────────────────────────────────────────────────


ToolExecutor = Callable[[dict[str, Any], str | None], Awaitable[str]]

_TOOL_MAP: dict[str, ToolExecutor] = {
    "get_available_cities": _get_available_cities,
    "get_all_products": _get_all_products,
    "get_city_products": _get_city_products,
    "get_city_holiday_packages": _get_city_holiday_packages,
    "get_city_cruises": _get_city_cruises,
    "get_city_yachts": _get_city_yachts,
    "get_product_details": _get_product_details,
    "get_visas": _get_visas,
    "get_popular_visas": _get_popular_visas,
    "get_tour_cards": _get_tour_cards,
    "convert_currency": _convert_currency,
}


class ToolRegistry:
    @staticmethod
    def get_all_schemas() -> list[dict[str, Any]]:
        return TOOL_SCHEMAS

    @staticmethod
    def get_executor(name: str) -> ToolExecutor | None:
        return _TOOL_MAP.get(name)

    @staticmethod
    async def execute(name: str, inp: dict[str, Any], session_id: str | None = None) -> str:
        executor = _TOOL_MAP.get(name)
        if not executor:
            return json.dumps({"success": False, "error": f"Unknown tool: {name}"})
        try:
            # Check Redis cache first
            from app.cache.redis_cache import get_cached, set_cached

            cached = await get_cached(name, inp)
            if cached is not None:
                logger.info("[ToolRegistry] Cache HIT for '%s'", name)
                return cached

            result = await executor(inp, session_id)

            # Cache the result (fire-and-forget)
            import asyncio
            asyncio.create_task(set_cached(name, inp, result))

            return result
        except Exception as e:
            logger.exception("[ToolRegistry] Tool '%s' failed", name)
            return json.dumps({
                "success": False,
                "error": str(e),
                "hint": "API call failed. Tell user data is temporarily unavailable.",
            })
