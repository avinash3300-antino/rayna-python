"""
Visa data fetching — exact port of src/chat/visa.service.ts.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://earnest-panda-e8edbd.netlify.app/api"


class VisaService:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0, headers={
            "Accept": "application/json",
            "User-Agent": "Rayna-Tours-Chatbot/2.0.0",
        })

    async def get_visas(
        self,
        country: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        logger.info("[VisaService] Fetching visas, country=%s limit=%s", country, limit)
        try:
            resp = await self._http.get(f"{BASE_URL}/visas")
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                raise RuntimeError("API returned success: false")

            visas: list[dict[str, Any]] = data.get("products") or []

            if country:
                cf = country.lower().strip()
                visas = [
                    v for v in visas
                    if cf in v.get("countrySlug", "").lower()
                    or cf in v.get("country", "").lower()
                ]

            if limit and limit > 0:
                visas = visas[:limit]

            logger.info("[VisaService] Returning %d visas", len(visas))
            return visas

        except httpx.TimeoutException:
            raise RuntimeError("Request timeout - visa service is taking too long to respond")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Visa API error: {e.response.status_code}")
        except Exception as e:
            logger.exception("[VisaService] Error fetching visas")
            raise RuntimeError(f"Failed to fetch visas: {e}")

    async def get_popular_visas(self) -> list[dict[str, Any]]:
        try:
            all_visas = await self.get_visas(limit=50)
            popular_countries = [
                "dubai", "usa", "uk", "canada", "australia", "schengen",
                "singapore", "thailand", "malaysia", "turkey", "japan", "south-korea",
            ]
            popular = [
                v for v in all_visas
                if any(
                    c in v.get("countrySlug", "").lower() or c in v.get("country", "").lower()
                    for c in popular_countries
                )
            ]
            return popular[:10]
        except Exception:
            logger.exception("[VisaService] Error fetching popular visas")
            raise

    async def search_visas_by_country(self, search_query: str) -> list[dict[str, Any]]:
        try:
            all_visas = await self.get_visas(limit=100)
            q = search_query.lower().strip()
            matched = [
                v for v in all_visas
                if q in v.get("country", "").lower()
                or q in v.get("countrySlug", "").lower()
                or q in v.get("name", "").lower()
            ]
            return matched[:10]
        except Exception:
            logger.exception("[VisaService] Error searching visas")
            raise


visa_service = VisaService()
