"""Nominatim (OpenStreetMap) — 正向 + 逆向地理编码."""

from __future__ import annotations

from geo.config import GEOCODE_TIMEOUT
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import forward_geocoder, reverse_geocoder


@forward_geocoder("nominatim", weight=4)
def _geocode(region: str, city: str, district: str = "") -> tuple[float, float] | None:
    query = " ".join(p for p in [district, city, region] if p)
    if not query:
        return None
    data = session.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "json", "limit": 1},
        timeout=GEOCODE_TIMEOUT,
    ).json()
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None


@reverse_geocoder("nominatim")
def _reverse(lat: float, lon: float) -> dict | None:
    data = session.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": lat, "lon": lon, "format": "json",
                "zoom": 14, "accept-language": "zh"},
        timeout=GEOCODE_TIMEOUT,
    ).json()
    if "error" in data:
        return None
    addr = data.get("address", {})
    return {
        "country": addr.get("country", ""),
        "region": addr.get("state", ""),
        "city": (addr.get("city") or addr.get("town")
                 or addr.get("municipality") or ""),
        "district": (addr.get("city_district") or addr.get("suburb")
                     or addr.get("county") or addr.get("borough") or ""),
    }
