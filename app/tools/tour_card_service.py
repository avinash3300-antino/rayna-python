"""
Tour card formatting — exact port of src/chat/services/tour-card.service.ts.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any


class TourCardService:
    @staticmethod
    def format_tour_cards(
        tours: list[dict[str, Any]],
        title: str = "Recommended Tours",
        subtitle: str | None = None,
    ) -> dict[str, Any]:
        cards: list[dict[str, Any]] = []
        for index, tour in enumerate(tours):
            sale_price = (
                tour.get("discountedAmount")
                or tour.get("salePrice")
                or tour.get("price")
                or tour.get("current_price")
                or tour.get("amount")
                or 0
            )
            normal_price = (
                tour.get("amount")
                or tour.get("normalPrice")
                or tour.get("original_price")
                or tour.get("normal_price")
            )

            discount = 0
            discount_pct = 0
            if normal_price and sale_price and float(str(normal_price)) > float(str(sale_price)):
                discount = float(str(normal_price)) - float(str(sale_price))
                discount_pct = round((discount / float(str(normal_price))) * 100)

            current_price = TourCardService.extract_price(sale_price)
            original_price = TourCardService.extract_price(normal_price) if normal_price else None

            avg_rating = TourCardService._parse_float(tour.get("averageRating")) or TourCardService._parse_float(tour.get("rating"))
            is_recommended = (avg_rating is not None and avg_rating >= 4.8) or bool(tour.get("is_featured"))
            is_new = bool(tour.get("is_new")) or TourCardService._is_recently_added(tour.get("created_at"))

            # Duration extraction
            duration_val = tour.get("duration")
            if isinstance(duration_val, list) and duration_val:
                duration_val = duration_val[0].get("label") if isinstance(duration_val[0], dict) else str(duration_val[0])
            elif not isinstance(duration_val, str):
                duration_val = TourCardService._extract_duration(tour.get("name") or tour.get("description") or "")

            # Image extraction
            image = ""
            img_field = tour.get("image")
            if isinstance(img_field, dict):
                image = img_field.get("src", "")
            elif isinstance(img_field, str):
                image = img_field
            if not image:
                image = tour.get("banner_image") or tour.get("thumbnail") or tour.get("bannerImage") or ""

            # Category
            cat = tour.get("category")
            if not cat:
                cats = tour.get("categories")
                if isinstance(cats, list) and cats:
                    cat = cats[0].get("label", "") if isinstance(cats[0], dict) else str(cats[0])
            if not cat:
                cat = TourCardService.categorize_activity(tour.get("name") or tour.get("title") or "")

            # Highlights
            desc_for_highlights = tour.get("description") or ""
            if not desc_for_highlights:
                cats = tour.get("categories")
                if isinstance(cats, list):
                    desc_for_highlights = ", ".join(
                        c.get("label", "") if isinstance(c, dict) else str(c) for c in cats
                    )
            highlights_str = tour.get("highlights")
            if isinstance(highlights_str, str):
                desc_for_highlights = highlights_str

            card: dict[str, Any] = {
                "id": tour.get("id") or tour.get("slug") or f"tour_{index}",
                "title": tour.get("name") or tour.get("title") or tour.get("productName") or "Tour",
                "slug": tour.get("slug") or tour.get("id") or "",
                "image": image,
                "location": (
                    tour.get("city")
                    or tour.get("cityName")
                    or tour.get("location")
                    or TourCardService.extract_location_from_name(tour.get("name") or tour.get("title") or "")
                ),
                "category": cat,
                "originalPrice": original_price,
                "currentPrice": current_price,
                "currency": "AED",
                "discount": discount if discount > 0 else None,
                "discountPercentage": discount_pct if discount_pct > 0 else None,
                "isRecommended": is_recommended,
                "isNew": is_new,
                "rPoints": TourCardService._calculate_r_points(current_price),
                "rating": avg_rating,
                "reviewCount": TourCardService._parse_int(tour.get("reviewCount") or tour.get("review_count")),
                "duration": duration_val,
                "highlights": TourCardService._extract_highlights(desc_for_highlights),
                "url": TourCardService._build_tour_url(
                    (tour.get("productUrl", {}) or {}).get("href")
                    or tour.get("slug")
                    or tour.get("id")
                    or tour.get("url")
                    or ""
                ),
            }
            cards.append(card)

        return {
            "type": "tour_carousel",
            "title": title,
            "subtitle": subtitle,
            "cards": cards,
            "totalResults": len(tours),
        }

    @staticmethod
    def extract_price(price_value: Any) -> float:
        if not price_value:
            return 0.0
        s = re.sub(r"[^\d.,]", "", str(price_value)).replace(",", "")
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _is_recently_added(created_at: str | None) -> bool:
        if not created_at:
            return False
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            return created > datetime.now(timezone.utc) - timedelta(days=30)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def extract_location_from_name(name: str) -> str:
        locations = [
            "Dubai", "Abu Dhabi", "Sharjah", "Ras Al Khaimah",
            "Jeddah", "Riyadh", "Makkah", "Dammam",
            "Muscat", "Khasab",
            "Bangkok", "Phuket", "Krabi", "Koh Samui", "Pattaya",
            "Bali",
            "Kuala Lumpur", "Langkawi", "Penang",
            "Singapore",
        ]
        lower_name = name.lower()
        for loc in locations:
            if loc.lower() in lower_name:
                return loc
        return "Middle East"

    @staticmethod
    def categorize_activity(name: str) -> str:
        categories: dict[str, list[str]] = {
            "Desert Safari": ["desert", "safari", "dune", "camel"],
            "City Tour": ["city tour", "sightseeing"],
            "Theme Park": ["theme park", "ferrari world", "legoland", "motiongate", "img", "universal", "fantasea"],
            "Water Park": ["aquaventure", "waterworld", "water park", "splash"],
            "Adventure": ["zipline", "skydiving", "bungee", "quad bike", "buggy", "mountain", "trek", "safari"],
            "Cruise": ["cruise", "dhow", "dinner cruise", "boat", "sailing"],
            "Attraction": ["burj khalifa", "museum", "aquarium", "frame", "tower", "flyer", "cable car"],
            "Cultural": ["mosque", "heritage", "cultural", "traditional", "temple", "palace", "fort"],
            "Religious": ["umrah", "religious", "spiritual", "holy", "mosque", "temple"],
            "Island": ["island", "beach", "marine park", "coral", "snorkeling"],
            "Entertainment": ["show", "cabaret", "nightlife", "entertainment"],
            "Nature": ["gardens", "nature", "wildlife", "elephant", "safari"],
            "Shopping": ["shopping", "mall", "souq", "market"],
            "Food": ["food", "culinary", "street food", "dining"],
        }
        lower = name.lower()
        for category, keywords in categories.items():
            if any(kw in lower for kw in keywords):
                return category
        return "Experience"

    @staticmethod
    def _calculate_r_points(price: float) -> int:
        if not price or price <= 0:
            return 0
        points = price * 0.01
        return round(points / 100) * 100

    @staticmethod
    def _extract_duration(text: str) -> str | None:
        if not text:
            return None
        patterns = [
            r"(\d+)\s*hours?",
            r"(\d+)\s*hrs?",
            r"(\d+)\s*days?",
            r"(full\s*day)",
            r"(half\s*day)",
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def _extract_highlights(text: str) -> list[str] | None:
        if not text:
            return None
        highlight_terms = [
            "Burj Khalifa", "Dubai Mall", "Palm Jumeirah", "Dubai Marina",
            "Desert Safari", "Camel Riding", "Dune Bashing", "BBQ Dinner",
            "Ferrari World", "Yas Island", "Sheikh Zayed Mosque",
            "Aquaventure", "Atlantis", "Dubai Fountain", "Global Village",
            "Hot Air Balloon", "Skydiving", "Zip Line", "Dhow Cruise",
            "Emirates Palace", "Louvre Abu Dhabi", "Jais Zipline",
            "Historical District", "Corniche", "Masmak Fortress", "Kingdom Centre",
            "Holy Kaaba", "Mount Arafat", "Half Moon Bay", "Heritage Village",
            "Grand Mosque", "Twin Forts", "Mutrah Souq",
            "Mountain Safari", "Dolphins", "Norway of Arabia",
            "Floating Markets", "Grand Palace", "Elephant Sanctuary",
            "Phi Phi Island", "Sunset Cruise", "Fantasea Show",
            "Four Islands", "Emerald Pool", "Hot Springs", "Ang Thong",
            "Cabaret Show", "Coral Island",
            "Mount Batur", "Sunrise Trek", "Rice Terraces", "Water Temple",
            "Art Workshop", "Ubud",
            "Petronas Towers", "Batu Caves", "Street Food", "Cable Car",
            "Island Hopping", "George Town", "Heritage Walk", "Penang Hill",
            "Singapore Flyer", "Gardens by the Bay", "Universal Studios",
            "Night Safari", "Orchard Road",
        ]
        found = [h for h in highlight_terms if h.lower() in text.lower()]
        return found[:4] if found else None

    @staticmethod
    def _build_tour_url(slug: str) -> str:
        if not slug:
            return "https://www.raynatours.com"
        if slug.startswith("http"):
            return slug
        clean = slug.lstrip("/")
        return f"https://www.raynatours.com/{clean}"

    @staticmethod
    def get_emoji_for_category(category: str) -> str:
        emoji_map: dict[str, str] = {
            "desert safari": "🏜️", "adventure": "🚁", "culture": "🏛️",
            "religious": "🕌", "theme park": "🎢", "water park": "🌊",
            "cruise": "🚢", "island": "🏝️", "entertainment": "🎭",
            "nature": "🌺", "shopping": "🛍️", "food": "🍜",
            "attraction": "🗼", "wildlife": "🐘", "beach": "🏖️",
            "mountain": "⛰️", "temple": "⛩️", "modern": "🏙️",
        }
        lower = category.lower()
        for key, emoji in emoji_map.items():
            if key in lower:
                return emoji
        return "🎯"

    # Carousel factory methods
    @classmethod
    def create_featured_carousel(cls, tours: list[dict[str, Any]]) -> dict[str, Any]:
        featured = [t for t in tours if (cls._parse_float(t.get("rating")) or 0) >= 4.8 or t.get("is_featured")][:6]
        return cls.format_tour_cards(featured, "⭐ Featured Tours", "Most popular tours chosen by travelers")

    @classmethod
    def create_discount_carousel(cls, tours: list[dict[str, Any]]) -> dict[str, Any]:
        discounted = [t for t in tours if t.get("original_price") and t.get("price") and t["original_price"] > t["price"]][:6]
        return cls.format_tour_cards(discounted, "💰 Special Offers", "Limited time deals - Save up to 50%")

    @classmethod
    def create_location_carousel(cls, tours: list[dict[str, Any]], location: str) -> dict[str, Any]:
        loc_tours = [
            t for t in tours
            if location.lower() in (t.get("city") or "").lower()
            or location.lower() in (t.get("name") or "").lower()
        ][:6]
        return cls.format_tour_cards(loc_tours, f"🏙️ Best in {location}", f"Top-rated activities and tours in {location}")

    @classmethod
    def create_category_carousel(cls, tours: list[dict[str, Any]], category: str) -> dict[str, Any]:
        cat_tours = [
            t for t in tours
            if cls.categorize_activity(t.get("name") or "").lower().find(category.lower()) != -1
            or category.lower() in (t.get("name") or "").lower()
        ][:6]
        return cls.format_tour_cards(cat_tours, f"🎯 {category} Activities", f"Best {category.lower()} experiences")

    @staticmethod
    def _parse_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None
