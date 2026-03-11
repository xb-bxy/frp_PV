"""业务服务层 — BanManager / EventLog / ConnectionTracker"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

from flask_socketio import SocketIO

from config import ConfigManager
from geo import GeoService
from models import ConnectionRecord, RingLog


# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════

_IP_V4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def is_valid_ipv4(ip: str) -> bool:
    """验证 IPv4 地址格式"""
    return bool(_IP_V4_RE.match(ip))


def parse_remote_ip(addr: str) -> str:
    """从 frps 提供的 remote_addr 中提取纯 IP (兼容 IPv4 / IPv6)"""
    if not addr:
        return ""
    if addr.startswith("["):           # [::1]:port
        return addr.split("]")[0][1:]
    if ":" in addr:                    # 1.2.3.4:port
        return addr.rsplit(":", 1)[0]
    return addr


# ═══════════════════════════════════════════════════════════
#  封禁管理器
# ═══════════════════════════════════════════════════════════


class BanManager:
    """IP 封禁列表 + 滑动窗口自动封禁"""

    def __init__(self, cfg: ConfigManager) -> None:
        self._cfg = cfg
        self._lock = Lock()
        self._banned: set[str] = set(cfg.get("banned_ips", []))
        self._windows: dict[str, list[float]] = defaultdict(list)
        self.blocked_count: int = 0

    # ── 查询 ──

    @property
    def banned_set(self) -> set[str]:
        return self._banned

    def is_banned(self, ip: str) -> bool:
        return ip in self._banned

    def sorted_list(self) -> list[str]:
        return sorted(self._banned)

    # ── 操作 ──

    def ban(self, ip: str) -> None:
        self._banned.add(ip)
        self._persist()

    def unban(self, ip: str) -> None:
        self._banned.discard(ip)
        self._persist()

    def increment_blocked(self) -> int:
        self.blocked_count += 1
        return self.blocked_count

    # ── 自动封禁 ──

    def check_auto_ban(self, ip: str, proxy: str, country: str) -> bool:
        """滑动窗口频率检测; 返回 True = 已触发封禁"""
        ab = self._cfg.get("auto_ban", {})
        if not ab.get("enabled", False):
            return False
        if proxy in ab.get("whitelist_modules", []):
            return False
        if ip in ab.get("whitelist_ips", []):
            return False

        home = self._cfg.get("home_country", "中国")
        if ab.get("foreign_only", True) and country == home:
            return False

        limit_sec = ab.get("threshold_seconds", 60)
        limit_count = ab.get("threshold_count", 10)
        now = time.time()

        with self._lock:
            window = self._windows[ip]
            window.append(now)
            while window and now - window[0] > limit_sec:
                window.pop(0)
            if len(window) < limit_count:
                return False
            hit = len(window)
            window.clear()
            self._banned.add(ip)
            self._persist()
            self.blocked_count += 1

        print(f"⚠️ 自动封禁: {ip} ({limit_sec}s 内连接 {proxy} 达 {hit} 次)")
        return True

    def _persist(self) -> None:
        self._cfg.set("banned_ips", sorted(self._banned))
        self._cfg.save()


# ═══════════════════════════════════════════════════════════
#  事件日志缓存
# ═══════════════════════════════════════════════════════════


class EventLog:
    """统一日志缓存, 所有事件 (conn/disconn/sys/blocked) 共享单一时间线"""

    def __init__(self, sio: SocketIO, maxlen: int = 500) -> None:
        self._sio = sio
        self._log = RingLog(maxlen)

    def push(self, kind: str, data: dict) -> None:
        self._log.append({"kind": kind, "data": data})

    def push_sys(self, msg: str, log_type: str = "ban", desc: str = "",
                 ip: str = "", proxy: str = "", reason: str = "") -> None:
        entry = {"msg": msg, "type": log_type, "desc": desc,
                 "ip": ip, "proxy": proxy, "reason": reason,
                 "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.push("sys", entry)
        self._sio.emit("sys_log", entry)

    def log_blocked(self, ip: str, proxy: str, reason: str,
                    desc: str = "", country: str = "",
                    lat: float = None, lon: float = None) -> dict:
        rec = {
            "ip": ip, "proxy": proxy, "reason": reason,
            "desc": desc, "country": country,
            "time": int(time.time()),
        }
        if lat is not None and lon is not None:
            rec["lat"] = lat
            rec["lon"] = lon
        self.push("blocked", rec)
        return rec

    @property
    def snapshot(self) -> list[dict]:
        return self._log.snapshot

    @property
    def blocked_list(self) -> list[dict]:
        return [e["data"] for e in self._log.snapshot if e["kind"] == "blocked"]


# ═══════════════════════════════════════════════════════════
#  连接追踪器
# ═══════════════════════════════════════════════════════════


class ConnectionTracker:
    """聚合所有用户连接, 按 (ip, module) 去重累加;
    按 remote_addr 精确追踪活跃连接"""

    def __init__(self, geo: GeoService, sio: SocketIO,
                 event_log: EventLog) -> None:
        self._geo = geo
        self._sio = sio
        self._elog = event_log
        self._lock = Lock()
        self._records: list[dict] = []
        self._index: dict[tuple[str, str], dict] = {}
        self._active: dict[str, dict] = {}

    @property
    def all_records(self) -> list[dict]:
        return self._records

    @property
    def active_count(self) -> int:
        return len(self._active)

    def record(self, ip: str, module: str, remote_addr: str) -> None:
        """地理查询 → 内存聚合 → WebSocket 推送"""
        geo = self._geo.lookup(ip)
        key = (ip, module)
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            if key not in self._index:
                rec = ConnectionRecord(
                    ip=ip, module=module,
                    lat=geo.lat if geo else None,
                    lon=geo.lon if geo else None,
                    country=geo.country if geo else "",
                    desc=geo.desc if geo else "",
                    time=now,
                ).to_dict()
                self._index[key] = rec
                self._records.append(rec)
                is_new = True
            else:
                rec = self._index[key]
                rec["count"] = rec.get("count", 1) + 1
                rec["time"] = now
                # 回填: 首次无经纬度 → 后续查询补全
                if geo and rec.get("lat") is None and geo.lat is not None:
                    rec["lat"] = geo.lat
                    rec["lon"] = geo.lon
                    rec["desc"] = geo.desc
                    rec["country"] = geo.country
                is_new = False
            is_active = remote_addr in self._active

        if is_new:
            self._sio.emit("new_ip", rec)
            self._elog.push("conn", rec)
        else:
            self._sio.emit("update_ip", rec)
            self._elog.push("conn", {
                "ip": rec["ip"], "module": rec["module"],
                "desc": rec.get("desc", ""), "time": rec["time"],
            })

        if is_active:
            self._sio.emit("connection_opened", {
                "ip": ip, "module": module, "active": self.active_count,
                "remote_addr": remote_addr,
                "desc": geo.desc if geo else "",
                "country": geo.country if geo else "",
            })

    @property
    def active_list(self) -> list[dict]:
        """当前所有活跃连接的快照 (供前端初始化)"""
        now = time.time()
        result = []
        for addr, info in list(self._active.items()):
            geo = self._geo.get_cached(info["ip"])
            result.append({
                "ip": info["ip"],
                "module": info["proxy"],
                "remote_addr": addr,
                "since": round(info["time"]),
                "elapsed": round(now - info["time"], 1),
                "desc": geo.desc if geo else "",
                "country": geo.country if geo else "",
            })
        return result

    def open_connection(self, ip: str, proxy: str, remote_addr: str) -> None:
        """标记一个活跃连接 (仅记录, 不 emit)"""
        self._active[remote_addr] = {
            "ip": ip, "proxy": proxy, "time": time.time(),
        }

    def close_connection(self, ip: str, proxy: str, remote_addr: str) -> None:
        """关闭一个活跃连接 (CloseUserConn 时调用)"""
        info = self._active.pop(remote_addr, None)
        duration = round(time.time() - info["time"], 3) if info else None
        geo = self._geo.get_cached(ip)
        rec = {
            "ip": ip, "module": proxy, "remote_addr": remote_addr,
            "duration": duration,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "desc": geo.desc if geo else "",
            "country": geo.country if geo else "",
            "active": len(self._active),
        }
        self._elog.push("disconn", rec)
        self._sio.emit("connection_closed", rec)
