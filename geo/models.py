"""GeoInfo 数据模型."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from geo.formatting import build_desc


@dataclass
class GeoInfo:
    """IP 地理位置查询结果."""

    lat: Optional[float] = None
    lon: Optional[float] = None
    country: str = ""
    region: str = ""
    city: str = ""
    district: str = ""
    isp: str = ""
    ip: str = ""
    updated_at: float = 0.0
    last_active: float = 0.0

    @property
    def desc(self) -> str:
        return build_desc(
            self.country, self.region, self.city, self.district, self.isp,
        )
