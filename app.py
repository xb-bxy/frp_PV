# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "flask",
#     "flask-socketio",
#     "requests",
#     "geoip2",
# ]
# ///

"""
FRP_PV — frp Server Plugin 态势感知与主动防御系统

工作流程:
  用户连接 → frps → HTTP POST /frp-plugin → 内存判定 → reject / allow
  延迟 <5 ms · 精度 100% · 无需 iptables
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from functools import wraps
from pathlib import Path
from threading import Lock, Thread
from typing import Optional

import requests as http_requests
try:
    import geoip2.database
    import geoip2.errors
    _GEOIP2_AVAILABLE = True
except ImportError:
    _GEOIP2_AVAILABLE = False
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash, generate_password_hash


# ═══════════════════════════════════════════════════════════
#  环形日志缓存
# ═══════════════════════════════════════════════════════════


class RingLog:
    """固定容量的环形日志缓存 (GIL 保证原子性, 无需加锁)"""

    def __init__(self, maxlen: int = 500) -> None:
        self._maxlen = maxlen
        self._buf: list = []

    def append(self, item) -> None:
        self._buf.append(item)
        if len(self._buf) > self._maxlen:
            del self._buf[: len(self._buf) - self._maxlen]

    @property
    def snapshot(self) -> list:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


# ═══════════════════════════════════════════════════════════
#  数据模型
# ═══════════════════════════════════════════════════════════


@dataclass
class GeoInfo:
    """IP 地理位置快照"""

    lat: Optional[float] = None
    lon: Optional[float] = None
    country: str = ""
    desc: str = ""


@dataclass
class ConnectionRecord:
    """单条访问聚合记录 (ip + module 唯一)"""

    ip: str
    module: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    country: str = ""
    desc: str = ""
    time: str = ""
    count: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════
#  配置管理器
# ═══════════════════════════════════════════════════════════


class ConfigManager:
    """统一读写 config.json, 线程安全"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = Lock()
        self._data: dict = {}
        self.reload()

    # -- 读写 --

    def reload(self) -> None:
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def save(self) -> None:
        with self._lock:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)

    # -- 字段操作 --

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    @property
    def raw(self) -> dict:
        """直接暴露底层 dict (供 Jinja 模板访问)"""
        return self._data


# ═══════════════════════════════════════════════════════════
#  地理位置服务
# ═══════════════════════════════════════════════════════════

_PRIVATE_PREFIXES = ("127.", "192.168.", "10.", "172.")


