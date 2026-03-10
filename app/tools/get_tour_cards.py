"""
get_tour_cards tool — exact port of src/chat/tools/get-tour-cards.tool.ts.
Complex logic: API fetch → fallback to static DB → carousel creation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.tour_card_service import TourCardService
from app.tools.tour_database import (
    TOUR_DATABASE,
    get_popular_tours,
    get_tours_by_category,
    get_tours_by_location,
)

logger = logging.getLogger(__name__)


async def get_tour_cards(inp: dict[str, Any]) -> str:
    city = inp.get("city")
    category = inp.get("category")
    carousel_type = inp.get("carouselType", "featured")
    limit = min(max(inp.get("limit", 6), 1), 12)

    try:
        from app.tools.registry import ToolRegistry

        logger.info(
            "[getTourCards] Fetching %s tours for %s, category: %s, limit: %d",
            carousel_type, city or "all cities", category or "all", limit,
        )

        tours: list[dict[str, Any]] = []
        use_static_data = False
        has_only_transfers = False

        if city and city.lower() != "all":
            cities_result = await ToolRegistry.execute("get_available_cities", {"productType": "tour"})
            cities_data = json.loads(cities_result)

            if cities_data.get("success") and cities_data.get("data"):
                options = (
                    cities_data.get("data", {}).get("data", {}).get("data", {}).get("options", [])
                )
                all_cities = []
                for o in options:
                    all_cities.extend(o.get("cities", []))

                city_data = next(
                    (c for c in all_cities if (c.get("name") or "").lower() == city.lower()),
                    None,
                )

                if city_data:
                    city_result = await ToolRegistry.execute("get_city_products", {"cityId": city_data["id"]})
                    city_result_data = json.loads(city_result)
                    payload = city_result_data.get("data") or {}
                    products = (
                        payload.get("data", {}).get("data", {}).get("products", [])
                    )
                    tours = products if isinstance(products, list) else []
                    tours = [{**p, "city": city} for p in tours]
        else:
            cities_result = await ToolRegistry.execute("get_available_cities", {"productType": "tour"})
            cities_data = json.loads(cities_result)
            options = cities_data.get("data", {}).get("data", {}).get("data", {}).get("options", [])
            all_cities = []
            for o in options:
                all_cities.extend(o.get("cities", []))
            dubai = next((c for c in all_cities if (c.get("name") or "").lower() == "dubai"), None)
            default_city_id = (dubai or {}).get("id") or (all_cities[0]["id"] if all_cities else None)

            if default_city_id:
                city_result = await ToolRegistry.execute("get_city_products", {"cityId": default_city_id})
                city_result_data = json.loads(city_result)
                payload = city_result_data.get("data") or {}
                products = payload.get("data", {}).get("data", {}).get("products", [])
                tours = products if isinstance(products, list) else []

        # Check for only transfers
        if tours:
            has_only_transfers = all(
                any(
                    kw in (t.get("name") or t.get("title") or "").lower()
                    or kw in (t.get("category") or "").lower()
                    for kw in ("transfer", "pickup", "drop")
                )
                for t in tours
            )

        if has_only_transfers:
            logger.info("[getTourCards] Detected only transfers for %s, switching to static data", city)

        # Fallback to static database
        if not tours or has_only_transfers:
            logger.info("[getTourCards] Using static tour database as fallback")
            use_static_data = True
            if city and city.lower() != "all":
                static = get_tours_by_location(city)
            elif category and category.lower() != "all":
                static = get_tours_by_category(category)
            else:
                static = get_popular_tours(limit)

            tours = [
                {
                    "id": t.id, "name": t.title, "title": t.title, "category": t.category,
                    "city": t.location, "location": t.location, "price": t.price,
                    "salePrice": t.price, "amount": t.price, "currency": t.currency,
                    "duration": t.duration, "description": t.description,
                    "highlights": t.highlights, "url": t.url, "slug": t.id,
                    "rating": t.rating, "averageRating": t.rating,
                    "is_featured": t.isPopular, "is_new": t.isNew,
                }
                for t in static
            ]

        # Apply category filter on API data
        if not use_static_data and category and category.lower() != "all":
            cat_lower = category.lower()
            tours = [
                t for t in tours
                if cat_lower in (t.get("name") or t.get("title") or "").lower()
                or cat_lower in (t.get("category") or "").lower()
                or (
                    isinstance(t.get("categories"), list)
                    and any(cat_lower in (c.get("label") or "").lower() for c in t["categories"] if isinstance(c, dict))
                )
                or cat_lower in TourCardService.categorize_activity(t.get("name") or t.get("title") or "").lower()
            ]

        tours = tours[:limit]

        if not tours:
            return json.dumps({
                "success": False,
                "message": (
                    f"No tours found{f' in {city}' if city else ''}"
                    f"{f' for {category}' if category else ''}. "
                    "Try browsing our popular destinations like Dubai, Bangkok, or Singapore!"
                ),
                "data": None,
            })

        # Create carousel
        if city and tours:
            nice_title = f"⭐ Featured in {city}" if carousel_type == "featured" else f"🏙️ Best in {city}"
            nice_sub = "Limited time deals" if carousel_type == "discount" else f"Top-rated activities and tours in {city}"
            carousel = TourCardService.format_tour_cards(tours, nice_title, nice_sub)
        else:
            match carousel_type:
                case "featured":
                    carousel = TourCardService.create_featured_carousel(tours)
                case "discount":
                    carousel = TourCardService.create_discount_carousel(tours)
                case "location":
                    carousel = TourCardService.create_location_carousel(tours, city or "UAE")
                case "category":
                    carousel = TourCardService.create_category_carousel(tours, category or "Adventure")
                case _:
                    carousel = TourCardService.format_tour_cards(tours, "🌟 Recommended Tours", "Popular tours and activities")

        # Build response text
        response_text = f"Here are amazing {category or 'tour'} options{f' in {city}' if city else ''}:\n\n"
        cards = carousel.get("cards", [])
        if cards:
            for idx, card in enumerate(cards):
                if use_static_data:
                    tour_obj = next((t for t in TOUR_DATABASE if t.id == card["id"]), None)
                    emoji = tour_obj.emoji if tour_obj else "🎯"
                else:
                    emoji = TourCardService.get_emoji_for_category(card.get("category", ""))
                response_text += (
                    f"{idx + 1}. {emoji} {card['title']} | {card['category']} "
                    f"💰 {card['currency']} {card['currentPrice']} | "
                    f"⏱ {card.get('duration', 'N/A')} 🔗 {card['url']}\n"
                )

            response_text += "\n📊 **Quick Summary:**\n"
            prices = [c["currentPrice"] for c in cards if c.get("currentPrice")]
            if len(prices) > 1:
                price_range = f"{cards[0]['currency']} {min(prices)} - {cards[0]['currency']} {max(prices)}"
            elif prices:
                price_range = f"{cards[0]['currency']} {prices[0]}"
            else:
                price_range = "N/A"
            response_text += f"💰 Price range: {price_range}\n"
            locations_set = list(dict.fromkeys(c.get("location", "") for c in cards))
            response_text += f"📍 Locations: {', '.join(locations_set)}\n"
            response_text += f"🎫 Total options: {len(cards)}\n"
            if use_static_data:
                response_text += "\n🌟 These are curated experiences from our premium collection!\n"
            discount_count = sum(1 for c in cards if c.get("discount"))
            if discount_count > 0:
                response_text += f"🎯 Special offers: {discount_count} tours with discounts\n"

        fallback_reason = None
        if use_static_data:
            fallback_reason = "transfers_only" if has_only_transfers else "no_api_data"

        return json.dumps({
            "success": True,
            "message": response_text,
            "data": {
                "carousel": carousel,
                "totalResults": len(tours),
                "filters": {"city": city or "all", "category": category or "all", "carouselType": carousel_type},
                "dataSource": "static" if use_static_data else "api",
                "note": "Showing curated experiences" if use_static_data else "Live data from API",
                "fallbackReason": fallback_reason,
            },
        })

    except Exception as e:
        logger.exception("[getTourCards] Error")
        # Emergency fallback
        try:
            fallback_tours = get_popular_tours(6)
            fallback_data = [
                {
                    "id": t.id, "name": t.title, "title": t.title, "category": t.category,
                    "city": t.location, "location": t.location, "price": t.price,
                    "salePrice": t.price, "amount": t.price, "currency": t.currency,
                    "duration": t.duration, "url": t.url, "rating": t.rating, "is_featured": t.isPopular,
                }
                for t in fallback_tours
            ]
            fallback_carousel = TourCardService.format_tour_cards(
                fallback_data, "🌟 Popular Tours", "Here are some of our most popular experiences"
            )
            fallback_text = "I had trouble finding specific tours, but here are some popular options:\n\n"
            for idx, card in enumerate(fallback_carousel.get("cards", [])):
                tour_obj = fallback_tours[idx] if idx < len(fallback_tours) else None
                emoji = tour_obj.emoji if tour_obj else "🎯"
                fallback_text += (
                    f"{idx + 1}. {emoji} {card['title']} | {card['category']} "
                    f"💰 {card['currency']} {card['currentPrice']} | "
                    f"⏱ {card.get('duration', 'N/A')} 🔗 {card['url']}\n"
                )
            return json.dumps({
                "success": True,
                "message": fallback_text,
                "data": {
                    "carousel": fallback_carousel,
                    "totalResults": len(fallback_tours),
                    "filters": {"city": "all", "category": "all", "carouselType": "featured"},
                    "fallback": True,
                },
            })
        except Exception:
            return json.dumps({
                "success": False,
                "message": "I'm having trouble loading tours right now. Please visit raynatours.com or try asking about specific destinations like Dubai, Bangkok, or Singapore!",
                "error": str(e),
            })
