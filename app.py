# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "flask",
#     "flask-socketio",
#     "requests",
# ]
# ///

import os
import re
import time
import json
import datetime
import requests
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from flask_socketio import SocketIO, emit
from functools import wraps
from collections import defaultdict, deque
from werkzeug.security import check_password_hash, generate_password_hash
from threading import Thread
import subprocess

# 载入配置
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

app = Flask(__name__)
# 载入Session密钥
app.secret_key = config.get("secret_key", os.urandom(24).hex())
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 定义日志文件路径
_cached_config = None
_last_config_load_time = 0

def get_log_file():
    global _cached_config, _last_config_load_time
    now = time.time()
    # 限制配置读取频率，每 5 秒最多重新加载一次，避免高发日志时频繁读写文件
    if now - _last_config_load_time > 5:
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                _cached_config = json.load(f)
                _last_config_load_time = now
        except:
            if _cached_config is None:
                _cached_config = config
    
    current_config = _cached_config if _cached_config else config
    return os.getenv("FRP_LOG_FILE") or current_config.get("frp_log_file", "/root/frp/frp_run.log")



ip_cache = {}    # 缓存已解析的 IP -> 地理信息映射
ip_connections = defaultdict(list) # 记录 IP 的访问时间戳，用于自动封禁
locations = []   # 保存用于前端展示的位置列表
location_map = {} # 记录 (ip, module) -> dict 进行引用更新
active_conns = defaultdict(deque) # module -> deque of {ip, connect_time}，追踪活跃连接

def get_geo_info(ip):
    """仅获取IP地理位置信息，带缓存防限流"""
    if ip in ip_cache:
        return ip_cache[ip]
    try:
        # 排除了一些局域网 IP
        if ip.startswith("127.") or ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
            ip_cache[ip] = None
            return None
            
        # 因 ip-api.com 在国内可能被墙，这里改用 ipwho.is 免费接口 + 设置超时防卡死
        res = requests.get(f"http://ipwho.is/{ip}?lang=zh-CN", timeout=5).json()
        if res.get('success') is True:
            geo_data = {
                "lat": res.get("latitude"),
                "lon": res.get("longitude"),
                "country": res.get("country", ""),
                "desc": f"{res.get('country', '')} - {res.get('city', '')}".strip(" - ")
            }
            ip_cache[ip] = geo_data
            return geo_data
    except Exception as e:
        print(f"Error fetching IP {ip}: {e}")
    ip_cache[ip] = None
    return None

def parse_log_timestamp(line):
    """从 frps 日志行中提取精确时间戳"""
    m = re.match(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{3})', line)
    if m:
        return datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f')
    return None

