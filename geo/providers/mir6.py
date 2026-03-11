"""mir6.com — 区级精度, 含 ISP, 无坐标. 中国 IP 最佳."""

from __future__ import annotations

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("mir6", weight=2)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://api.mir6.com/api/ip_json?ip={ip}",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    if resp.get("code") != 200:
        return None
    d = resp.get("data", {})
    return GeoInfo(
        ip=ip,
        country=(d.get("country") or "").strip(),
        region=(d.get("province") or "").strip(),
        district=(d.get("city") or "").strip(),
        isp=translate_isp((d.get("isp") or "").strip()),
    )
