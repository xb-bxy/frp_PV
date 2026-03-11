"""ipwho.is — 城市级 + 坐标 + ISP, 中文."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import strip_country_prefix, translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("ipwho", weight=5)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"http://ipwho.is/{ip}?lang=zh-CN",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    if not resp.get("success"):
        return None
    country = resp.get("country", "")
    conn = resp.get("connection", {})
    return GeoInfo(
        ip=ip,
        lat=resp.get("latitude"), lon=resp.get("longitude"),
        country=country,
        region=strip_country_prefix(country, resp.get("region", "")),
        city=resp.get("city", ""),
        isp=translate_isp(conn.get("isp", "")),
    )
