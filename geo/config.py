"""geo.config — 集中配置."""

from pathlib import Path

# ── 超时 (connect, read) 秒 ──────────────────────────────

PROVIDER_TIMEOUT = (2, 3)
GEOCODE_TIMEOUT  = (1, 2)

# ── 熔断器 ───────────────────────────────────────────────

BREAKER_PROVIDER = {"max_failures": 3, "cooldown": 3 * 3600}
BREAKER_GEOCODER = {"max_failures": 3, "cooldown": 3 * 3600}

# ── 缓存/路径 ────────────────────────────────────────────

MMDB_PATH           = Path("GeoLite2-City.mmdb")
CACHE_FILE          = Path("geo_cache.json")
CACHE_SAVE_INTERVAL = 20
CACHE_TTL           = 7 * 24 * 3600
CACHE_ACTIVE_TTL    = 24 * 3600
CACHE_INCOMPLETE_TTL = 120          # 无坐标的残缺结果, 2 分钟后重试

# ── 线程池 ───────────────────────────────────────────────

MAX_WORKERS           = 4
PROVIDER_WAIT_TIMEOUT = 6
GEOCODE_WAIT_TIMEOUT  = 4

# ── 坐标评分 ─────────────────────────────────────────────

COORD_DISTRICT_BONUS     = 3
COORD_FWD_DISTRICT_BONUS = 4
COORD_AGREE_THRESHOLD    = 0.5   # 度
COORD_AGREE_BONUS        = 2
COORD_AGREE_MAX          = 4
COORD_CITY_MATCH_BONUS   = 6

# ── 私有 IP ──────────────────────────────────────────────

PRIVATE_PREFIXES = ("127.", "192.168.", "10.", "172.")

# ── 国家代码 (ISO 3166-1) → 中文 ─────────────────────────

CC_MAP: dict[str, str] = {
    "CN": "中国", "US": "美国", "JP": "日本", "KR": "韩国",
    "SG": "新加坡", "HK": "中国香港", "TW": "中国台湾",
    "DE": "德国", "FR": "法国", "GB": "英国", "AU": "澳大利亚",
    "CA": "加拿大", "RU": "俄罗斯", "IN": "印度", "ID": "印度尼西亚",
    "BR": "巴西", "NL": "荷兰", "TH": "泰国", "VN": "越南",
    "MY": "马来西亚", "PH": "菲律宾", "IT": "意大利", "ES": "西班牙",
    "SE": "瑞典", "CH": "瑞士",
}

# ── 国家全名 → 中文简称 ──────────────────────────────────

COUNTRY_NAMES: dict[str, str] = {
    "中华人民共和国": "中国", "美利坚合众国": "美国",
    "大韩民国": "韩国", "日本国": "日本",
    "United States": "美国", "United States of America": "美国",
    "United Kingdom": "英国", "Japan": "日本",
    "South Korea": "韩国", "Republic of Korea": "韩国",
    "North Korea": "朝鲜", "China": "中国",
    "Singapore": "新加坡", "Russia": "俄罗斯",
    "Russian Federation": "俄罗斯", "Germany": "德国",
    "France": "法国", "Australia": "澳大利亚",
    "Canada": "加拿大", "Brazil": "巴西",
    "India": "印度", "Indonesia": "印度尼西亚",
    "Thailand": "泰国", "Vietnam": "越南",
    "Malaysia": "马来西亚", "Philippines": "菲律宾",
    "Netherlands": "荷兰", "Italy": "意大利",
    "Spain": "西班牙", "Sweden": "瑞典",
    "Switzerland": "瑞士", "Taiwan": "台湾", "Hong Kong": "香港",
}

# ── ISP 翻译 ─────────────────────────────────────────────

ISP_EN_TO_CN: dict[str, str] = {
    "china unicom": "联通", "china telecom": "电信",
    "china mobile": "移动", "chinanet": "电信", "cmnet": "移动",
    "cernet": "教育网", "tencent": "腾讯云",
    "alibaba": "阿里云", "aliyun": "阿里云",
    "huawei cloud": "华为云", "amazon": "AWS",
    "google": "GCP", "microsoft": "Azure",
    "cloudflare": "Cloudflare", "digitalocean": "DigitalOcean",
    "linode": "Linode", "vultr": "Vultr",
    "ovh": "OVH", "hetzner": "Hetzner",
}