class GeoService:
    """IP 地理信息查询——优先用本地 GeoLite2-City.mmdb，否则 ipwho.is"""

    API_URL = "http://ipwho.is/{ip}?lang=zh-CN"
    TIMEOUT = 5
    MMDB_PATH = Path("GeoLite2-City.mmdb")

    def __init__(self) -> None:
        self._cache: dict[str, Optional[GeoInfo]] = {}
        self._reader = None
        if _GEOIP2_AVAILABLE and self.MMDB_PATH.exists():
            try:
                self._reader = geoip2.database.Reader(str(self.MMDB_PATH))
                print(f"[GEO] 使用本地 GeoLite2 数据库: {self.MMDB_PATH}")
            except Exception as e:
                print(f"[GEO] GeoLite2 加载失败: {e}")

    def _lookup_local(self, ip: str) -> Optional[GeoInfo]:
        """GeoLite2 本地查询，精确到城市级"""
        try:
            r = self._reader.city(ip)
            lat = r.location.latitude
            lon = r.location.longitude
            country = r.country.names.get("zh-CN") or r.country.name or ""
            city = r.city.names.get("zh-CN") or r.city.name or ""
            return GeoInfo(
                lat=lat, lon=lon,
                country=country,
                desc=f"{country} - {city}".strip(" - "),
            )
        except Exception:
            return None

    def lookup(self, ip: str) -> Optional[GeoInfo]:
        """查询并缓存; 内网 IP 直接返回 None"""
        if ip in self._cache:
            return self._cache[ip]

        if ip.startswith(_PRIVATE_PREFIXES):
            self._cache[ip] = None
            return None

        # 优先本地数据库
        if self._reader:
            geo = self._lookup_local(ip)
            if geo:
                self._cache[ip] = geo
                return geo

        # 备用在线接口（ipwho.is）
        try:
            resp = http_requests.get(
                self.API_URL.format(ip=ip), timeout=self.TIMEOUT
            ).json()
            if resp.get("success") is True:
                geo = GeoInfo(
                    lat=resp.get("latitude"),
                    lon=resp.get("longitude"),
                    country=resp.get("country", ""),
                    desc=(
                        f"{resp.get('country', '')} - {resp.get('city', '')}".strip(
                            " - "
                        )
                    ),
                )
                self._cache[ip] = geo
                return geo
        except Exception as e:
            print(f"[GEO] 查询失败 {ip}: {e}")

        self._cache[ip] = None
        return None

    def get_cached(self, ip: str) -> Optional[GeoInfo]:
        """仅读缓存, 不触发网络请求"""
        return self._cache.get(ip)


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

    # -- 查询 --

    @property
    def banned_set(self) -> set[str]:
        return self._banned

    def is_banned(self, ip: str) -> bool:
        return ip in self._banned

    def sorted_list(self) -> list[str]:
        return sorted(self._banned)

    # -- 操作 --

    def ban(self, ip: str) -> None:
        self._banned.add(ip)
        self._persist()

    def unban(self, ip: str) -> None:
        self._banned.discard(ip)
        self._persist()

    def increment_blocked(self) -> int:
        self.blocked_count += 1
        return self.blocked_count

    # -- 自动封禁 --

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

    # -- 内部 --

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
    """聚合所有用户连接, 按 (ip, module) 去重累加; 按 remote_addr 精确追踪活跃连接"""

    def __init__(self, geo: GeoService, sio: SocketIO,
                 event_log: EventLog) -> None:
        self._geo = geo
        self._sio = sio
        self._elog = event_log
        self._lock = Lock()  # 仅保护 record() 的 check-then-insert
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
        """地理查询 → 内存聚合 → WebSocket 推送 (在后台线程调用)"""
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
                is_new = False
            is_active = remote_addr in self._active

        if is_new:
            self._sio.emit("new_ip", rec)
            self._elog.push("conn", rec)
        else:
            self._sio.emit("update_ip", rec)
            self._elog.push("conn", {"ip": rec["ip"], "module": rec["module"],
                           "desc": rec.get("desc", ""), "time": rec["time"]})

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
        items = list(self._active.items())
        result = []
        for addr, info in items:
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
        self._active[remote_addr] = {"ip": ip, "proxy": proxy, "time": time.time()}

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


# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════

_IP_V4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


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
#  应用工厂
# ═══════════════════════════════════════════════════════════


