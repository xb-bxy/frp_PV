"""ip-api.com — 45req/min, 中文, 区级 + 坐标 + ISP."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import strip_country_prefix, translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("ip-api", weight=8)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"http://ip-api.com/json/{ip}",
        params={"lang": "zh-CN",
                "fields": "status,country,regionName,city,district,lat,lon,isp"},
        timeout=PROVIDER_TIMEOUT,
    ).json()
    if resp.get("status") != "success":
        return None
    country = resp.get("country", "")
    return GeoInfo(
        ip=ip,
        lat=resp.get("lat"), lon=resp.get("lon"),
        country=country,
        region=strip_country_prefix(country, resp.get("regionName", "")),
        city=resp.get("city", ""),
        district=resp.get("district", ""),
        isp=translate_isp(resp.get("isp", "")),
    )