def watch_log():
    """后台监控并解析 frp 日志文件"""
    while True:
        try:
            current_log_file = get_log_file()
            if not current_log_file or not os.path.exists(current_log_file):
                print(f"警告: 日志文件 {current_log_file} 不存在，等待其生成...")
                while not current_log_file or not os.path.exists(current_log_file):
                    current_log_file = get_log_file()
                    time.sleep(5)
                    
            print(f"开始监控日志: {current_log_file}")
            try:
                with open(current_log_file, 'r', encoding='utf-8') as f:
                    # 查找最后一次 frps 启动位置，从该处加载历史连接数据
                    last_start_pos = f.tell()
                    while True:
                        line = f.readline()
                        if not line:
                            break
                        if 'frps uses config file:' in line:
                            last_start_pos = f.tell()
                    f.seek(last_start_pos)
                    print(f"从最近一次 frps 启动记录开始初始化历史数据...")
                    is_init = True
                    # 记录inode信息，检查是否被轮换或修改路径
                    current_ino = os.fstat(f.fileno()).st_ino
                    
                    while True:
                        new_log_file = get_log_file()
                        if new_log_file != current_log_file:
                            print(f"检测到日志文件配置变更: {current_log_file} -> {new_log_file}")
                            break
                            
                        line = f.readline()
                        if not line:
                            if is_init:
                                is_init = False
                                active = sum(len(q) for q in active_conns.values())
                                print(f"历史数据初始化完成: {len(locations)} 条 IP 记录, 活跃连接 {active}")
                            time.sleep(1)
                            
                            # 检查文件是否被重建或轮转
                            try:
                                if os.stat(current_log_file).st_ino != current_ino:
                                    print(f"检测到日志文件 {current_log_file} 已轮存更新")
                                    break
                            except FileNotFoundError:
                                print(f"日志文件 {current_log_file} 被移除")
                                break
                                
                            continue
                            
                        # 正则匹配 frp 日志中的模块名和客户端 IP
                        # 新格式: 2026-03-08 16:40:26.417 [I] [proxy/proxy.go:204] [4b30cb9a69ac7f18] [keai_server_web_https] get a user connection [106.87.123.185:3368]
                        match = re.search(r'(?:\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{3}\s+\[.*?\]\s+\[.*?\]\s+\[.*?\]\s+)?\[([^\]]+)\] get a user connection \[([^\]]+):\d+\]', line)
                        if match:
                            module = match.group(1)
                            ip = match.group(2)
                            
                            # 1. 获取归属地并记录模块访问次数
                            if ip not in ip_cache:
                                print(f"检测到新 IP: {ip} (模块: {module}), 正在查询地理位置...")
                                get_geo_info(ip)
                                time.sleep(0.3 if is_init else 1.5)
                            
                            geo_data = ip_cache.get(ip)
                            
                            key = (ip, module)
                            if key not in location_map:
                                data = {
                                    "ip": ip,
                                    "lat": geo_data.get("lat") if geo_data else None,
                                    "lon": geo_data.get("lon") if geo_data else None,
                                    "country": geo_data.get("country", "") if geo_data else "",
                                    "desc": geo_data.get("desc", "") if geo_data else "",
                                    "module": module,
                                    "time": time.strftime('%Y-%m-%d %H:%M:%S'),
                                    "count": 1
                                }
                                location_map[key] = data
                                locations.append(data)
                                socketio.emit('new_ip', data)
                            else:
                                data = location_map[key]
                                data["count"] = data.get("count", 1) + 1
                                data["time"] = time.strftime('%Y-%m-%d %H:%M:%S')
                                socketio.emit('update_ip', data)
                                
                            # 2. 自动封禁 (Auto Ban) 判定逻辑
                            cfg = _cached_config if _cached_config else config
                            auto_ban = cfg.get("auto_ban", {})
                            
                            whitelist_ips = auto_ban.get("whitelist_ips", [])
                            
                            if auto_ban.get("enabled", False) and module not in auto_ban.get("whitelist_modules", []) and ip not in whitelist_ips:
                                country = geo_data.get('country', '') if geo_data else ''
                                home = cfg.get("home_country", "中国")
                                
                                # 根据条件判断该 IP 是否受规则管控
                                # 默认开启 foreign_only，即若检测到是 home_country (如中国) 的 IP，直接放行不记录累加
                                if not (auto_ban.get("foreign_only", True) and country == home):
                                    now = time.time()
                                    history = ip_connections[ip]
                                    history.append(now)
                                    
                                    limit_sec = auto_ban.get("threshold_seconds", 60)
                                    limit_count = auto_ban.get("threshold_count", 10)
                                    
                                    # 剔除滑动窗口外（超时）的历史记录
                                    while history and now - history[0] > limit_sec:
                                        history.pop(0)
                                        
                                    if len(history) >= limit_count:
                                        print(f"⚠️ [系统预警] 触发自动封禁: {ip} 在 {limit_sec} 秒内不断连接非白名单模块 {module} 达 {len(history)} 次")
                                        try:
                                            # 防重复写入
                                            subprocess.check_call(['iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP'], stderr=subprocess.DEVNULL)
                                        except: pass
                                        try:
                                            subprocess.check_call(['iptables', '-A', 'INPUT', '-s', ip, '-j', 'DROP'])
                                            print(f"🛡️ 已将 {ip} 自动加入系统 iptables 黑名单阻断")
                                            socketio.emit('sys_log', {'msg': f"自动封禁: {ip} (频繁连接 {module})"})
                                        except Exception as e:
                                            print(f"执行防火墙封禁失败: {e}")
                                            
                                        # 清空记录避免该IP紧接着无意义的连续触发拉黑命令
                                        history.clear()

                        # 3. 连接建立追踪
                        join_match = re.search(
                            r'\[([^\]]+)\] join connections, workConn\(.*?\) userConn\(.*?r\[([^\]]+):\d+\]\)',
                            line
                        )
                        if join_match:
                            j_module = join_match.group(1)
                            j_ip = join_match.group(2)
                            j_ts = parse_log_timestamp(line)
                            active_conns[j_module].append({'ip': j_ip, 'connect_time': j_ts})
                            socketio.emit('connection_opened', {
                                'module': j_module, 'ip': j_ip,
                                'active': sum(len(q) for q in active_conns.values())
                            })

                        # 4. 连接断开追踪 (计算持续时长)
                        close_match = re.search(r'\[([^\]]+)\] join connections closed', line)
                        if close_match:
                            c_module = close_match.group(1)
                            duration = None
                            c_ip = None
                            if active_conns[c_module]:
                                conn = active_conns[c_module].popleft()
                                c_ip = conn['ip']
                                c_ts = parse_log_timestamp(line)
                                if c_ts and conn.get('connect_time'):
                                    duration = (c_ts - conn['connect_time']).total_seconds()
                            geo = ip_cache.get(c_ip) if c_ip else None
                            socketio.emit('connection_closed', {
                                'ip': c_ip or '未知',
                                'module': c_module,
                                'duration': round(duration, 3) if duration is not None else None,
                                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                                'desc': geo.get('desc', '') if geo else '',
                                'country': geo.get('country', '') if geo else '',
                                'active': sum(len(q) for q in active_conns.values())
                            })

            except Exception as e:
                print(f"读取日志文件遇到错误: {e}")
                time.sleep(5)
        except Exception as outer_e:
            print(f"监控线程出现意外错误: {outer_e}")
            time.sleep(5)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password', '')
        
        cfg_user = config.get('admin_username', 'root')
        cfg_hash = config.get('admin_password_hash', '')
        
        if username == cfg_user:
            # 如果配置的密码为空（即无密码状态）或密码匹配成功
            if (not cfg_hash and password == '') or (cfg_hash and check_password_hash(cfg_hash, password)):
                session['logged_in'] = True
                return redirect(url_for('index'))
            else:
                error = '密码错误。当前默认无密码时请直接留空。' if not cfg_hash else '用户名或密码错误'
        else:
            error = '用户名或密码错误'
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    if request.method == 'GET':
        return jsonify({
            "status": "success",
            "data": {
                "frp_log_file": config.get("frp_log_file", "/root/frp/frp_run.log"),
                "home_country": config.get("home_country", "中国"),
                "frequent_threshold": config.get("frequent_threshold", 5),
                "foreign_highlight": config.get("foreign_highlight", True),
                "admin_username": config.get("admin_username", "root"),
                "auto_ban": config.get("auto_ban", {})
            }
        })

    if not request.is_json:
        return jsonify({"status": "error", "msg": "请求格式错误"}), 400
        
    data = request.get_json()
    
    # 账号与密码处理
    if data.get('change_pwd'):
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        cfg_hash = config.get('admin_password_hash', '')
        
        if cfg_hash and not check_password_hash(cfg_hash, old_password):
            return jsonify({"status": "error", "msg": "原密码错误"})
        elif not cfg_hash and old_password != '':
            return jsonify({"status": "error", "msg": "原密码为空，请留空"})
            
        config['admin_password_hash'] = generate_password_hash(new_password) if new_password else ''

    # 常规配置处理
    config['frp_log_file'] = data.get('frp_log_file', config.get('frp_log_file'))
    config['home_country'] = data.get('home_country', config.get('home_country'))
    config['frequent_threshold'] = data.get('frequent_threshold', config.get('frequent_threshold'))
    if 'auto_ban' in data:
        config['auto_ban'] = data['auto_ban']
        
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        
    # 主动刷新内存中的缓存配置
    global _cached_config
    _cached_config = config
    
    return jsonify({"status": "success", "msg": "系统设置保存成功！"})

