"""photon (komoot) — 正向 + 逆向地理编码, 基于 OSM."""

from __future__ import annotations

from geo.config import GEOCODE_TIMEOUT
from geo.providers._http import session
from geo.registry import forward_geocoder, reverse_geocoder


@forward_geocoder("photon", weight=4)
def _geocode(region: str, city: str, district: str = "") -> tuple[float, float] | None:
    query = " ".join(p for p in [district, city, region] if p)
    if not query:
        return None
    features = session.get(
        "https://photon.komoot.io/api/",
        params={"q": query, "limit": 1},
        timeout=GEOCODE_TIMEOUT,
    ).json().get("features", [])
    if features:
        lon, lat = features[0]["geometry"]["coordinates"]
        return float(lat), float(lon)
    return None


@reverse_geocoder("photon")
def _reverse(lat: float, lon: float) -> dict | None:
    features = session.get(
        "https://photon.komoot.io/reverse",
        params={"lat": lat, "lon": lon, "lang": "zh"},
        timeout=GEOCODE_TIMEOUT,
    ).json().get("features", [])
    if not features:
        return None
    p = features[0].get("properties", {})
    return {
        "country": p.get("country", ""),
        "region": p.get("state", ""),
        "city": p.get("city", ""),
        "district": p.get("county") or p.get("district") or "",
    }
