# FRP 态势感知系统 (FRP Request visualization)

FRP 态势感知系统是一个基于 Python Flask 和 SocketIO 构建的实时监控仪表盘，专为 [frp](https://github.com/fatedier/frp) 设计。它通过实时读取和解析 FRP 的运行日志，结合地理位置数据库，将网络流量的来源地可视化展现在 3D 地球上。不仅如此，本系统还整合了 Linux `iptables` 防火墙控制，支持手工封禁和高频攻击自动封禁机制，为您提供全方位的 FRP 安全态势感知与主动防御能力。
![](./img/frp1.png)
# frps  
如果需要基于日志版本请使用releases 版本 目前main是frp插件模式 需要一个特定版本的frp 
[xb-bxy/frp](https://github.com/xb-bxy/frp/releases/tag/v0.68.1)

## frp中添加配置 
```json
{
  [[httpPlugins]]
  name = "frp-pv"
  addr = "127.0.0.1:5508"
  path = "/frp-plugin"
  ops = ["NewUserConn", "CloseUserConn"]
}
```
## 主要功能特性

*   **🌐 3D 实时可视化**: 使用 WebGL/Three.js 渲染的动态地球仪表盘，实时呈现客户端连接位置、流量飞流动画，直观展示访客分布。
*   **📍 智能定位与识别**: 自动提取并解析连接来源 IP（基于 ipwho.is），智能区分境内/境外流量，并在界面高亮标记境外访问来源。
*   **🛡️ 精准访问控制**: 提供直观的 "访问控制" 面板，完整记录访客 IP 与连接频率，一键执行 IP 黑名单封禁与解封操作（底层联动 `iptables` 规则）。
*   **🤖 自动化高频封禁**: 内置防扫描与防恶意爆破机制。可配置时间窗口（滑动窗口算法）内的连接频率阈值（例如：60秒内连接超过10次）。一旦触发阈值，系统自动调用 `iptables` 将恶意IP阻拦。
*   **✅ 安全白名单机制**: 配置强大的白名单系统，包含 IP 白名单和 代理模块白名单。被标记的 IP 或相关 FRP 服务（模块）不受自动封禁的约束，防止误杀关键业务或管理通道。
*   **⚙️ 图形化后台配置**: 所有复杂的 JSON 配置文件都可以通过前台“系统设置”面板进行点选编辑与保存。支持动态热重载功能，随需开启防御策略。

## 环境依赖

*   **操作系统**: Linux (须支持及安装了 `iptables`)
*   **权限要求**: ROOT 权限 (由于需调用系统命令管理 `iptables` 防护墙)
*   **Python 版本**: Python 3.8+ (推荐使用 `uv` 管理执行环境)

核心依赖库：
*   `Flask` / `Flask-SocketIO` (基础 Web 框架与实时通信)
*   `requests` (GeoIP 解析请求)
*   `werkzeug` (密码哈希鉴权)

## 配置文件说明 (`config.json`)

系统启动时会自动读取工作目录下的 `config.json` 文件（如果没有它会在启动时根据默认参数自动生成）。以下是所有配置参数的说明：

```json
{
  "frp_log_file": "/root/frp/frp_run.log",    // FRP 运行日志的绝对路径，确保日志记录级别足够获取 IP
  "server_location": {                        // FRP 服务端所在地的经纬度标点（地球射线终点）
    "lat": 39.9042,
    "lng": 116.4074,
    "name": "北京 (Beijing)"
  },
  "web_port": 5508,                           // 态势感知面板的 Web 访问端口
  "web_host": "0.0.0.0",                      // 面板监听地址
  "admin_username": "root",                   // 面板登录账户名 
  "admin_password_hash": "",                  // 面板登录密码哈希（可直接在 Web 设置中重置密码）
  "secret_key": "xxx",                        // Flask Cookie 加密密钥（系统自动生成）
  "arc_lifetime_seconds": 3600,               // 3D 地球连线动画在未继续活跃情况下的存留时间（秒）
  "home_country": "中国",                     // 归属地（本国名称），地理位置包含此字符串的流量视为内网/境内
  "foreign_highlight": true,                  // 是否高亮境外 IP（标记为特殊颜色并在控制面板中着重显示）
  
  // 主动防御 (自动封禁) 相关参数
  "auto_ban": {
    "enabled": true,                          // 开启自动防御系统总开关
    "foreign_only": true,                     // 仅对境外攻击 IP 开启自动封禁机制（国内 IP 超频仅报警不封锁）
    "threshold_seconds": 60,                  // 频次统计滑动时间窗口大小（秒）
    "threshold_count": 10,                    // 触发封禁要求的频次阈值（在上述该周期内连接次数≥该值则被阻断）
    "whitelist_modules": [                    // FRP 代理名称/模块白名单。匹配这些模块的请求免除封禁检测
      "keai_server_web_https",
      "keai_server_web_http"
    ],
    "whitelist_ips": [                        // IP 白名单。这些特定 IP 进行高频访问不受任何限制
      "127.0.0.1"
    ]
  }
}
```

> **注意**：以上设置均可通过登录后的右下角【系统设置】直接修改即可生效，无需人工打开文本编辑器编辑 `config.json`。

## 安装与启动 (使用 `uv`)

1. **配置环境**
   ```bash
   # 克隆/上传项目代码到 /root/frp_PV 目录
   cd /root/frp_PV
   ```
   
2. **使用 uv 启动系统**
   ```bash
   # 执行 uv 运行指令，会自动处理依赖并启动 Web 服务
   uv run app.py
   ```

3. **配置 Systemd 服务 (强烈推荐)**
   本项目提供了一个 `frp_pv.service` 配置文件，用于通过 `systemctl` 将程序设置为后台服务，实现开机自启和自动重启功能。

   * 复制配置文件到系统目录：
     ```bash
     cp /root/frp_PV/frp_pv.service /etc/systemd/system/
     ```
   * 重新加载 systemd 守护进程：
     ```bash
     systemctl daemon-reload
     ```
   * 启动并设置开机自启：
     ```bash
     systemctl start frp_pv
     systemctl enable frp_pv
     ```
   * 查看运行状态：
     ```bash
     systemctl status frp_pv
     ```
   * 停止服务：
     ```bash
     systemctl stop frp_pv
     ```

4. **后台常驻运行 (普通替代方法)**
   如果不想使用 systemd，也可以使用 `nohup`、`screen` 进行简单的守护：
   ```bash
   nohup uv run app.py > pv.log 2>&1 &
   ```

5. **访问面板**
   * 打开浏览器访问：`http://服务器IP:5508`
   * 初次使用时，如未设定密码可以直接进入（或按照 `config.json` 中的设置）。推荐登录后在“系统设置”选项卡设立密码。

## 注意事项

- **IPtables 状态保存**: 本程序运行中动态调用的是内存在用 `iptables -A INPUT -s IP -j DROP` 指令，这意味着重启服务器（宿主机）将导致临时封禁列表丢失。如需永久阻断，请结合系统防火墙配置固化工具处理。
- **Geo API 限制**: 系统默认使用海外节点友好的 `ipwho.is` JSON API 检索定位数据。如果在内网专网部署，由于缺少地理数据会导致归属地查询失效。
- **日志权限**: 请务必保证本程序的执行用户具有目标 FRP 日志路径 `/root/frp/frp_run.log` 的持续物理读取权限。


