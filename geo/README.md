# geo — 多源聚合 IP 地理定位包

## 这是什么？

把一个 IP 地址丢进来，它会**同时问 10 个不同的网站**"这个 IP 在哪？"，然后把所有回答汇总成一个最准确的结果：国家、省、市、区、运营商、经纬度。

就像你问 10 个人"北京在哪"，综合所有人的答案，比只问一个人靠谱得多。

---

## 目录结构

```
geo/
├── __init__.py          # 包入口，导入即自动注册所有组件
├── config.py            # 所有可调参数（超时、阈值、映射表）
├── models.py            # GeoInfo 数据结构
├── formatting.py        # 文字处理（翻译国名、拼接地址描述）
├── breaker.py           # 熔断器（某个源连续挂了就暂停使用）
├── registry.py          # 装饰器注册表（provider/geocoder 注册中心）
├── service.py           # GeoService 核心（查询流水线 + 缓存）
│
├── providers/           # IP → 地理信息的数据源（10 个）
│   ├── __init__.py      # 自动扫描注册
│   ├── _http.py         # 共享 HTTP 连接
│   ├── ip_api.py        # ip-api.com      权重 8（中文、区级）
│   ├── ipinfo.py        # ipinfo.io       权重 6
│   ├── freeipapi.py     # freeipapi.com   权重 6
│   ├── ipapi_co.py      # ipapi.co        权重 5
│   ├── ipwho.py         # ipwho.is        权重 5
│   ├── ipwhois_app.py   # ipwhois.app     权重 5
│   ├── ip2location.py   # ip2location.io  权重 5
│   ├── db_ip.py         # db-ip.com       权重 4
│   ├── mir6.py          # mir6.com        权重 2（仅中国 IP）
│   ├── cip.py           # cip.cc          权重 2（仅中国 IP）
│   └── geolite2.py      # MaxMind 离线库（非装饰器注册）
│
└── geocoders/           # 地理编码器（地址⇋坐标互转）
    ├── __init__.py      # 自动扫描注册
    ├── nominatim.py     # OpenStreetMap（正向 + 逆向）
    ├── photon.py        # komoot/photon（正向 + 逆向）
    └── bigdatacloud.py  # BigDataCloud（仅逆向，中文）
```

---

## 怎么用？

### 最简单的用法

```python
from geo import GeoService

svc = GeoService()

# 同步查询
info = svc.lookup("114.253.111.241")
print(info.desc)      # "中国 - 北京市 · 昌平区 联通"
print(info.lat)       # 40.2183
print(info.country)   # "中国"

# 私有 IP 返回 None
svc.lookup("127.0.0.1")  # None
```

### 异步查询（不阻塞）

```python
# 查完后会自动调用回调函数
svc.lookup_async("8.8.8.8", callback=lambda ip, info: print(info.desc))
```

### 缓存命中

```python
# 第二次查询同一个 IP，直接从内存返回，不走网络
info = svc.lookup("8.8.8.8")   # 走网络（约 2-5 秒）
info = svc.lookup("8.8.8.8")   # 走缓存（< 0.001 秒）
```

### 获取缓存中的结果（不触发网络查询）

```python
info = svc.get_cached("8.8.8.8")  # 有就返回，没有就 None
```

---

## 查询流水线

一个 IP 查询经历 6 个阶段：

```
IP
 │
 ▼
┌─────────────────────────────────┐
│ 阶段 1: 并发查询 10 个 provider │  ← 最多等 6 秒
│         （挂了的自动跳过）       │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 阶段 2: 国家投票 + 字段合并     │  ← 多数表决定国家
│         收集坐标候选项           │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 阶段 3: GeoLite2 离线补充       │  ← 本地 MMDB 数据库
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 阶段 4: 正向地理编码            │  ← "昌平区" → (40.22, 116.23)
│         有文字没坐标时补坐标     │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 阶段 5: 逆向地理编码            │  ← (39.90, 116.40) → "朝阳区"
│         有坐标没区级时补区级     │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 阶段 6: 坐标评分选最优          │  ← 区级坐标 > 城市级坐标
└────────────┬────────────────────┘
             ▼
          GeoInfo
```

---

## GeoInfo 数据结构

```python
@dataclass
class GeoInfo:
    lat: float | None     # 纬度
    lon: float | None     # 经度
    country: str          # 国家（"中国"）
    region: str           # 省/州（"北京市"）
    city: str             # 城市（"北京市"）
    district: str         # 区/县（"昌平区"）
    isp: str              # 运营商（"联通"）
    ip: str               # 原始 IP
    updated_at: float     # 缓存时间戳
    last_active: float    # 最近活跃时间

    desc → str            # 自动拼接："中国 - 北京市 · 昌平区 联通"
```

