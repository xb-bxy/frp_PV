"""ip2location.io — 1000次/天, 城市级 + 坐标 + ASN."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import translate_country, translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("ip2location", weight=5)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://api.ip2location.io/?ip={ip}",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    return GeoInfo(
        ip=ip,
        lat=resp.get("latitude"), lon=resp.get("longitude"),
        country=translate_country(resp.get("country_code", "")),
        region=resp.get("region_name", ""),
        city=resp.get("city_name", ""),
        isp=translate_isp(resp.get("as", "")),
    )
