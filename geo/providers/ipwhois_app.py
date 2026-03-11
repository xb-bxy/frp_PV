"""ipwhois.app — 中文, 城市级 + 坐标 + ISP."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import strip_country_prefix, translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("ipwhois", weight=5)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://ipwhois.app/json/{ip}?lang=zh-CN",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    if resp.get("success") is False:
        return None
    country = resp.get("country", "")
    return GeoInfo(
        ip=ip,
        lat=resp.get("latitude"), lon=resp.get("longitude"),
        country=country,
        region=strip_country_prefix(country, resp.get("region", "")),
        city=resp.get("city", ""),
        isp=translate_isp(resp.get("isp", "")),
    )
