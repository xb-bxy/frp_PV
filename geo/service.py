"""GeoService — 多源聚合 IP 地理定位, 流水线式分阶段处理."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Callable

import requests as _requests

from geo.breaker import CircuitBreaker
from geo.config import (
    BREAKER_GEOCODER, BREAKER_PROVIDER,
    CACHE_ACTIVE_TTL, CACHE_FILE, CACHE_INCOMPLETE_TTL,
    CACHE_SAVE_INTERVAL, CACHE_TTL,
    COORD_AGREE_BONUS, COORD_AGREE_MAX, COORD_AGREE_THRESHOLD,
    COORD_CITY_MATCH_BONUS, COORD_DISTRICT_BONUS, COORD_FWD_DISTRICT_BONUS,
    COUNTRY_NAMES, GEOCODE_WAIT_TIMEOUT,
    MAX_WORKERS, MMDB_PATH,
    PRIVATE_PREFIXES, PROVIDER_WAIT_TIMEOUT,
)
from geo.formatting import norm_admin
from geo.models import GeoInfo
from geo.providers.geolite2 import GeoLite2Provider
from geo.registry import get_fwd_geocoders, get_providers, get_rev_geocoders

log = logging.getLogger(__name__)


def _is_cjk(s: str) -> bool:
    """字符串中是否含有中日韩字符."""
    return any('\u4e00' <= c <= '\u9fff' for c in s)


# ── 纯函数: 国家投票 ──────────────────────────────────────


def _vote_country(results: dict[str, GeoInfo | None]) -> str:
    """多源国家投票, 取出现次数最多的."""
    votes: dict[str, int] = {}
    for geo in results.values():
        if geo and geo.country:
            key = norm_admin(geo.country)
            votes[key] = votes.get(key, 0) + 1
    if not votes:
        return ""
    winner = max(votes, key=votes.get)
    # 优先返回中文, 否则返回第一个匹配
    fallback = ""
    for geo in results.values():
        if geo and geo.country and norm_admin(geo.country) == winner:
            if _is_cjk(geo.country):
                return geo.country
            if not fallback:
                fallback = geo.country
    return fallback or winner


# ── 纯函数: 文本字段投票 ──────────────────────────────────


def _vote_field(candidates: list[tuple[str, int]]) -> str:
    """加权投票选出最佳文本值.

    candidates: [(value, weight), ...]
    按 norm_admin 归一化分组, 组内权重求和, 取最高分组的最佳字符串.
    组内优先选中文, 其次选最高权重.
    """
    if not candidates:
        return ""
    groups: dict[str, list[tuple[str, int]]] = {}
    totals: dict[str, int] = {}
    for val, w in candidates:
        key = norm_admin(val)
        groups.setdefault(key, []).append((val, w))
        totals[key] = totals.get(key, 0) + w
    best_key = max(totals, key=totals.get)
    entries = groups[best_key]
    # 组内: 优先中文, 其次最高权重
    cjk = [(v, w) for v, w in entries if _is_cjk(v)]
    pool = cjk or entries
    return max(pool, key=lambda x: x[1])[0]


# ── 纯函数: 坐标评分 ──────────────────────────────────────


def _best_coordinates(
    candidates: list[list],
    city_match_names: set[str] | None = None,
) -> tuple[float, float]:
    """对所有坐标候选项评分, 返回最优 (lat, lon).

    每项: [lat, lon, weight, name, has_district]
    city_match_names: 与投票城市一致的 provider 名集合, 给予额外加分.
    """
    scored: list[tuple[float, float, float]] = []
    for i, (lat_i, lon_i, w_i, name_i, has_dist) in enumerate(candidates):
        bonus = COORD_DISTRICT_BONUS if has_dist else 0
        if city_match_names and name_i in city_match_names:
            bonus += COORD_CITY_MATCH_BONUS
        agree = 0
        for j, (lat_j, lon_j, *_) in enumerate(candidates):
            if i != j and (abs(lat_i - lat_j) < COORD_AGREE_THRESHOLD
                           and abs(lon_i - lon_j) < COORD_AGREE_THRESHOLD):
                agree += COORD_AGREE_BONUS
        scored.append((lat_i, lon_i, w_i + bonus + min(agree, COORD_AGREE_MAX)))
    best = max(scored, key=lambda x: x[2])
    return best[0], best[1]


# ═══════════════════════════════════════════════════════════
#  GeoService
# ═══════════════════════════════════════════════════════════


class GeoService:
    """多源并发 IP 地理定位, 带持久化缓存和熔断器."""

    def __init__(self, *,
                 mmdb_path: Path | str | None = None,
                 cache_path: Path | str | None = None) -> None:
        self._lock = Lock()
        self._cache: dict[str, GeoInfo | None] = {}
        self._dirty = 0
        self._pending: dict[str, Future] = {}

        self._cache_path = Path(cache_path) if cache_path else CACHE_FILE
        self._load_cache()

        self._geolite2 = GeoLite2Provider(
            Path(mmdb_path) if mmdb_path else MMDB_PATH)

        self._pool = ThreadPoolExecutor(
            max_workers=MAX_WORKERS, thread_name_prefix="geo")

        # 为所有已注册组件创建独立熔断器
        self._breakers: dict[str, CircuitBreaker] = {}
        bp, bg = BREAKER_PROVIDER, BREAKER_GEOCODER
        for p in get_providers():
            self._breakers[p.name] = CircuitBreaker(
                p.name, max_failures=bp["max_failures"],
                cooldown=bp["cooldown"])
        for g in (*get_fwd_geocoders(), *get_rev_geocoders()):
            self._breakers[g.name] = CircuitBreaker(
                g.name, max_failures=bg["max_failures"],
                cooldown=bg["cooldown"])

    # ── 缓存持久化 ────────────────────────────────────────

    def _load_cache(self) -> None:
        if not self._cache_path.exists():
            return
        try:
            raw = json.loads(self._cache_path.read_text("utf-8"))
            now = time.time()
            for ip, fields in raw.items():
                if fields is None:
                    self._cache[ip] = None
                else:
                    fields.setdefault("updated_at", now)
                    fields.setdefault("last_active", 0.0)
                    self._cache[ip] = GeoInfo(**fields)
            log.info("Cache loaded: %d entries from %s",
                     len(self._cache), self._cache_path)
        except Exception as e:
            log.warning("Cache load failed: %s", e)

    def save_cache(self) -> None:
        with self._lock:
            snapshot = dict(self._cache)
            self._dirty = 0
        data = {ip: asdict(g) if g else None for ip, g in snapshot.items()}
        try:
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self._cache_path)
        except Exception as e:
            log.warning("Cache save failed: %s", e)

    def _maybe_save(self) -> None:
        if self._dirty >= CACHE_SAVE_INTERVAL:
            self.save_cache()

    # ── 公共 API ──────────────────────────────────────────

    def lookup(self, ip: str) -> GeoInfo | None:
        """同步查询, 命中缓存则直接返回."""
        now = time.time()
        cached = self._cache.get(ip)
        if cached is not None:
            # 残缺结果 (有文字无坐标) 用更短 TTL, 尽快重试
            incomplete = (cached.lat is None
                         and (cached.country or cached.region))
            if incomplete:
                ttl = CACHE_INCOMPLETE_TTL
            else:
                ttl = (CACHE_ACTIVE_TTL
                       if (now - cached.last_active) < CACHE_ACTIVE_TTL
                       else CACHE_TTL)
            if cached.updated_at > 0 and (now - cached.updated_at) < ttl:
                cached.last_active = now
                return cached
        elif ip in self._cache:  # None → 私有 IP
            return None

        if ip.startswith(PRIVATE_PREFIXES):
            self._cache[ip] = None
            return None

        result = self._multi_source_lookup(ip)
        if result:
            result.updated_at = now
            result.last_active = now
        with self._lock:
            self._cache[ip] = result
            self._dirty += 1
        self._maybe_save()
        return result

    def lookup_async(self, ip: str,
                     callback: Callable[..., None] | None = None,
                     ) -> Future:
        """异步查询, 相同 IP 的并发请求自动去重."""
        def _task():
            result = self.lookup(ip)
            self._pending.pop(ip, None)
            if callback:
                try:
                    callback(ip, result)
                except Exception as e:
                    log.warning("Callback error %s: %s", ip, e)
            return result

        with self._lock:
            if ip in self._cache:
                fut: Future = Future()
                fut.set_result(self._cache[ip])
                if callback:
                    try:
                        callback(ip, self._cache[ip])
                    except Exception:
                        pass
                return fut

            if ip in self._pending:
                existing = self._pending[ip]
                if callback:
                    existing.add_done_callback(
                        lambda f, cb=callback: cb(ip, f.result()))
                return existing

            fut = self._pool.submit(_task)
            self._pending[ip] = fut
            return fut

    def get_cached(self, ip: str) -> GeoInfo | None:
        return self._cache.get(ip)

    def detect_server_location(self) -> GeoInfo | None:
        """自动检测服务器公网 IP 并查询地理信息."""
        apis = [
            ("https://api.ipify.org?format=json", "ip"),
            ("https://ipinfo.io/json", "ip"),
            ("https://api.ip.sb/geoip", "ip"),
        ]
        for url, key in apis:
            try:
                public_ip = _requests.get(url, timeout=5).json().get(key)
                if public_ip:
                    log.info("Server public IP: %s", public_ip)
                    return self.lookup(public_ip)
            except Exception:
                continue
        log.warning("Failed to detect server public IP")
        return None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
        self.save_cache()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    # ── 熔断器守卫调用 ────────────────────────────────────

    def _guarded_call(self, name: str, fn, *args):
        """带熔断器保护的函数调用."""
        cb = self._breakers.get(name)
        if cb and not cb.allow:
            return None
        result = fn(*args)
        if cb:
            if result is not None:
                cb.record_success()
            else:
                cb.record_failure()
        return result

    # ── 多源查询流水线 ────────────────────────────────────

    def _multi_source_lookup(self, ip: str) -> GeoInfo | None:
        merged = GeoInfo(ip=ip)
        coords: list[list] = []

        # 阶段 1: 并发查询所有 IP provider
        results = self._query_providers(ip)

        # 阶段 2: 国家投票 + 字段合并
        winning = _vote_country(results)
        has_text_no_coords = self._merge_provider_results(
            results, merged, coords, winning)

        # 计算与投票城市一致的 provider 名集合 (逆向编码改写前)
        city_match_names: set[str] = set()
        if merged.city:
            voted_key = norm_admin(merged.city)
            for p in get_providers():
                geo = results.get(p.name)
                if geo and geo.city and norm_admin(geo.city) == voted_key:
                    city_match_names.add(p.name)

        # 阶段 3: GeoLite2 离线补充
        self._enrich_geolite2(ip, merged, coords, winning)

        # 阶段 4: 正向地理编码 (文字 → 坐标)
        if has_text_no_coords and (merged.region or merged.city):
            self._forward_geocode(merged, coords)

        # 阶段 5: 逆向地理编码 (坐标 → 区级)
        self._reverse_geocode(merged, coords)

        # 阶段 6: 选择最优坐标
        if coords:
            merged.lat, merged.lon = _best_coordinates(
                coords, city_match_names)

        if not (merged.country or merged.region or merged.lat is not None):
            return None
        return merged

    # ── 阶段 1: 并发查询 provider ─────────────────────────

    def _query_providers(self, ip: str) -> dict[str, GeoInfo | None]:
        providers = get_providers()
        active = [p for p in providers
                  if self._breakers.get(p.name,
                                        CircuitBreaker("_")).allow]
        if not active:
            return {}

        results: dict[str, GeoInfo | None] = {}
        pool = ThreadPoolExecutor(
            max_workers=len(active), thread_name_prefix="geo_q")
        try:
            fs = {pool.submit(self._guarded_call, p.name, p.fn, ip): p
                  for p in active}
            done, pending = wait(fs.keys(), timeout=PROVIDER_WAIT_TIMEOUT)
            for f in pending:
                f.cancel()
            for f in done:
                p = fs[f]
                try:
                    results[p.name] = f.result()
                except Exception as e:
                    log.warning("[%s] exception: %s", p.name, e)
        finally:
            pool.shutdown(wait=False)
        return results

    # ── 阶段 2: 合并 provider 结果 ────────────────────────

    def _merge_provider_results(
        self,
        results: dict[str, GeoInfo | None],
        merged: GeoInfo,
        coords: list[list],
        winning_country: str,
    ) -> bool:
        """加权投票合并文本字段 + 收集坐标候选. 返回 True = 有文字但无坐标."""
        has_text_no_coords = False
        field_cands: dict[str, list[tuple[str, int]]] = {
            "region": [], "city": [], "district": [],
        }
        isp_cands: list[tuple[str, int]] = []

        for p in get_providers():
            geo = results.get(p.name)
            if not geo:
                continue
            # 仅采纳与投票国家一致的 provider 文本
            country_ok = (not geo.country or not winning_country
                          or norm_admin(geo.country) == norm_admin(winning_country))
            if country_ok:
                for attr in ("region", "city", "district"):
                    val = getattr(geo, attr)
                    if val:
                        field_cands[attr].append((val, p.weight))
            if geo.isp:
                isp_cands.append((geo.isp, p.weight))
            # 坐标始终收集
            if geo.lat is not None and geo.lon is not None:
                coords.append(
                    [geo.lat, geo.lon, p.weight, p.name,
                     bool(geo.district)])
            elif geo.region or geo.city or geo.district:
                has_text_no_coords = True

        # 国家
        if winning_country:
            merged.country = winning_country
        # 文本字段: 加权投票
        for attr in ("region", "city", "district"):
            voted = _vote_field(field_cands[attr])
            if voted:
                setattr(merged, attr, voted)
        # district 一致性: 若没有 provider 同时拥有投票 city 和投票 district, 清除 district
        if merged.city and merged.district:
            ck = norm_admin(merged.city)
            dk = norm_admin(merged.district)
            consistent = False
            for p in get_providers():
                geo = results.get(p.name)
                if (geo and geo.city and norm_admin(geo.city) == ck
                        and geo.district and norm_admin(geo.district) == dk):
                    consistent = True
                    break
            if not consistent:
                merged.district = ""
        # ISP: 优先中文, 最高权重
        if isp_cands:
            cjk_isps = [(v, w) for v, w in isp_cands if _is_cjk(v)]
            pool = cjk_isps or isp_cands
            merged.isp = max(pool, key=lambda x: x[1])[0]

        return has_text_no_coords

    # ── 阶段 3: GeoLite2 离线补充 ─────────────────────────

    def _enrich_geolite2(
        self, ip: str, merged: GeoInfo,
        coords: list[list], winning_country: str,
    ) -> None:
        if not self._geolite2.available:
            return
        local = self._geolite2.lookup(ip)
        if not local:
            return
        if local.lat is not None and local.lon is not None:
            coords.append(
                [local.lat, local.lon, 3, "geolite2", False])
        country_ok = (not local.country or not winning_country
                      or norm_admin(local.country) == norm_admin(winning_country))
        if country_ok:
            if not merged.country and local.country:
                merged.country = local.country
            if not merged.region and local.region:
                merged.region = local.region
        if not merged.city and local.city:
            merged.city = local.city

    # ── 阶段 4: 正向地理编码 ──────────────────────────────

    def _forward_geocode(self, merged: GeoInfo, coords: list[list]) -> None:
        geocoders = get_fwd_geocoders()
        active = [g for g in geocoders
                  if self._breakers.get(g.name,
                                        CircuitBreaker("_")).allow]
        if not active:
            return

        pool = ThreadPoolExecutor(
            max_workers=len(active), thread_name_prefix="geo_fwd")
        try:
            fs = {
                pool.submit(
                    self._guarded_call, g.name, g.fn,
                    merged.region, merged.city, merged.district,
                ): g
                for g in active
            }
            done, pending = wait(fs.keys(), timeout=GEOCODE_WAIT_TIMEOUT)
            for f in pending:
                f.cancel()
            for f in done:
                g = fs[f]
                try:
                    result = f.result()
                except Exception:
                    result = None
                if result:
                    w = g.weight + (
                        COORD_FWD_DISTRICT_BONUS if merged.district else 0)
                    coords.append(
                        [result[0], result[1], w,
                         f"fwd_{g.name}", True])
        finally:
            pool.shutdown(wait=False)

    # ── 阶段 5: 逆向地理编码 ──────────────────────────────

    def _reverse_geocode(self, merged: GeoInfo, coords: list[list]) -> None:
        no_dist = [i for i, c in enumerate(coords) if not c[4]]
        if not no_dist:
            return
        # 选权重最高的无区级坐标
        rep_i = max(no_dist, key=lambda i: coords[i][2])
        rep_lat, rep_lon = coords[rep_i][0], coords[rep_i][1]

        geocoders = get_rev_geocoders()
        active = [g for g in geocoders
                  if self._breakers.get(g.name,
                                        CircuitBreaker("_")).allow]
        if not active:
            return

        pool = ThreadPoolExecutor(
            max_workers=len(active), thread_name_prefix="geo_rev")
        try:
            fs = {
                pool.submit(
                    self._guarded_call, g.name, g.fn,
                    rep_lat, rep_lon,
                ): g.name
                for g in active
            }
            done, pending = wait(fs.keys(), timeout=GEOCODE_WAIT_TIMEOUT)
            for f in pending:
                f.cancel()

            # 按注册顺序 (优先级) 处理结果
            got_district = False
            for g in geocoders:
                for f in done:
                    if fs.get(f) != g.name:
                        continue
                    try:
                        addr = f.result()
                    except Exception:
                        addr = None
                    if not addr or not addr.get("district"):
                        continue

                    got_district = True
                    rev_country = COUNTRY_NAMES.get(
                        addr.get("country", ""), addr.get("country", ""))
                    if (rev_country and merged.country
                            and norm_admin(rev_country) != norm_admin(merged.country)):
                        merged.country = rev_country
                        merged.region = addr.get("region", "")
                        merged.city = addr.get("city", "")
                        merged.district = addr["district"]
                    else:
                        # 空则填, 或中文覆盖英文
                        rev_d = addr["district"]
                        if not merged.district or (
                                _is_cjk(rev_d) and not _is_cjk(merged.district)):
                            merged.district = rev_d
                        rev_c = addr.get("city", "")
                        if rev_c and (not merged.city or (
                                _is_cjk(rev_c) and not _is_cjk(merged.city))):
                            merged.city = rev_c
                        rev_r = addr.get("region", "")
                        if rev_r and (not merged.region or (
                                _is_cjk(rev_r) and not _is_cjk(merged.region))):
                            merged.region = rev_r
                        if not merged.country and rev_country:
                            merged.country = rev_country
                    break
                if got_district:
                    break

            # 标记附近坐标为有区级信息
            if got_district:
                for i in no_dist:
                    c = coords[i]
                    if (abs(c[0] - rep_lat) < COORD_AGREE_THRESHOLD
                            and abs(c[1] - rep_lon) < COORD_AGREE_THRESHOLD):
                        c[4] = True
        finally:
            pool.shutdown(wait=False)