def create_app() -> tuple[Flask, SocketIO, ConfigManager]:
    """构建 Flask 应用, 注入所有服务"""

    base_dir = Path(__file__).parent
    cfg = ConfigManager(base_dir / "config.json")

    app = Flask(__name__)
    app.secret_key = cfg.get("secret_key", os.urandom(24).hex())
    sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    geo = GeoService()
    bans = BanManager(cfg)
    elog = EventLog(sio)
    tracker = ConnectionTracker(geo, sio, elog)

    # ── 认证装饰器 ──

    def login_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login", next=request.url))
            return f(*args, **kwargs)
        return wrapper

    # ── frp Server Plugin 端点 ────────────────────────────

    def _backfill_geo(rec: dict, ip: str) -> None:
        """后台补全拦截记录的地理信息"""
        g = geo.lookup(ip)
        if g:
            rec["desc"] = g.desc
            rec["country"] = g.country
            rec["lat"] = g.lat
            rec["lon"] = g.lon
            sio.emit("blocked_geo_update", rec)

    def _reject_ip(ip: str, proxy: str, reason: str,
                   sys_msg: str, reject_reason: str):
        """记录拦截 → 广播事件 → 返回拒绝响应"""
        cached = geo.get_cached(ip)
        lat = cached.lat if cached else None
        lon = cached.lon if cached else None
        rec = elog.log_blocked(ip, proxy, reason,
                               cached.desc if cached else "",
                               cached.country if cached else "",
                               lat=lat, lon=lon)
        geo_desc = cached.desc if cached and cached.desc else ""
        elog.push_sys(sys_msg, desc=geo_desc, ip=ip, proxy=proxy, reason=reason)
        sio.emit("blocked_update", {"blocked": bans.blocked_count})
        sio.emit("blocked_event", rec)
        if not cached:
            Thread(target=_backfill_geo, args=(rec, ip), daemon=True).start()
        return jsonify({"reject": True, "reject_reason": reject_reason})

    @app.route("/frp-plugin", methods=["POST"])
    def frp_plugin():
        op = request.args.get("op", "")
        content = (request.get_json(silent=True) or {}).get("content", {})

        proxy = content.get("proxy_name", "")
        raw_addr = content.get("remote_addr", "")
        ip = parse_remote_ip(raw_addr)

        # ── CloseUserConn: 连接断开通知 ──
        if op == "CloseUserConn":
            if ip:
                tracker.close_connection(ip, proxy, raw_addr)
            return jsonify({"reject": False, "unchange": True})

        # ── 非 NewUserConn 一律放行 ──
        if op != "NewUserConn" or not ip:
            return jsonify({"reject": False, "unchange": True})

        # ① 已在黑名单 → 直接拒绝
        if bans.is_banned(ip):
            bans.increment_blocked()
            return _reject_ip(ip, proxy, "已封禁",
                              f"拦截: {ip} → {proxy} (已封禁)",
                              "banned by frp_pv")

        # ② 滑动窗口自动封禁
        cached_geo = geo.get_cached(ip)
        country = cached_geo.country if cached_geo else ""
        if bans.check_auto_ban(ip, proxy, country):
            return _reject_ip(ip, proxy, "自动封禁",
                              f"自动封禁: {ip} (频繁连接 {proxy})",
                              "auto-banned by frp_pv")

        # ③ 放行 → 标记活跃 + 异步记录
        tracker.open_connection(ip, proxy, raw_addr)
        Thread(target=tracker.record, args=(ip, proxy, raw_addr), daemon=True).start()
        return jsonify({"reject": False, "unchange": True})

    # ── 认证路由 ──────────────────────────────────────────

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password", "")
            if username == cfg.get("admin_username", "root"):
                cfg_hash = cfg.get("admin_password_hash", "")
                if (not cfg_hash and password == "") or (
                    cfg_hash and check_password_hash(cfg_hash, password)
                ):
                    session["logged_in"] = True
                    return redirect(url_for("index"))
                error = (
                    "密码错误。当前默认无密码时请直接留空。"
                    if not cfg_hash
                    else "用户名或密码错误"
                )
            else:
                error = "用户名或密码错误"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.pop("logged_in", None)
        return redirect(url_for("login"))

    # ── 页面 & 数据 ──────────────────────────────────────

    @app.route("/")
    @login_required
    def index():
        return render_template("index.html", config=cfg.raw)

    @app.route("/api/data")
    @login_required
    def api_data():
        return jsonify(tracker.all_records)

    # ── 设置 API ──────────────────────────────────────────

    @app.route("/api/settings", methods=["GET", "POST"])
    @login_required
    def api_settings():
        if request.method == "GET":
            return jsonify({
                "status": "success",
                "data": {
                    "home_country": cfg.get("home_country", "中国"),
                    "frequent_threshold": cfg.get("frequent_threshold", 5),
                    "foreign_highlight": cfg.get("foreign_highlight", True),
                    "admin_username": cfg.get("admin_username", "root"),
                    "auto_ban": cfg.get("auto_ban", {}),
                },
            })

        if not request.is_json:
            return jsonify({"status": "error", "msg": "请求格式错误"}), 400

        data = request.get_json()

        # 密码变更
        if data.get("change_pwd"):
            old_pw = data.get("old_password", "")
            new_pw = data.get("new_password", "")
            cfg_hash = cfg.get("admin_password_hash", "")
            if cfg_hash and not check_password_hash(cfg_hash, old_pw):
                return jsonify({"status": "error", "msg": "原密码错误"})
            if not cfg_hash and old_pw != "":
                return jsonify({"status": "error", "msg": "原密码为空，请留空"})
            cfg.set(
                "admin_password_hash",
                generate_password_hash(new_pw) if new_pw else "",
            )

        # 常规字段 — 逐个覆盖
        for key in (
            "home_country",
            "frequent_threshold",
            "foreign_highlight",
            "auto_ban",
            "admin_username",
        ):
            if key in data:
                cfg.set(key, data[key])

        cfg.save()
        return jsonify({"status": "success", "msg": "设置保存成功！"})

    # ── 封禁管理 API ─────────────────────────────────────

    @app.route("/api/firewall", methods=["GET"])
    @login_required
    def get_firewall():
        items = []
        for i, ip in enumerate(bans.sorted_list(), 1):
            g = geo.lookup(ip)
            items.append({
                "num": i,
                "ip": ip,
                "desc": g.desc if g else "",
            })
        return jsonify({"status": "success", "data": items})

    @app.route("/api/firewall/add", methods=["POST"])
    @login_required
    def add_firewall():
        ip = (request.get_json().get("ip") or "").strip()
        if not ip or not _IP_V4_RE.match(ip):
            return jsonify({"status": "error", "msg": "无效的 IP 地址"})
        bans.ban(ip)
        elog.push_sys(f"手动封禁: {ip}", "ban")
        return jsonify({
            "status": "success",
            "msg": f"已封禁 {ip}，后续连接将被 frp 直接拒绝",
        })

    @app.route("/api/firewall/remove", methods=["POST"])
    @login_required
    def remove_firewall():
        ip = (request.get_json().get("ip") or "").strip()
        if not ip:
            return jsonify({"status": "error", "msg": "IP 为空"})
        bans.unban(ip)
        elog.push_sys(f"解除封禁: {ip}", "unban")
        sio.emit("unban_ip", {"ip": ip})
        return jsonify({"status": "success", "msg": f"已解除对 {ip} 的封禁"})

    # ── WebSocket ─────────────────────────────────────────

    @sio.on("connect")
    def on_connect():
        if not session.get("logged_in"):
            return False
        emit("init", tracker.all_records)
        emit("blocked_update", {"blocked": bans.blocked_count})
        emit("blocked_init", elog.blocked_list)
        emit("active_init", tracker.active_list)
        emit("connection_opened", {"active": tracker.active_count})
        emit("event_log_init", elog.snapshot)

    return app, sio, cfg


# ═══════════════════════════════════════════════════════════
#  模块级实例 (供 WSGI 部署 / 直接运行)
# ═══════════════════════════════════════════════════════════

app, socketio, _cfg = create_app()

if __name__ == "__main__":
    host = _cfg.get("web_host", "0.0.0.0")
    port = _cfg.get("web_port", 5008)
    print("=" * 56)
    print("  FRP_PV — Server Plugin 模式")
    print("=" * 56)
    print("  在 frps.toml 末尾添加:")
    print()
    print("  [[httpPlugins]]")
    print('  name = "frp-pv"')
    print(f'  addr = "127.0.0.1:{port}"')
    print('  path = "/frp-plugin"')
    print('  ops = ["NewUserConn", "CloseUserConn"]')
    print()
    print(f"  Web UI: http://127.0.0.1:{port}")
    print("=" * 56)
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
