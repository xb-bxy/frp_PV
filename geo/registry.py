"""装饰器注册表 — 自动捕获异常, provider/geocoder 只写 happy path."""

from __future__ import annotations

import logging
from functools import wraps
from typing import Callable, NamedTuple, Optional

from geo.models import GeoInfo

log = logging.getLogger(__name__)


class ProviderEntry(NamedTuple):
    name: str
    weight: int
    fn: Callable[[str], Optional[GeoInfo]]


class FwdGeocoderEntry(NamedTuple):
    name: str
    weight: int
    fn: Callable[..., Optional[tuple[float, float]]]


class RevGeocoderEntry(NamedTuple):
    name: str
    fn: Callable[[float, float], Optional[dict]]


_providers: list[ProviderEntry] = []
_fwd_geocoders: list[FwdGeocoderEntry] = []
_rev_geocoders: list[RevGeocoderEntry] = []


def ip_provider(name: str, weight: int = 1):
    """注册 IP 查询 provider. 异常自动捕获并记录."""
    def decorator(fn):
        @wraps(fn)
        def safe(ip: str) -> Optional[GeoInfo]:
            try:
                return fn(ip)
            except Exception as e:
                log.warning("[%s] %s: %s", name, ip, e)
                return None
        _providers.append(ProviderEntry(name, weight, safe))
        return safe
    return decorator


def forward_geocoder(name: str, weight: int = 4):
    """注册正向地理编码器 (地址 → 坐标)."""
    def decorator(fn):
        @wraps(fn)
        def safe(*args):
            try:
                return fn(*args)
            except Exception:
                return None
        _fwd_geocoders.append(FwdGeocoderEntry(name, weight, safe))
        return safe
    return decorator


def reverse_geocoder(name: str):
    """注册逆地理编码器 (坐标 → 地址)."""
    def decorator(fn):
        @wraps(fn)
        def safe(lat: float, lon: float) -> Optional[dict]:
            try:
                return fn(lat, lon)
            except Exception:
                return None
        _rev_geocoders.append(RevGeocoderEntry(name, safe))
        return safe
    return decorator


def get_providers() -> list[ProviderEntry]:
    return list(_providers)


def get_fwd_geocoders() -> list[FwdGeocoderEntry]:
    return list(_fwd_geocoders)


def get_rev_geocoders() -> list[RevGeocoderEntry]:
    return list(_rev_geocoders)
