"""geo — 多源 IP 地理定位包.

Usage::

    from geo import GeoService, GeoInfo

    svc = GeoService()
    info = svc.lookup("114.253.111.241")
    print(info.desc)   # "中国 - 北京市 · 昌平区 联通"
"""

import logging

# 触发 provider / geocoder 自动注册
import geo.providers   # noqa: F401
import geo.geocoders   # noqa: F401

from geo.breaker import CircuitBreaker
from geo.models import GeoInfo
from geo.service import GeoService

__all__ = ["GeoService", "GeoInfo", "CircuitBreaker"]

logging.getLogger(__name__).addHandler(logging.NullHandler())
