"""ipapi.co — 英文, 城市级 + 坐标."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import translate_country, translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("ipapi.co", weight=5)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://ipapi.co/{ip}/json/",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    if resp.get("error"):
        return None
    return GeoInfo(
        ip=ip,
        lat=resp.get("latitude"), lon=resp.get("longitude"),
        country=translate_country(resp.get("country_code", "")),
        region=resp.get("region", ""),
        city=resp.get("city", ""),
        isp=translate_isp(resp.get("org", "")),
    )
