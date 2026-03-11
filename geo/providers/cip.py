"""cip.cc — 纯文本, 含 ISP, 无坐标."""

from __future__ import annotations

import re

from geo.config import PROVIDER_TIMEOUT
from geo.formatting import translate_isp
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider

_PATTERN = re.compile(
    r"地址\s*:\s*(.+?)$.*?运营商\s*:\s*(.+?)$",
    re.MULTILINE | re.DOTALL,
)


@ip_provider("cip.cc", weight=2)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://www.cip.cc/{ip}",
        timeout=PROVIDER_TIMEOUT,
        headers={"User-Agent": "curl/7.0"},
    )
    m = _PATTERN.search(resp.text.strip())
    if not m:
        return None
    parts = m.group(1).strip().split()
    isp_raw = m.group(2).strip()
    return GeoInfo(
        ip=ip,
        country=parts[0] if parts else "",
        region=parts[1] if len(parts) > 1 else "",
        city=parts[2] if len(parts) > 2 else "",
        district=parts[3] if len(parts) > 3 else "",
        isp=translate_isp(isp_raw) or isp_raw,
    )