ISP_CN_FULL_TO_SHORT: dict[str, str] = {
    "中国联通": "联通", "中国电信": "电信", "中国移动": "移动",
    "中国铁通": "铁通", "中国教育网": "教育网",
}

# ── 行政区划后缀 ─────────────────────────────────────────

ADMIN_SUFFIXES = (
    "维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区",
    "自治区", "自治州", "自治县", "地区",
    "省", "市", "区", "县", "州", "盟", "旗",
)

# ── 省名英文 → 中文 (合并投票用) ─────────────────────────

PROVINCE_EN_TO_CN: dict[str, str] = {
    "anhui": "安徽", "beijing": "北京", "chongqing": "重庆",
    "fujian": "福建", "gansu": "甘肃", "guangdong": "广东",
    "guangxi": "广西", "guizhou": "贵州", "hainan": "海南",
    "hebei": "河北", "heilongjiang": "黑龙江", "henan": "河南",
    "hubei": "湖北", "hunan": "湖南", "inner mongolia": "内蒙古",
    "jiangsu": "江苏", "jiangxi": "江西", "jilin": "吉林",
    "liaoning": "辽宁", "ningxia": "宁夏", "qinghai": "青海",
    "shaanxi": "陕西", "shandong": "山东", "shanghai": "上海",
    "shanxi": "山西", "sichuan": "四川", "tianjin": "天津",
    "tibet": "西藏", "xinjiang": "新疆", "yunnan": "云南",
    "zhejiang": "浙江", "taiwan": "台湾",
    "hong kong": "香港", "macau": "澳门",
}

# ── 城市名英文 → 中文 (合并投票用) ────────────────────────

CITY_EN_TO_CN: dict[str, str] = {
    "beijing": "北京", "shanghai": "上海", "guangzhou": "广州",
    "shenzhen": "深圳", "chengdu": "成都", "wuhan": "武汉",
    "hangzhou": "杭州", "nanjing": "南京", "chongqing": "重庆",
    "tianjin": "天津", "suzhou": "苏州", "changsha": "长沙",
    "zhengzhou": "郑州", "hefei": "合肥", "fuzhou": "福州",
    "jinan": "济南", "qingdao": "青岛", "dalian": "大连",
    "shenyang": "沈阳", "harbin": "哈尔滨", "changchun": "长春",
    "nanning": "南宁", "guiyang": "贵阳", "lhasa": "拉萨",
    "urumqi": "乌鲁木齐", "hohhot": "呼和浩特", "lanzhou": "兰州",
    "yinchuan": "银川", "xining": "西宁", "haikou": "海口",
    "taiyuan": "太原", "shijiazhuang": "石家庄", "nanchang": "南昌",
    "kunming": "昆明", "xiamen": "厦门", "ningbo": "宁波",
    "wuxi": "无锡", "dongguan": "东莞", "foshan": "佛山",
    "wenzhou": "温州", "zhuhai": "珠海", "changzhou": "常州",
    "huanggang": "黄冈", "yichang": "宜昌", "xiangyang": "襄阳",
    "tangshan": "唐山", "baoding": "保定", "luoyang": "洛阳",
    "guilin": "桂林", "nantong": "南通", "xuzhou": "徐州",
    "yantai": "烟台", "shaoxing": "绍兴", "huizhou": "惠州",
    "zhongshan": "中山", "quanzhou": "泉州", "zhanjiang": "湛江",
    "xian": "西安", "xi'an": "西安",
    "baotou": "包头", "anshan": "鞍山", "yancheng": "盐城",
    "yangzhou": "扬州", "huzhou": "湖州", "jiaxing": "嘉兴",
    "jinhua": "金华", "zhoushan": "舟山", "lishui": "丽水",
    "mountain view": "芒廷维尤", "sydney": "悉尼",
    "tokyo": "东京", "osaka": "大阪", "seoul": "首尔",
}