@app.route('/')
@login_required
def index():
    return render_template('index.html', config=config)

@app.route('/api/data')
@login_required
def api_data():
    return jsonify(locations)

@app.route('/api/firewall', methods=['GET'])
@login_required
def get_firewall():
    try:
        result = subprocess.check_output(['iptables', '-nL', 'INPUT', '--line-numbers'], universal_newlines=True)
        blocked_ips = []
        for line in result.split('\n'):
            parts = line.split()
            # 根据 iptables -nL INPUT --line-numbers 格式解析
            # 例: 1    DROP       all  --  1.2.3.4              0.0.0.0/0
            if len(parts) >= 5 and parts[1] == 'DROP' and parts[4] != '0.0.0.0/0':
                blocked_ips.append({
                    "num": parts[0],
                    "ip": parts[4],
                    "target": parts[1]
                })
        return jsonify({"status": "success", "data": blocked_ips})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/firewall/add', methods=['POST'])
@login_required
def add_firewall():
    data = request.get_json()
    ip = data.get('ip')
    if not ip or not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
        return jsonify({"status": "error", "msg": "无效的 IP 地址"})
    try:
        # 添加防火墙规则
        subprocess.check_call(['iptables', '-A', 'INPUT', '-s', ip, '-j', 'DROP'])
        socketio.emit('sys_log', {'msg': f"手动封禁: 已将 {ip} 加入黑名单"})
        return jsonify({"status": "success", "msg": f"已将 {ip} 加入黑名单并阻断访问"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/firewall/remove', methods=['POST'])
@login_required
def remove_firewall():
    data = request.get_json()
    ip = data.get('ip')
    if not ip:
        return jsonify({"status": "error", "msg": "IP为空"})
    try:
        # 移除该IP所有的 DROP 规则
        while True:
            try:
                subprocess.check_call(['iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP'], stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                break
        socketio.emit('sys_log', {'msg': f"手动解封: 已解除对 {ip} 的阻断", 'type': 'unban'})
        return jsonify({"status": "success", "msg": f"已解除对 {ip} 的阻断"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500


@socketio.on('connect')
def on_connect():
    """客户端连接时，校验登录状态并推送全量历史数据"""
    if not session.get('logged_in'):
        return False  # 在握手阶段直接拒绝，未登录用户无法建立连接
    emit('init', locations)


if __name__ == '__main__':
    t = Thread(target=watch_log, daemon=True)
    t.start()
    host = config.get('web_host', '0.0.0.0')
    port = config.get('web_port', 5008)
    print(f"Web 服务已启动，请访问 http://127.0.0.1:{port}")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
