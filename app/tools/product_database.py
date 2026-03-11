"""
Static fallback product data for holidays, cruises, and yachts.
Used when the Rayna API returns no data (similar to tour_database.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StaticProduct:
    id: str
    name: str
    city: str
    price: float
    currency: str = "AED"
    duration: str = ""
    image: str = ""
    url: str = ""
    category: str = ""
    description: str = ""
    amenities: list[str] = field(default_factory=list)


# ── Holiday Packages ─────────────────────────────────────
HOLIDAY_DATABASE: list[StaticProduct] = [
    StaticProduct(
        id="hol-dubai-1",
        name="Dubai City Explorer Package",
        city="Dubai",
        price=1899,
        duration="4 Nights / 5 Days",
        image="https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/dubai",
        category="Holiday",
        description="Explore iconic Dubai landmarks with hotel stay, transfers and guided tours.",
        amenities=["Hotel Stay", "Airport Transfers", "City Tour", "Desert Safari", "Dhow Cruise"],
    ),
    StaticProduct(
        id="hol-dubai-2",
        name="Dubai Premium Holiday",
        city="Dubai",
        price=3499,
        duration="5 Nights / 6 Days",
        image="https://images.unsplash.com/photo-1518684079-3c830dcef090?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/dubai",
        category="Holiday",
        description="Premium Dubai experience with 5-star hotel, Burj Khalifa and adventure activities.",
        amenities=["5-Star Hotel", "Burj Khalifa", "Desert Safari", "Yacht Tour", "Airport Transfers"],
    ),
    StaticProduct(
        id="hol-abudhabi-1",
        name="Abu Dhabi Discovery Package",
        city="Abu Dhabi",
        price=2199,
        duration="3 Nights / 4 Days",
        image="https://images.unsplash.com/photo-1611605698335-8b1569810432?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/abu-dhabi",
        category="Holiday",
        description="Discover Abu Dhabi's grandeur with Sheikh Zayed Mosque, Yas Island and Ferrari World.",
        amenities=["Hotel Stay", "City Tour", "Ferrari World", "Yas Island", "Transfers"],
    ),
    StaticProduct(
        id="hol-singapore-1",
        name="Singapore Fun Package",
        city="Singapore",
        price=2799,
        duration="4 Nights / 5 Days",
        image="https://images.unsplash.com/photo-1525625293386-3f8f99389edd?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/singapore",
        category="Holiday",
        description="Experience Singapore with Sentosa Island, Gardens by the Bay and Night Safari.",
        amenities=["Hotel Stay", "Sentosa Island", "Gardens by the Bay", "Night Safari", "Transfers"],
    ),
    StaticProduct(
        id="hol-thailand-1",
        name="Thailand Explorer Package",
        city="Bangkok",
        price=1599,
        duration="5 Nights / 6 Days",
        image="https://images.unsplash.com/photo-1528181304800-259b08848526?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/thailand",
        category="Holiday",
        description="Bangkok temples, floating markets and Pattaya beach — all in one amazing package.",
        amenities=["Hotel Stay", "Temple Tour", "Floating Market", "Pattaya Day Trip", "Transfers"],
    ),
    StaticProduct(
        id="hol-bali-1",
        name="Bali Paradise Package",
        city="Bali",
        price=2099,
        duration="5 Nights / 6 Days",
        image="https://images.unsplash.com/photo-1537996194471-e657df975ab4?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/bali",
        category="Holiday",
        description="Explore Bali's temples, rice terraces and stunning beaches with guided tours.",
        amenities=["Hotel Stay", "Ubud Tour", "Temple Visit", "Beach Activities", "Transfers"],
    ),
    StaticProduct(
        id="hol-turkey-1",
        name="Turkey Highlights Package",
        city="Istanbul",
        price=2499,
        duration="6 Nights / 7 Days",
        image="https://images.unsplash.com/photo-1524231757912-21f4fe3a7200?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/turkey",
        category="Holiday",
        description="Istanbul, Cappadocia and Pamukkale — the best of Turkey in one package.",
        amenities=["Hotel Stay", "Istanbul Tour", "Cappadocia", "Hot Air Balloon", "Transfers"],
    ),
    StaticProduct(
        id="hol-maldives-1",
        name="Maldives Beach Getaway",
        city="Maldives",
        price=4999,
        duration="4 Nights / 5 Days",
        image="https://images.unsplash.com/photo-1514282401047-d79a71a590e8?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/holidays/maldives",
        category="Holiday",
        description="Overwater villa experience with snorkeling, dolphin cruise and sunset fishing.",
        amenities=["Overwater Villa", "Snorkeling", "Dolphin Cruise", "Sunset Fishing", "All Meals"],
    ),
]

# ── Cruises ──────────────────────────────────────────────
CRUISE_DATABASE: list[StaticProduct] = [
    StaticProduct(
        id="cr-dubai-1",
        name="Dubai Marina Dinner Cruise",
        city="Dubai",
        price=249,
        duration="3 Hours",
        image="https://images.unsplash.com/photo-1580541631950-7282082b02f6?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/cruises/dubai-marina-cruise",
        category="Cruise",
        description="Luxury dinner cruise along Dubai Marina with buffet dinner and live entertainment.",
    ),
    StaticProduct(
        id="cr-dubai-2",
        name="Dhow Cruise Dubai Creek",
        city="Dubai",
        price=149,
        duration="2 Hours",
        image="https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/cruises/dhow-cruise-creek",
        category="Cruise",
        description="Traditional dhow cruise on Dubai Creek with dinner, tanoura show and cultural experience.",
    ),
    StaticProduct(
        id="cr-dubai-3",
        name="Dubai Luxury Yacht Cruise",
        city="Dubai",
        price=599,
        duration="4 Hours",
        image="https://images.unsplash.com/photo-1567899378494-47b22a2ae96a?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/cruises/luxury-yacht-cruise",
        category="Cruise",
        description="Private luxury yacht experience with BBQ, swimming and views of Burj Al Arab.",
    ),
    StaticProduct(
        id="cr-abudhabi-1",
        name="Abu Dhabi Sunset Cruise",
        city="Abu Dhabi",
        price=199,
        duration="2 Hours",
        image="https://images.unsplash.com/photo-1611605698335-8b1569810432?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/cruises/abu-dhabi-sunset",
        category="Cruise",
        description="Scenic cruise around Abu Dhabi corniche with stunning sunset views.",
    ),
    StaticProduct(
        id="cr-oman-1",
        name="Musandam Dibba Cruise",
        city="Musandam",
        price=349,
        duration="Full Day",
        image="https://images.unsplash.com/photo-1597220869811-9eb894044aa5?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/cruises/musandam-dibba",
        category="Cruise",
        description="Full-day dhow cruise in Musandam fjords with snorkeling, kayaking and lunch.",
    ),
]

# ── Yachts ───────────────────────────────────────────────
YACHT_DATABASE: list[StaticProduct] = [
    StaticProduct(
        id="yt-dubai-1",
        name="50ft Luxury Yacht Charter",
        city="Dubai",
        price=799,
        duration="3 Hours",
        image="https://images.unsplash.com/photo-1567899378494-47b22a2ae96a?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/yachts/50ft-luxury-yacht",
        category="Yacht",
        description="Private 50ft yacht for up to 12 guests with swimming, fishing and BBQ.",
    ),
    StaticProduct(
        id="yt-dubai-2",
        name="65ft Premium Yacht",
        city="Dubai",
        price=1299,
        duration="4 Hours",
        image="https://images.unsplash.com/photo-1540946485063-a40da27545f8?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/yachts/65ft-premium-yacht",
        category="Yacht",
        description="Premium yacht experience with onboard chef, jacuzzi and Dubai skyline views.",
    ),
    StaticProduct(
        id="yt-dubai-3",
        name="85ft Mega Yacht Experience",
        city="Dubai",
        price=2499,
        duration="4 Hours",
        image="https://images.unsplash.com/photo-1605281317010-fe5ffe798166?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/yachts/85ft-mega-yacht",
        category="Yacht",
        description="Mega yacht with 3 decks, jetski, flyboard and luxury amenities for up to 30 guests.",
    ),
    StaticProduct(
        id="yt-dubai-4",
        name="Budget Yacht Tour",
        city="Dubai",
        price=399,
        duration="2 Hours",
        image="https://images.unsplash.com/photo-1580541631950-7282082b02f6?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/yachts/budget-yacht",
        category="Yacht",
        description="Affordable yacht experience along Dubai Marina with soft drinks and music.",
    ),
    StaticProduct(
        id="yt-abudhabi-1",
        name="Abu Dhabi Yacht Charter",
        city="Abu Dhabi",
        price=999,
        duration="3 Hours",
        image="https://images.unsplash.com/photo-1611605698335-8b1569810432?w=600&h=400&fit=crop",
        url="https://www.raynatours.com/yachts/abu-dhabi-charter",
        category="Yacht",
        description="Private yacht charter in Abu Dhabi with views of Corniche, Lulu Island and Louvre.",
    ),
]


def get_holidays_by_city(city: str) -> list[StaticProduct]:
    city_lower = city.lower()
    matches = [h for h in HOLIDAY_DATABASE if h.city.lower() == city_lower]
    return matches if matches else HOLIDAY_DATABASE[:4]


def get_cruises_by_city(city: str) -> list[StaticProduct]:
    city_lower = city.lower()
    matches = [c for c in CRUISE_DATABASE if c.city.lower() == city_lower]
    return matches if matches else CRUISE_DATABASE[:4]


def get_yachts_by_city(city: str) -> list[StaticProduct]:
    city_lower = city.lower()
    matches = [y for y in YACHT_DATABASE if y.city.lower() == city_lower]
    return matches if matches else YACHT_DATABASE[:4]


def static_product_to_card(product: StaticProduct, carousel_type: str) -> dict[str, Any]:
    """Convert a StaticProduct to a card dict matching _extract_product_cards output."""
    card: dict[str, Any] = {
        "id": product.id,
        "title": product.name,
        "image": product.image,
        "location": product.city,
        "category": product.category or carousel_type.replace("_carousel", "").title(),
        "originalPrice": product.price * 1.2,   # Show ~20% "discount"
        "currentPrice": product.price,
        "currency": product.currency,
        "duration": product.duration,
        "url": product.url,
        "slug": product.id,
        "description": product.description,
    }
    if carousel_type == "holiday_carousel" and product.amenities:
        card["amenities"] = product.amenities
    return card
