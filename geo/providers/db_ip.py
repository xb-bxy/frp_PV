"""db-ip.com — 城市级, 区级嵌在括号里, 无坐标."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import split_city_district, translate_country
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("db-ip", weight=2)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://api.db-ip.com/v2/free/{ip}",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    if resp.get("error"):
        return None
    city, district = split_city_district(resp.get("city", ""))
    return GeoInfo(
        ip=ip,
        country=translate_country(resp.get("countryCode", "")),
        city=city, district=district,
    )
