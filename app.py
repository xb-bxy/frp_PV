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

模块结构:
  config.py      — ConfigManager (线程安全配置读写)
  models.py      — RingLog / ConnectionRecord (数据结构)
  services.py    — BanManager / EventLog / ConnectionTracker (业务服务)
  geo_service.py — GeoService (多源 IP 地理查询 + 缓存)
  app.py         — Flask 应用工厂 + 路由 + 入口 (本文件)
"""

from __future__ import annotations

import atexit
import os
from functools import wraps
from pathlib import Path

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

from config import ConfigManager
from geo import GeoService
from services import (
    BanManager,
    ConnectionTracker,
    EventLog,
    is_valid_ipv4,
    parse_remote_ip,
)


# ═══════════════════════════════════════════════════════════
#  应用工厂
# ═══════════════════════════════════════════════════════════


def create_app() -> tuple[Flask, SocketIO, ConfigManager]:
    """构建 Flask 应用, 初始化所有服务, 注册路由"""

    base_dir = Path(__file__).parent
    cfg = ConfigManager(base_dir / "config.json")

    app = Flask(__name__)
    app.secret_key = cfg.get("secret_key", os.urandom(24).hex())
    sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    # ── 服务初始化 ────────────────────────────────────────

    geo = GeoService()

    server_geo = geo.detect_server_location()
    if server_geo and server_geo.lat is not None:
        print(f"[GEO] 服务器定位: {server_geo.desc} ({server_geo.lat}, {server_geo.lon})")
    else:
        print("[GEO] ⚠️ 无法探测服务器位置, 地球上 Server 标记将缺失")

    bans = BanManager(cfg)
    elog = EventLog(sio)
    tracker = ConnectionTracker(geo, sio, elog)

    # ── 认证装饰器 ────────────────────────────────────────

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
        def _on_result(_ip, g):
            if g:
                rec["desc"] = g.desc
                rec["country"] = g.country
                rec["lat"] = g.lat
                rec["lon"] = g.lon
                sio.emit("blocked_geo_update", rec)
        geo.lookup_async(ip, callback=_on_result)

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
            _backfill_geo(rec, ip)
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
        geo.lookup_async(ip, callback=lambda _ip, _geo: tracker.record(ip, proxy, raw_addr))
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
        return render_template("index.html", config=cfg.raw,
                               server_geo=server_geo)

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
        if not ip or not is_valid_ipv4(ip):
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

    # ── 退出清理 ──────────────────────────────────────────
    atexit.register(geo.save_cache)

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