---

## 核心机制

### 1. 权重评分

每个 provider 有一个权重（weight），代表对它的信任程度：

| 权重 | 含义 | 典型 provider |
|------|------|---------------|
| 8 | 高精度，支持中文 + 区级 | ip-api |
| 5-6 | 中等精度 | ipinfo, ipwho, freeipapi |
| 2 | 仅中国 IP 有效 | mir6, cip.cc |

坐标评分时额外加分规则：
- 返回了**区级信息** → +3 分
- 正向编码查到**区级地址** → +10 分（压制城市级抱团）
- 多个源坐标**相近**（< 0.5°）→ 每多一个 +2 分，上限 +4

### 2. 国家投票

10 个 provider 都会返回一个国家名字。用**多数表决**决定最终国家。

只有跟投票结果一致的 provider 的省/市/区才会被采纳。防止某个源把美国 IP 错判成中国，把"纽约"混进地址。

### 3. 熔断器

如果某个 provider 连续挂了 3 次（超时/报错），就自动**暂停使用**它 3 小时。3 小时后试一次，如果成功就恢复正常。

状态机：

```
正常（CLOSED）
    │ 连续失败 ≥ 3 次
    ▼
熔断（OPEN）── 一切请求被跳过
    │ 冷却 3 小时
    ▼
半开（HALF_OPEN）── 放一个请求试试
    │ 成功 → 回到 CLOSED
    │ 失败 → 回到 OPEN
```

### 4. 缓存

- 普通 IP：缓存 **7 天**
- 活跃 IP（24 小时内被查过）：缓存 **1 天**（更快刷新）
- 每 20 次新查询自动落盘到 `geo_cache.json`
- 进程退出时 `atexit` 保存

---

## 添加新 provider

在 `providers/` 下新建一个 `.py` 文件，用装饰器注册即可，**不需要改任何其他文件**：

```python
# geo/providers/my_new_api.py

from geo.config import PROVIDER_TIMEOUT
from geo.models import GeoInfo
from geo.providers._http import session
from geo.registry import ip_provider


@ip_provider("my-api", weight=5)
def _lookup(ip: str) -> GeoInfo | None:
    resp = session.get(
        f"https://my-api.com/{ip}",
        timeout=PROVIDER_TIMEOUT,
    ).json()
    return GeoInfo(
        ip=ip,
        lat=resp.get("lat"),
        lon=resp.get("lon"),
        country=resp.get("country", ""),
    )
```

要点：
- **不需要 try/except** — 装饰器自动捕获异常
- **用 `session`** — 共享连接池，自带 User-Agent
- **用 `PROVIDER_TIMEOUT`** — 统一超时
- 文件放进目录就自动注册，importlib 会扫描

---

## 添加新 geocoder

同理，在 `geocoders/` 下新建文件：

```python
# geo/geocoders/my_geocoder.py

from geo.config import GEOCODE_TIMEOUT
from geo.providers._http import session
from geo.registry import forward_geocoder, reverse_geocoder


@forward_geocoder("my-geo", weight=4)
def _geocode(region: str, city: str, district: str = "") -> tuple[float, float] | None:
    # 返回 (lat, lon) 或 None
    ...

@reverse_geocoder("my-geo")
def _reverse(lat: float, lon: float) -> dict | None:
    # 返回 {"country": ..., "region": ..., "city": ..., "district": ...} 或 None
    ...
```

---

## 配置项速查

所有配置在 `geo/config.py`，改这个文件就够了：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `PROVIDER_TIMEOUT` | (2, 3) 秒 | IP 查询超时 (connect, read) |
| `GEOCODE_TIMEOUT` | (1, 2) 秒 | 地理编码超时 |
| `BREAKER_PROVIDER` | 3 次 / 3 小时 | provider 熔断阈值 |
| `BREAKER_GEOCODER` | 3 次 / 3 小时 | geocoder 熔断阈值 |
| `CACHE_TTL` | 7 天 | 普通缓存有效期 |
| `CACHE_ACTIVE_TTL` | 1 天 | 活跃 IP 缓存有效期 |
| `CACHE_SAVE_INTERVAL` | 20 | 每 N 次查询落盘 |
| `MAX_WORKERS` | 4 | 异步线程池大小 |
| `PROVIDER_WAIT_TIMEOUT` | 6 秒 | 并发 provider 最大等待 |
| `GEOCODE_WAIT_TIMEOUT` | 4 秒 | 并发编码器最大等待 |
| `COORD_FWD_DISTRICT_BONUS` | 10 | 正向编码区级加分 |
| `MMDB_PATH` | GeoLite2-City.mmdb | GeoLite2 离线库路径 |
