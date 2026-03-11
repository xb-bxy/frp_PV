"""freeipapi.com — 城市级 + 坐标, 区级嵌在括号里."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import split_city_district, translate_country, translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("freeipapi", weight=6)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://freeipapi.com/api/json/{ip}",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    city, district = split_city_district(resp.get("cityName", ""))
    return GeoInfo(
        ip=ip,
        lat=resp.get("latitude"), lon=resp.get("longitude"),
        country=translate_country(resp.get("countryCode", "")),
        region=resp.get("regionName", ""),
        city=city, district=district,
        isp=translate_isp(resp.get("asnOrganization", "")),
    )
