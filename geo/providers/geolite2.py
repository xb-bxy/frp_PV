"""GeoLite2 离线 MMDB 查询 (城市级, 无 ISP)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from geo.models import GeoInfo

log = logging.getLogger(__name__)

try:
    import geoip2.database
    import geoip2.errors
    _HAS_GEOIP2 = True
except ImportError:
    _HAS_GEOIP2 = False


class GeoLite2Provider:
    """离线 MMDB IP 查询."""

    def __init__(self, path: Path) -> None:
        self._reader = None
        if _HAS_GEOIP2 and path.exists():
            try:
                self._reader = geoip2.database.Reader(str(path))
                log.info("Loaded GeoLite2: %s", path)
            except Exception as e:
                log.warning("GeoLite2 load failed: %s", e)

    @property
    def available(self) -> bool:
        return self._reader is not None

    def lookup(self, ip: str) -> GeoInfo | None:
        if not self._reader:
            return None
        try:
            r = self._reader.city(ip)
            region = ""
            if r.subdivisions:
                region = (r.subdivisions.most_specific.names.get("zh-CN")
                          or r.subdivisions.most_specific.name or "")
            return GeoInfo(
                ip=ip,
                lat=r.location.latitude, lon=r.location.longitude,
                country=r.country.names.get("zh-CN") or r.country.name or "",
                region=region,
                city=r.city.names.get("zh-CN") or r.city.name or "",
            )
        except Exception:
            return None
