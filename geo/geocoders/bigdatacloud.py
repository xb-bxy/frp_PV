"""BigDataCloud — 逆向地理编码, 免费, 中文, 区级."""

from __future__ import annotations

from geo.config import GEOCODE_TIMEOUT
from geo.formatting import translate_country
from geo.providers._http import session
from geo.registry import reverse_geocoder


@reverse_geocoder("bigdata")
def _reverse(lat: float, lon: float) -> dict | None:
    data = session.get(
        "https://api.bigdatacloud.net/data/reverse-geocode-client",
        params={"latitude": lat, "longitude": lon,
                "localityLanguage": "zh-Hans"},
        timeout=GEOCODE_TIMEOUT,
    ).json()
    return {
        "country": translate_country(data.get("countryName", "")),
        "region": data.get("principalSubdivision", ""),
        "city": data.get("city", ""),
        "district": data.get("locality", ""),
    }
