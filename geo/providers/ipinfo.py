"""ipinfo.io — 英文, 城市级 + 坐标 + ASN."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import translate_country, translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("ipinfo", weight=6)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://ipinfo.io/{ip}/json",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    if "bogon" in resp:
        return None

    lat = lon = None
    loc = resp.get("loc", "")
    if "," in loc:
        lat_s, lon_s = loc.split(",", 1)
        lat, lon = float(lat_s), float(lon_s)

    org = resp.get("org", "")
    isp = org.split(" ", 1)[1] if org.startswith("AS") and " " in org else org

    return GeoInfo(
        ip=ip, lat=lat, lon=lon,
        country=translate_country(resp.get("country", "")),
        region=resp.get("region", ""),
        city=resp.get("city", ""),
        isp=translate_isp(isp),
    )
