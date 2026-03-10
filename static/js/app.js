/* ═══════════════════════════════════════════════════════
   FRP_PV — 全球态势感知主脚本
   依赖: Three.js, Globe.gl, Socket.IO (均在 HTML 中引入)
   配置: 由 HTML 内联 <script> 注入 window.APP_CONFIG
   ═══════════════════════════════════════════════════════ */

// ── 从模板注入的配置读取 ────────────────────────────────
const _cfg = window.APP_CONFIG || {};
const PRIMARY_COLOR = '#3b82f6';
const TARGET_COLOR = '#ffffff';
const TARGET_LOC = { lat: _cfg.serverLat || 0, lng: _cfg.serverLng || 0 };
const ARC_LIFETIME_MS = (_cfg.arcLifetime || 3600) * 1000;
const HOME_COUNTRY = _cfg.homeCountry || '中国';
const FREQUENT_THRESHOLD = _cfg.frequentThreshold || 5;
const GLOBE_IMAGE_URL = _cfg.globeImageUrl || '';
const BUMP_IMAGE_URL = _cfg.bumpImageUrl || '//unpkg.com/three-globe/example/img/earth-topology.png';
const CLOUD_IMAGE_URL = _cfg.cloudImageUrl || '//unpkg.com/three-globe/example/img/earth-clouds10k.png';
let foreignHighlight = _cfg.foreignHighlight !== false;

// ── 自定义对话框 ────────────────────────────────────────
const customDialog = {
    show(options) {
        document.getElementById('cd-title').innerText = options.title || '提示';
        document.getElementById('cd-msg').innerHTML = options.msg || '';
        const cancelBtn = document.getElementById('cd-cancel-btn');
        const confirmBtn = document.getElementById('cd-confirm-btn');
        const modal = document.getElementById('custom-dialog-modal');

        if (options.type === 'confirm') {
            cancelBtn.style.display = 'block';
            cancelBtn.onclick = () => {
                modal.classList.remove('active');
                if (options.onCancel) options.onCancel();
            };
        } else {
            cancelBtn.style.display = 'none';
        }

        confirmBtn.onclick = () => {
            modal.classList.remove('active');
            if (options.onConfirm) options.onConfirm();
        };

        modal.classList.add('active');
    },
    alert(msg, callback) {
        this.show({ title: '提示', msg, type: 'alert', onConfirm: callback });
    },
    confirm(msg, onConfirm, onCancel) {
        this.show({ title: '操作确认', msg, type: 'confirm', onConfirm, onCancel });
    }
};

// ── 工具函数 ────────────────────────────────────────────

function isExpired(loc) {
    if (!loc.time || ARC_LIFETIME_MS <= 0) return false;
    const t = new Date(loc.time.replace(' ', 'T'));
    return (Date.now() - t.getTime()) > ARC_LIFETIME_MS;
}

function formatDuration(sec) {
    if (sec === null || sec === undefined) return '';
    if (sec < 1) return (sec * 1000).toFixed(0) + 'ms';
    if (sec < 60) return sec.toFixed(1) + 's';
    if (sec < 3600) return Math.floor(sec / 60) + 'm ' + Math.floor(sec % 60) + 's';
    return Math.floor(sec / 3600) + 'h ' + Math.floor((sec % 3600) / 60) + 'm';
}

// ── Cesium 初始化 ────────────────────────────────────────

const globeContainer = document.getElementById('globe-container');
const viewer = new Cesium.Viewer(globeContainer, {
    animation: false,
    baseLayerPicker: true,
    fullscreenButton: false,
    vrButton: false,
    geocoder: false,
    homeButton: false,
    infoBox: false,
    sceneModePicker: false,
    selectionIndicator: false,
    timeline: false,
    navigationHelpButton: false,
    navigationInstructionsInitiallyVisible: false,
    scene3DOnly: true,
    shadows: false,
    skyAtmosphere: new Cesium.SkyAtmosphere(),
    skyBox: new Cesium.SkyBox({
        sources: {
            positiveX: 'https://unpkg.com/three-globe/example/img/earth-topology.png', // Fallback, Cesium provides default anyway
            negativeX: 'https://unpkg.com/three-globe/example/img/earth-topology.png',
            positiveY: 'https://unpkg.com/three-globe/example/img/earth-topology.png',
            negativeY: 'https://unpkg.com/three-globe/example/img/earth-topology.png',
            positiveZ: 'https://unpkg.com/three-globe/example/img/earth-topology.png',
            negativeZ: 'https://unpkg.com/three-globe/example/img/earth-topology.png'
        }
    }) // We'll just use defaults where possible to keep it lightweight.
});

// Remove default base layer if we want a custom one, but default imagery is fine.
// viewer.scene.globe.enableLighting = true;
viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#030305');

// 去除底部 Cesium logo 标志
viewer.cesiumWidget.creditContainer.style.display = "none";

// 隐藏原右上角工具栏
viewer.baseLayerPicker.container.style.display = 'none';

// 在标题旁新建独立的 BaseLayerPicker（中文化）
(function createTitlePicker() {
    const logoEl = document.querySelector('.overlay-title-row');
    const pickerContainer = document.createElement('div');
    pickerContainer.id = 'title-layer-picker';
    logoEl.appendChild(pickerContainer);

    const imageryVMs = viewer.baseLayerPicker.viewModel.imageryProviderViewModels;
    const terrainVMs = viewer.baseLayerPicker.viewModel.terrainProviderViewModels;

    // 翻译底图名称
    const nameMap = {
        'Bing Maps Aerial': '必应卫星图',
        'Bing Maps Aerial with Labels': '必应卫星图+标注',
        'Bing Maps Roads': '必应道路图',
        'Sentinel-2': '哨兵-2',
        'Blue Marble': '蓝色弹珠',
        'Earth at night': '夜间地球',
        'Natural Earth II': '自然地球 II',
        'Google Maps Satellite': '谷歌卫星图',
        'Google Maps Satellite with Labels': '谷歌卫星图+标注',
        'Google Maps Roadmap': '谷歌道路图',
        'Google Maps Contour': '谷歌等高线',
        'Azure Maps Aerial': 'Azure 卫星图',
        'WGS84 Ellipsoid': 'WGS84 椭球体',
        'Cesium World Terrain': 'Cesium 世界地形',
        'STK World Terrain': 'STK 世界地形',
        'Ellipsoid': '椭球体（无地形）',
    };
    [...imageryVMs, ...terrainVMs].forEach(vm => {
        const cn = nameMap[vm.name];
        if (cn) vm.name = cn;
    });

    const picker = new Cesium.BaseLayerPicker(pickerContainer, {
        globe: viewer.scene.globe,
        imageryProviderViewModels: imageryVMs,
        terrainProviderViewModels: terrainVMs
    });

    // 恢复上次保存的底图选择
    const STORAGE_KEY = 'frp_pv_imagery';
    const savedName = localStorage.getItem(STORAGE_KEY);
    if (savedName) {
        const vm = imageryVMs.find(v => v.name === savedName);
        if (vm) picker.viewModel.selectedImagery = vm;
    }

    // 每次切换时保存到 localStorage
    picker.viewModel.selectedImageryChanged = new Cesium.Event();
    Cesium.knockout.getObservable(picker.viewModel, 'selectedImagery').subscribe(function(vm) {
        if (vm && vm.name) localStorage.setItem(STORAGE_KEY, vm.name);
    });

    // 用 MutationObserver 在下拉框出现时替换英文标签
    const labelMap = { 'Imagery': '底图', 'Terrain': '地形' };
    function translatePickerDOM(root) {
        root.querySelectorAll('.cesium-baseLayerPicker-sectionTitle').forEach(el => {
            const cn = labelMap[el.textContent.trim()];
            if (cn) el.textContent = cn;
        });
    }
    const dropDown = pickerContainer.querySelector('.cesium-baseLayerPicker-dropDown');
    if (dropDown) {
        translatePickerDOM(dropDown);
        new MutationObserver(() => translatePickerDOM(dropDown))
            .observe(dropDown, { childList: true, subtree: true, characterData: true });
    }
})();

viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(TARGET_LOC.lng + 10, TARGET_LOC.lat - 15, 10000000)
});

window.addEventListener('resize', () => {
    viewer.resize();
});

// ── Cesium 数据 ──────────────────────────────────────────

const logStream = document.getElementById('log-stream');
const allLogsStream = document.getElementById('all-logs-stream');
let attackPointsData = [], attackArcsData = [], attackRingsData = [];

// === 自定义 Fabric 飞线材质 ===
function FlyingLineMaterialProperty(color, duration) {
    this._definitionChanged = new Cesium.Event();
    this.color = color;
    this.duration = duration || 2000;
    this._time = performance.now();
}
Object.defineProperties(FlyingLineMaterialProperty.prototype, {
    isConstant: { get: function () { return false; } },
    definitionChanged: { get: function () { return this._definitionChanged; } }
});
FlyingLineMaterialProperty.prototype.getType = function () {
    return 'FlyingLine';
};
FlyingLineMaterialProperty.prototype.getValue = function (time, result) {
    if (!Cesium.defined(result)) result = {};
    // Fix: color might be a raw Cesium.Color instead of a Property
    result.color = Cesium.Property.getValueOrClonedDefault(
        this.color instanceof Cesium.Property ? this.color : new Cesium.ConstantProperty(this.color), 
        time, 
        Cesium.Color.WHITE, 
        result.color
    );
    result.time = ((performance.now() - this._time) % this.duration) / this.duration;
    return result;
};
FlyingLineMaterialProperty.prototype.equals = function (other) {
    return this === other || (other instanceof FlyingLineMaterialProperty && Cesium.Property.equals(this.color, other.color));
};

if (!Cesium.Material._materialCache.getMaterial('FlyingLine')) {
    Cesium.Material._materialCache.addMaterial('FlyingLine', {
        fabric: {
            type: 'FlyingLine',
            uniforms: { color: new Cesium.Color(1.0, 0.0, 0.0, 1.0), time: 0.0 },
            source: `
                czm_material czm_getMaterial(czm_materialInput materialInput) {
                    czm_material material = czm_getDefaultMaterial(materialInput);
                    vec2 st = materialInput.st;
                    // 流动效果：计算相对于当前时间 time 的距离
                    float t = fract(st.s - time);
                    // 头部亮，尾部暗的飞线拖尾
                    float strength = smoothstep(0.0, 0.5, t) * (1.0 - smoothstep(0.5, 1.0, t));
                    float alpha = pow(t, 2.0); // 尾部渐变
                    material.diffuse = color.rgb;
                    material.alpha = color.a * alpha * 2.0;
                    return material;
                }
            `
        },
        translucent: function () { return true; }
    });
}

// === 自定义屏蔽虚线材质 ===
// === X 标记 Billboard 图像 (封禁连接用，一次性创建) ===
const _xMarkerCanvas = (() => {
    const c = document.createElement('canvas');
    c.width = 48; c.height = 48;
    const ctx = c.getContext('2d');
    ctx.strokeStyle = 'rgba(255, 50, 50, 1.0)';
    ctx.lineWidth = 3;  // 笔划细
    ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(8, 8); ctx.lineTo(40, 40); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(40, 8); ctx.lineTo(8, 40); ctx.stroke();
    return c;
})();

function addBlockedXMarkers(lineId, arcPositions) {
    [0.25, 0.5, 0.75].forEach((frac, i) => {
        const markerId = `arcx_${lineId}_${i}`;
        if (!viewer.entities.getById(markerId)) {
            const idx = Math.max(0, Math.min(arcPositions.length - 1,
                Math.floor(frac * (arcPositions.length - 1))));
            viewer.entities.add({
                id: markerId,
                position: arcPositions[idx],
                billboard: {
                    image: _xMarkerCanvas,
                    width: 36,   // 显示大一些
                    height: 36,
                    verticalOrigin: Cesium.VerticalOrigin.CENTER,
                    horizontalOrigin: Cesium.HorizontalOrigin.CENTER
                }
            });
        }
    });
}

function removeBlockedXMarkers(lineId) {
    [0, 1, 2].forEach(i => {
        const xEnt = viewer.entities.getById(`arcx_${lineId}_${i}`);
        if (xEnt) viewer.entities.remove(xEnt);
    });
}

// === 自适应线宽 (根据相机高度缩放) ===
function makeAdaptiveWidth(baseWidth) {
    return new Cesium.CallbackProperty(() => {
        const alt = viewer.camera.positionCartographic.height;
        // 越放大（alt越小）线越细；全球视角（alt~10000km）保持粗线
        // scale: alt=2e7(全球) -> 2.0, alt=5e6(大陆) -> 1.0, alt=5e5(城市) -> 0.3
        const scale = Math.min(2.5, Math.max(0.2, alt / 1e7));
        return baseWidth * scale;
    }, false);
}

// === 3D 高度圆弧生成函数 ===
function compute3DArcPositions(lng1, lat1, lng2, lat2, segments) {
    const startCarto = Cesium.Cartographic.fromDegrees(lng1, lat1);
    const endCarto = Cesium.Cartographic.fromDegrees(lng2, lat2);
    const geodesic = new Cesium.EllipsoidGeodesic(startCarto, endCarto);
    const dist = geodesic.surfaceDistance;
    // 越远弧越高，设置最小弧高 120km 就〠距离财子市内也能显示
    const MIN_HEIGHT = 120000;
    const rawHeight = dist < 500000 ? dist * 0.3
                    : dist < 2000000 ? dist * 0.2
                    : dist * 0.18;
    const maxHeight = Math.max(rawHeight, MIN_HEIGHT);
    const segs = segments || (dist < 200000 ? 12 : dist < 500000 ? 20 : dist < 2000000 ? 35 : 50);

    const positions = [];
    for (let i = 0; i <= segs; i++) {
        const fraction = i / segs;
        const pt = geodesic.interpolateUsingFraction(fraction);
        const currentHeight = Math.sin(fraction * Math.PI) * maxHeight;
        positions.push(Cesium.Cartesian3.fromRadians(pt.longitude, pt.latitude, currentHeight));
    }
    return positions;
}

function updateGlobeThreatData() {
    // 使用基于 ID 的增量更新替换 removeAll，防止闪烁
    const currentIds = new Set(['server_target']);
    
    // 渲染基站 (Target) 仅在不存在时添加
    if (!viewer.entities.getById('server_target')) {
        viewer.entities.add({
            id: 'server_target',
            position: Cesium.Cartesian3.fromDegrees(TARGET_LOC.lng, TARGET_LOC.lat),
            point: {
                pixelSize: 10,
                color: Cesium.Color.WHITE,
                outlineColor: Cesium.Color.fromCssColorString('#3b82f6'),
                outlineWidth: 2
            },
            label: {
                text: 'Server',
                font: '14pt sans-serif',
                style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                outlineWidth: 2,
                verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                pixelOffset: new Cesium.Cartesian2(0, -9)
            }
        });
    }

    // IP 状态判断：活跃 (active) 或 封禁 (blocked)
    const isBlockedIp = (ip) => activeBannedIps.has(ip);
    const isActiveIp = (ip) => {
        for (const conn of activeConnections.values()) {
            if (conn.ip === ip) return true;
        }
        return false;
    };

    // 渲染攻击源点 (支持状态动态更新)
    attackPointsData.forEach(d => {
        const pointId = `pt_${d.lng}_${d.lat}`;
        currentIds.add(pointId);

        const blocked = isBlockedIp(d.ip);
        const active = isActiveIp(d.ip);
        
        let pColor, lColor;
        if (blocked) {
            pColor = Cesium.Color.RED;
            lColor = Cesium.Color.fromCssColorString('#ff6666');
        } else if (active) {
            pColor = Cesium.Color.GREEN;
            lColor = Cesium.Color.fromCssColorString('#86efac');
        } else {
            const isForeign = foreignHighlight && d.country && d.country !== HOME_COUNTRY;
            pColor = isForeign ? Cesium.Color.RED : Cesium.Color.fromCssColorString('#3b82f6');
            lColor = isForeign ? Cesium.Color.fromCssColorString('#ff6666') : Cesium.Color.fromCssColorString('#93c5fd');
        }

        const pointEntity = viewer.entities.getById(pointId);
        if (!pointEntity) {
            viewer.entities.add({
                id: pointId,
                position: Cesium.Cartesian3.fromDegrees(d.lng, d.lat),
                point: {
                    pixelSize: 6,
                    color: pColor
                },
                label: d.desc ? {
                    text: d.desc,
                    font: '12pt sans-serif',
                    fillColor: lColor,
                    style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                    outlineWidth: 1,
                    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                    pixelOffset: new Cesium.Cartesian2(0, -9)
                } : undefined
            });
            const pEnt = viewer.entities.getById(pointId);
            if (pEnt) pEnt._ipState = blocked ? 'blocked' : (active ? 'active' : 'historical');
        } else {
            const newState = blocked ? 'blocked' : (active ? 'active' : 'historical');
            if (pointEntity._ipState !== newState) {
                pointEntity.point.color = pColor;
                if (pointEntity.label) pointEntity.label.fillColor = lColor;
                pointEntity._ipState = newState;
            }
        }
    });

    // 渲染连线 (3 种线状态: 封禁=X+线段静态, 活跃=流光动画, 历史=静态纯色)
    attackArcsData.filter(d => d.arcType === 'base').forEach(d => {
        const lineId = `arc_${d.lng}_${d.lat}`;
        currentIds.add(lineId);

        const blocked = isBlockedIp(d.ip);
        const active = isActiveIp(d.ip);
        const newState = blocked ? 'blocked' : (active ? 'active' : 'historical');

        // 封禁状态的 X 标记实体也加入 currentIds
        if (blocked) {
            [0, 1, 2].forEach(i => currentIds.add(`arcx_${lineId}_${i}`));
        }

        let lineColor, material, lineWidth;
        if (blocked) {
            // 封禁连接：红色虚线 + 沿线三个 X billboard 标记
            lineColor = Cesium.Color.RED.withAlpha(0.8);
            material = new Cesium.PolylineDashMaterialProperty({
                color: lineColor,
                dashLength: 40.0,   // 较长的断居，线段更稀疆
                gapColor: Cesium.Color.TRANSPARENT
            });
            lineWidth = makeAdaptiveWidth(4);  // 封禁线细了
        } else if (active) {
            // 活跃连接：保持流光动画，绿色
            lineColor = Cesium.Color.GREEN;
            material = new FlyingLineMaterialProperty(lineColor, 800 + Math.random() * 500);
            lineWidth = makeAdaptiveWidth(4);  // 活跃线
        } else {
            // 非活跃/历史连接：静态纯色线，无动画
            const isForeign = foreignHighlight && d.country && d.country !== HOME_COUNTRY;
            lineColor = isForeign ? Cesium.Color.RED.withAlpha(0.85) : Cesium.Color.fromCssColorString('#60a5fa').withAlpha(0.85);
            material = new Cesium.ColorMaterialProperty(lineColor);
            lineWidth = makeAdaptiveWidth(2.5);  // 历史线
        }

        const lineEntity = viewer.entities.getById(lineId);
        if (!lineEntity) {
            const arcPositions = compute3DArcPositions(d.lng, d.lat, TARGET_LOC.lng, TARGET_LOC.lat);
            const ent = viewer.entities.add({
                id: lineId,
                polyline: {
                    positions: arcPositions,
                    width: lineWidth,
                    material: material
                }
            });
            ent._ipState = newState;
            if (blocked) addBlockedXMarkers(lineId, arcPositions);
        } else if (lineEntity._ipState !== newState) {
            // 状态变更：若原来是封禁状态需先清除 X 标记
            if (lineEntity._ipState === 'blocked') removeBlockedXMarkers(lineId);
            viewer.entities.remove(lineEntity);
            const arcPositions = compute3DArcPositions(d.lng, d.lat, TARGET_LOC.lng, TARGET_LOC.lat);
            const ent = viewer.entities.add({
                id: lineId,
                polyline: {
                    positions: arcPositions,
                    width: lineWidth,
                    material: material
                }
            });
            ent._ipState = newState;
            if (blocked) addBlockedXMarkers(lineId, arcPositions);
        }
    });

    // 移除过期实体
    const entitiesToRemove = [];
    viewer.entities.values.forEach(entity => {
        if (!currentIds.has(entity.id)) {
            entitiesToRemove.push(entity);
        }
    });
    
    entitiesToRemove.forEach(entity => {
        if (entity.id && (entity.id.startsWith('pt_') || entity.id.startsWith('arc_') || entity.id.startsWith('arcx_'))) {
            viewer.entities.remove(entity);
        }
    });
}
// ── WebSocket 连接 ──────────────────────────────────────

const wsIndicator = document.getElementById('ws-indicator');
const wsStatus = document.getElementById('ws-status');
wsIndicator.classList.add('connecting');

function setWsStatus(state) {
    wsIndicator.className = 'live-indicator';
    if (state === 'connected') {
        wsStatus.innerText = '服务正常';
    } else if (state === 'disconnected') {
        wsIndicator.classList.add('disconnected');
        wsStatus.innerText = '连接已断开';
    } else {
        wsIndicator.classList.add('connecting');
        wsStatus.innerText = '服务连接中...';
    }
}

const socket = io();

socket.on('connect', () => setWsStatus('connected'));
socket.on('disconnect', () => setWsStatus('disconnected'));
socket.on('connect_error', () => setWsStatus('disconnected'));

socket.on('init', (data) => {
    allIpData = data;
    updateFromData(data);
});

socket.on('new_ip', (loc) => {
    allIpData.push(loc);
    updateFromData(allIpData);
    if (document.getElementById('iplist-modal').classList.contains('active')) {
        filterIpTable();
    }
    addLogEntry(loc);
});

socket.on('update_ip', (data) => {
    let existing = allIpData.find(loc => loc.ip === data.ip && loc.module === data.module);
    if (existing) {
        existing.count = data.count;
        existing.time = data.time;
        updateFromData(allIpData);
        if (document.getElementById('iplist-modal').classList.contains('active')) {
            filterIpTable();
        }
        addLogEntry({ ...existing });
    }
});

socket.on('sys_log', (data) => {
    addSysLogEntry(data.msg, data.type, data.desc || '', data.ip || '', data.proxy || '', data.reason || '');
});

socket.on('event_log_init', (logs) => {
    (logs || []).forEach(e => {
        if (e.kind === 'conn') addLogEntry(e.data);
        else if (e.kind === 'disconn') addDisconnectLogEntry(e.data);
        else if (e.kind === 'sys') addSysLogEntry(e.data.msg, e.data.type, e.data.desc || '', e.data.ip || '', e.data.proxy || '', e.data.reason || '');
    });
});

// ── 活跃连接追踪 ────────────────────────────────────────

const activeConnections = new Map();
let activeRefreshTimer = null;

socket.on('active_init', (list) => {
    activeConnections.clear();
    (list || []).forEach(c => {
        activeConnections.set(c.remote_addr, c);
    });
    document.getElementById('active-count').innerText = activeConnections.size;
    renderActiveTable();
});

socket.on('connection_opened', (data) => {
    document.getElementById('active-count').innerText = data.active || 0;
    if (data.remote_addr) {
        activeConnections.set(data.remote_addr, {
            ip: data.ip, module: data.module,
            remote_addr: data.remote_addr,
            since: Math.floor(Date.now() / 1000),
            desc: data.desc || '', country: data.country || ''
        });
        renderActiveTable();
    }
});

socket.on('connection_closed', (data) => {
    document.getElementById('active-count').innerText = data.active || 0;
    if (data.remote_addr) {
        activeConnections.delete(data.remote_addr);
        renderActiveTable();
    }
    addDisconnectLogEntry(data);
});

function openActiveConns() {
    document.getElementById('active-modal').classList.add('active');
    renderActiveTable();
    if (activeRefreshTimer) clearInterval(activeRefreshTimer);
    activeRefreshTimer = setInterval(renderActiveTable, 1000);
}
function closeActiveConns() {
    document.getElementById('active-modal').classList.remove('active');
    if (activeRefreshTimer) { clearInterval(activeRefreshTimer); activeRefreshTimer = null; }
}
document.getElementById('active-modal').addEventListener('click', function (e) {
    if (e.target === this) closeActiveConns();
});

function renderActiveTable() {
    const tbody = document.getElementById('active-table-body');
    const nowSec = Math.floor(Date.now() / 1000);
    const entries = Array.from(activeConnections.values());

    // 按 ip+module 分组
    const groups = new Map();
    entries.forEach(c => {
        const gk = c.ip + '|' + c.module;
        if (!groups.has(gk)) {
            groups.set(gk, { ip: c.ip, module: c.module, desc: c.desc || '', country: c.country || '', conns: [] });
        }
        let port = '';
        if (c.remote_addr) {
            const parts = c.remote_addr.split(':');
            port = parts[parts.length - 1];
        }
        groups.get(gk).conns.push({ port, since: c.since || 0 });
    });

    const groupList = Array.from(groups.values());
    groupList.sort((a, b) => b.conns.length - a.conns.length);

    const totalConns = entries.length;
    const groupCount = groupList.length;
    document.getElementById('active-modal-count').innerText =
        groupCount ? `(${groupCount} 组 / ${totalConns} 连接)` : '';

    if (groupList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#555;padding:24px;">当前无活跃连接</td></tr>';
        return;
    }

    tbody.innerHTML = groupList.map((g, i) => {
        const earliest = Math.min(...g.conns.map(c => c.since));
        const elapsed = earliest ? nowSec - earliest : 0;
        const sortedConns = [...g.conns].sort((a, b) => a.since - b.since);

        return `<tr>
            <td style="color:#555;font-size:12px">${i + 1}</td>
            <td><span class="t-ip">${g.ip}</span></td>
            <td>${g.desc || '—'}</td>
            <td>${g.module ? `<span class="t-module">${g.module}</span>` : '<span style="color:#444">—</span>'}</td>
            <td style="text-align:center"><span class="port-badge" data-ports='${JSON.stringify(sortedConns.map(c => ({ port: c.port, since: c.since })))}'>${g.conns.length}</span></td>
            <td style="text-align:center; color:#10b981; font-family:ui-monospace,monospace; font-size:13px;">${formatDuration(elapsed)}</td>
        </tr>`;
    }).join('');
}

// ── 端口悬浮提示 (fixed positioning) ────────────────────

const portTip = document.getElementById('port-tooltip');
let _portTipTarget = null;

document.addEventListener('mouseover', function (e) {
    const badge = e.target.closest('.port-badge');
    if (!badge || !badge.dataset.ports) return;
    _portTipTarget = badge;
    const ports = JSON.parse(badge.dataset.ports);
    const nowSec = Math.floor(Date.now() / 1000);
    let html = '<div class="port-tip-header">源端口 / 连接时长</div>';
    ports.forEach(p => {
        const dur = p.since ? formatDuration(nowSec - p.since) : '?';
        html += `<div class="port-tip-row"><span style="color:#60a5fa">:${p.port}</span><span style="color:#10b981">${dur}</span></div>`;
    });
    portTip.innerHTML = html;
    const rect = badge.getBoundingClientRect();
    portTip.style.left = (rect.left + rect.width / 2 - 110) + 'px';
    portTip.style.top = (rect.top - portTip.offsetHeight - 8) + 'px';
    portTip.style.display = 'block';
    const tipRect = portTip.getBoundingClientRect();
    if (tipRect.top < 0) {
        portTip.style.top = (rect.bottom + 8) + 'px';
    }
});

document.addEventListener('mouseover', function (e) {
    // 鼠标移到其他非 badge 元素时隐藏
    if (!e.target.closest('.port-badge') && !e.target.closest('#port-tooltip') && _portTipTarget) {
        portTip.style.display = 'none';
        _portTipTarget = null;
    }
});

document.addEventListener('mouseleave', function () {
    portTip.style.display = 'none';
    _portTipTarget = null;
});

document.addEventListener('click', function (e) {
    if (!e.target.closest('.port-badge')) {
        portTip.style.display = 'none';
        _portTipTarget = null;
    }
});

document.addEventListener('scroll', function () {
    portTip.style.display = 'none';
    _portTipTarget = null;
}, true);

// ── 拦截记录追踪 ────────────────────────────────────────

const activeBannedIps = new Set(); // 当前实际封禁中的 IP

socket.on('blocked_update', (data) => {
    document.getElementById('blocked-count').innerText = data.blocked || 0;
});

const blockedRecords = [];

socket.on('blocked_init', (list) => {
    blockedRecords.length = 0;
    activeBannedIps.clear();
    if (Array.isArray(list)) {
        list.forEach(r => {
            blockedRecords.push(r);
            if (r.ip) activeBannedIps.add(r.ip);
        });
    }
    renderBlockedTable();
    updateGlobeThreatData();
});

socket.on('blocked_event', (rec) => {
    blockedRecords.push(rec);
    if (rec.ip) activeBannedIps.add(rec.ip);
    if (blockedRecords.length > 200) blockedRecords.splice(0, blockedRecords.length - 200);
    renderBlockedTable();

    // 若 blocked_event 携带了经纬度（封禁名单内 IP 再次访问），需注入绘图数据
    if (rec.ip && rec.lat && rec.lon) {
        // 检查 allIpData 里是否已有此 IP 的地理数据，没有则注入一条虚拟记录供画线用
        const existing = allIpData.find(d => d.ip === rec.ip && d.lat && d.lon);
        if (!existing) {
            const ghost = {
                ip: rec.ip, lat: rec.lat, lon: rec.lon,
                desc: rec.desc || '', country: rec.country || '',
                count: 1, time: new Date().toISOString(), _ghost: true
            };
            allIpData.push(ghost);
        }
        updateFromData(allIpData);
    } else {
        // 已有线条则刷新状态
        updateGlobeThreatData();
    }
});

socket.on('unban_ip', (data) => {
    if (data && data.ip) {
        activeBannedIps.delete(data.ip);
        // 解封后刷新地球线条状态（封禁→历史/活跃）
        updateGlobeThreatData();
    }
});

socket.on('blocked_geo_update', (rec) => {
    for (let i = blockedRecords.length - 1; i >= 0; i--) {
        const r = blockedRecords[i];
        if (r.ip === rec.ip && r.time === rec.time) {
            r.desc = rec.desc;
            r.country = rec.country;
            break;
        }
    }
    renderBlockedTable();

    // 若补全了经纬度，更新 allIpData 中的 ghost 记录并触发画线
    if (rec.ip && rec.lat && rec.lon) {
        const ghost = allIpData.find(d => d.ip === rec.ip && d._ghost);
        if (ghost) {
            ghost.lat = rec.lat;
            ghost.lon = rec.lon;
            ghost.desc = rec.desc || ghost.desc;
            ghost.country = rec.country || ghost.country;
            delete ghost._mappedData; // 清除缓存的 mapped 数据，强制重建
            delete ghost._baseArc;
            delete ghost._animArc;
        } else if (!allIpData.find(d => d.ip === rec.ip && d.lat && d.lon)) {
            allIpData.push({
                ip: rec.ip, lat: rec.lat, lon: rec.lon,
                desc: rec.desc || '', country: rec.country || '',
                count: 1, time: new Date().toISOString(), _ghost: true
            });
        }
        updateFromData(allIpData);
    }
});

function openBlockedModal() {
    document.getElementById('blocked-modal').classList.add('active');
    renderBlockedTable();
}
function closeBlockedModal() {
    document.getElementById('blocked-modal').classList.remove('active');
}
document.getElementById('blocked-modal').addEventListener('click', function (e) {
    if (e.target === this) closeBlockedModal();
});

function renderBlockedTable() {
    const tbody = document.getElementById('blocked-table-body');
    if (!tbody) return;
    document.getElementById('blocked-modal-count').innerText =
        blockedRecords.length ? `(${blockedRecords.length} 条)` : '';
    if (blockedRecords.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#555;padding:24px;">暂无拦截记录</td></tr>';
        return;
    }
    const reversed = [...blockedRecords].reverse();
    tbody.innerHTML = reversed.map((r, i) => {
        const idx = blockedRecords.length - i;
        const t = r.time ? new Date(r.time * 1000) : null;
        const timeStr = t ? t.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
        const reasonColor = r.reason === '自动封禁' ? '#f59e0b' : '#ef4444';
        return `<tr>
            <td style="color:#555;font-size:12px">${idx}</td>
            <td><span class="t-ip">${r.ip || '—'}</span></td>
            <td>${r.desc || '—'}</td>
            <td>${r.proxy ? `<span class="t-module">${r.proxy}</span>` : '<span style="color:#444">—</span>'}</td>
            <td><span style="color:${reasonColor};font-size:12px;">${r.reason || '—'}</span></td>
            <td style="font-family:ui-monospace,monospace;font-size:12px;color:#888;">${timeStr}</td>
        </tr>`;
    }).join('');
}

// ── 数据更新与球面渲染 ──────────────────────────────────

function updateFromData(data) {
    const activeData = data.filter(loc => !isExpired(loc)).slice(-60);
    const uniqueIps = new Set(data.map(loc => loc.ip)).size;
    const totalConns = data.reduce((sum, loc) => sum + (loc.count || 1), 0);

    document.getElementById('ip-count').innerText = uniqueIps;
    document.getElementById('conn-count').innerText = totalConns;

    attackPointsData = [];
    attackArcsData = [];

    activeData.filter(loc => loc.lat && loc.lon).forEach(loc => {
        if (!loc._mappedData) {
            loc._mappedData = {
                lat: loc.lat, lng: loc.lon, ip: loc.ip, desc: loc.desc, country: loc.country || ''
            };
            loc._baseArc = { ...loc._mappedData, arcType: 'base' };
            loc._animArc = { ...loc._mappedData, arcType: 'anim', _randGap: Math.random() * 2, _randTime: 2500 + Math.random() * 1500 };
        }
        attackPointsData.push(loc._mappedData);
        attackArcsData.push(loc._baseArc);
        attackArcsData.push(loc._animArc);
    });

    attackRingsData = attackPointsData.slice(-10);
    updateGlobeThreatData();
}

// 每分钟刷新球面，清除过期弧线
setInterval(() => updateFromData(allIpData), 60000);

// ── 日志渲染 ────────────────────────────────────────────

function addLogEntry(loc) {
    const entry = document.createElement('div');
    entry.className = 'log-entry';

    let timeStr = '';
    if (loc.time) {
        const t = new Date(loc.time.replace(' ', 'T'));
        timeStr = `${t.getHours().toString().padStart(2, '0')}:${t.getMinutes().toString().padStart(2, '0')}:${t.getSeconds().toString().padStart(2, '0')}`;
    } else {
        const now = new Date();
        timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
    }

    const moduleBadge = loc.module ? `<span class="module-badge">${loc.module}</span>` : '';
    const innerHTML = `
        <div><span class="timestamp">[${timeStr}]</span> <strong>${loc.ip}</strong>${moduleBadge}</div>
        <span class="geo">${loc.desc}</span>
    `;

    entry.innerHTML = innerHTML;
    logStream.insertBefore(entry, logStream.firstChild);
    if (logStream.children.length > 5) logStream.removeChild(logStream.lastChild);

    const allEntry = document.createElement('div');
    allEntry.className = 'log-entry';
    allEntry.innerHTML = innerHTML;
    allLogsStream.insertBefore(allEntry, allLogsStream.firstChild);
    if (allLogsStream.children.length > 1000) allLogsStream.removeChild(allLogsStream.lastChild);
}

function addSysLogEntry(msg, type, desc, ip, proxy, reason) {
    const entry = document.createElement('div');
    entry.className = 'log-entry';

    const color = type === 'unban' ? '#10b981' : '#ef4444';
    const bgColor = type === 'unban' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)';
    const title = type === 'unban' ? '系统操作' : '系统拦截';

    entry.style.background = bgColor;
    entry.style.borderLeft = `3px solid ${color}`;

    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

    let mainLine;
    if (ip && proxy) {
        // 拦截/自动封禁：显示 IP + 模块强调样式 + reason 标签
        const reasonBadge = reason
            ? `<span class="module-badge" style="background:rgba(239,68,68,0.15);color:#f87171;border-color:rgba(239,68,68,0.3);">${reason}</span>`
            : '';
        const moduleBadge = `<span class="module-badge" style="background:rgba(239,68,68,0.12);color:#fca5a5;border-color:rgba(239,68,68,0.25);">${proxy}</span>`;
        mainLine = `<span class="timestamp" style="color:${color}">[${timeStr}] ${title}</span> <strong>${ip}</strong>${moduleBadge}${reasonBadge}`;
    } else {
        // 手动封禁/解除封禁：保持原来简洁文本格式
        mainLine = `<span class="timestamp" style="color:${color}">[${timeStr}] ${title}</span> <strong>${msg}</strong>`;
    }

    const geoLine = desc ? `<span class="geo">${desc}</span>` : '';
    const innerHTML = `<div>${mainLine}</div>${geoLine}`;

    entry.innerHTML = innerHTML;

    entry.innerHTML = innerHTML;
    logStream.insertBefore(entry, logStream.firstChild);
    if (logStream.children.length > 5) logStream.removeChild(logStream.lastChild);

    const allEntry = document.createElement('div');
    allEntry.className = 'log-entry';
    allEntry.style.background = bgColor;
    allEntry.style.borderLeft = `3px solid ${color}`;
    allEntry.innerHTML = innerHTML;
    allLogsStream.insertBefore(allEntry, allLogsStream.firstChild);
    if (allLogsStream.children.length > 1000) allLogsStream.removeChild(allLogsStream.lastChild);
}

function addDisconnectLogEntry(data) {
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.style.borderLeftColor = '#10b981';
    let timeStr = '';
    if (data.time) {
        const t = new Date(data.time.replace(' ', 'T'));
        timeStr = `${t.getHours().toString().padStart(2, '0')}:${t.getMinutes().toString().padStart(2, '0')}:${t.getSeconds().toString().padStart(2, '0')}`;
    } else {
        const now = new Date();
        timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
    }
    const moduleBadge = data.module ? `<span class="module-badge" style="background:rgba(16,185,129,0.15);color:#10b981;border-color:rgba(16,185,129,0.3);">${data.module}</span>` : '';
    const dur = formatDuration(data.duration);
    const durationBadge = dur ? `<span class="module-badge" style="background:rgba(251,191,36,0.15);color:#fbbf24;border-color:rgba(251,191,36,0.3);">&#9201; ${dur}</span>` : '';
    const innerHTML = `
        <div><span class="timestamp" style="color:#10b981">[${timeStr}] 断开</span> <strong>${data.ip}</strong>${moduleBadge}${durationBadge}</div>
        <span class="geo">${data.desc || ''}</span>
    `;
    entry.innerHTML = innerHTML;
    logStream.insertBefore(entry, logStream.firstChild);
    if (logStream.children.length > 5) logStream.removeChild(logStream.lastChild);
    const allEntry = document.createElement('div');
    allEntry.className = 'log-entry';
    allEntry.style.borderLeftColor = '#10b981';
    allEntry.innerHTML = innerHTML;
    allLogsStream.insertBefore(allEntry, allLogsStream.firstChild);
    if (allLogsStream.children.length > 1000) allLogsStream.removeChild(allLogsStream.lastChild);
}

// ── 境外高亮切换 ────────────────────────────────────────

function updateHighlightBtn() {
    const btn = document.getElementById('highlight-btn');
    if (foreignHighlight) {
        btn.style.color = '#ef4444';
        btn.style.borderColor = 'rgba(239,68,68,0.4)';
    } else {
        btn.style.color = '';
        btn.style.borderColor = '';
    }
}
function toggleForeignHighlight() {
    foreignHighlight = !foreignHighlight;
    updateHighlightBtn();
    updateFromData(allIpData);
}
updateHighlightBtn();

// ── 面板折叠 ────────────────────────────────────────────

function togglePanel() {
    document.getElementById('ui-panel').classList.toggle('collapsed');
}

// ── IP 列表 & 访问控制弹窗 ─────────────────────────────

let allIpData = [];
let blockedIps = new Set();

function openIpList(e) {
    e.preventDefault();
    document.getElementById('ip-search-input').value = '';
    renderIpTable(allIpData.filter(loc => !blockedIps.has(loc.ip)));
    loadFirewallRules();
    document.getElementById('iplist-modal').classList.add('active');
}
function closeIpList() {
    document.getElementById('iplist-modal').classList.remove('active');
}
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelector(`.tab-btn[onclick*="${tabId}"]`).classList.add('active');
    document.getElementById(tabId).classList.add('active');
    if (tabId === 'tab-firewall') {
        loadFirewallRules();
    }
}

function blockIp(ip) {
    customDialog.confirm(`确定要封禁 ${ip} 吗？该 IP 后续连接将被 frp 直接拒绝。`, () => {
        fetch('/api/firewall/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip })
        }).then(r => r.json()).then(data => {
            if (data.status === 'success') {
                customDialog.alert(data.msg, () => loadFirewallRules());
            } else {
                customDialog.alert('封禁失败: ' + data.msg);
            }
        });
    });
}

function unblockIp(ip) {
    customDialog.confirm(`确定要解除对 ${ip} 的封禁吗？`, () => {
        fetch('/api/firewall/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip })
        }).then(r => r.json()).then(data => {
            if (data.status === 'success') {
                customDialog.alert(data.msg, () => loadFirewallRules());
            } else {
                customDialog.alert('解封失败: ' + data.msg);
            }
        });
    });
}

function loadFirewallRules() {
    fetch('/api/firewall').then(r => r.json()).then(res => {
        if (res.status === 'success') {
            const tbody = document.getElementById('firewall-table-body');
            const data = res.data;
            blockedIps = new Set(data.map(rule => rule.ip));
            filterIpTable();
            document.getElementById('fw-count').innerText = `(${data.length})`;
            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#666;padding:20px;">暂无封禁 IP</td></tr>';
                return;
            }
            tbody.innerHTML = data.map(rule => `
                <tr>
                    <td>${rule.num}</td>
                    <td><span class="t-ip" style="color:#ef4444">${rule.ip}</span></td>
                    <td>${rule.desc || '—'}</td>
                    <td style="text-align:center"><button class="btn-unblock" onclick="unblockIp('${rule.ip}')">解封</button></td>
                </tr>
            `).join('');
        }
    }).catch(err => {
        console.error('加载封禁列表失败', err);
    });
}

document.getElementById('iplist-modal').addEventListener('click', function (e) {
    if (e.target === this) closeIpList();
});

function renderIpTable(data) {
    const tbody = document.getElementById('ip-table-body');
    const reversed = [...data].reverse();
    tbody.innerHTML = reversed.map((loc, i) => `
        <tr title="${loc.ip}" style="${(loc.count || 1) >= FREQUENT_THRESHOLD ? 'background:rgba(239,68,68,0.15);' : ''}">
            <td style="color:#555;font-size:12px">${data.length - i}</td>
            <td><span class="t-ip" style="${(loc.count || 1) >= FREQUENT_THRESHOLD ? 'color:#fca5a5;' : ''}">${loc.ip}</span></td>
            <td title="${loc.desc || ''}">${loc.desc || '—'}</td>
            <td>${loc.module ? `<span class="t-module" title="${loc.module}">${loc.module}</span>` : '<span style="color:#444">—</span>'}</td>
            <td style="text-align:center; font-weight:bold; color: ${(loc.count || 1) >= FREQUENT_THRESHOLD ? '#ef4444' : '#10b981'};">${loc.count || 1}</td>
            <td style="color:#64748b;font-size:12px;font-family:ui-monospace,monospace">${loc.time || '—'}</td>
            <td style="text-align:center"><button class="btn-block" onclick="blockIp('${loc.ip}')">封禁</button></td>
        </tr>
    `).join('');
    document.getElementById('ip-count-info').innerText = `共 ${data.length} 条记录`;
}

function filterIpTable() {
    const q = document.getElementById('ip-search-input').value.toLowerCase();
    const freqOnly = document.getElementById('frequent-filter').checked;

    const unblockedData = allIpData.filter(loc => !blockedIps.has(loc.ip));
    let filtered = unblockedData;
    if (freqOnly) {
        filtered = filtered.filter(loc => (loc.count || 1) >= FREQUENT_THRESHOLD);
    }
    if (q) {
        filtered = filtered.filter(loc =>
            (loc.ip || '').toLowerCase().includes(q) ||
            (loc.desc || '').toLowerCase().includes(q) ||
            (loc.module || '').toLowerCase().includes(q)
        );
    }
    renderIpTable(filtered);
    document.getElementById('ip-count-info').innerText = `共 ${filtered.length} / ${unblockedData.length} 条记录`;
}

// ── 全部日志弹窗 ────────────────────────────────────────

function openAllLogs(e) {
    e.preventDefault();
    document.getElementById('all-logs-modal').classList.add('active');
}
function closeAllLogs() {
    document.getElementById('all-logs-modal').classList.remove('active');
}
document.getElementById('all-logs-modal').addEventListener('click', function (e) {
    if (e.target === this) closeAllLogs();
});

// ── 设置弹窗 ────────────────────────────────────────────

function openSettings(e) {
    e.preventDefault();
    document.getElementById('modal-msg').innerText = '加载配置中...';
    document.getElementById('modal-msg').style.color = '#888';

    document.getElementById('cfg_change_pwd').checked = false;
    document.getElementById('pwd_section').style.display = 'none';
    document.getElementById('m_old_pwd').value = '';
    document.getElementById('m_new_pwd').value = '';
    document.getElementById('m_confirm_pwd').value = '';

    document.getElementById('settings-modal').classList.add('active');

    fetch('/api/settings')
        .then(r => r.json())
        .then(res => {
            if (res.status === 'success') {
                document.getElementById('modal-msg').innerText = '';
                const cfg = res.data;
                document.getElementById('cfg_home_country').value = cfg.home_country || '';
                document.getElementById('cfg_frequent_threshold').value = cfg.frequent_threshold || 5;
                document.getElementById('cfg_foreign_highlight').checked = !!cfg.foreign_highlight;
                document.getElementById('cfg_admin_user').value = cfg.admin_username || '';

                const ab = cfg.auto_ban || {};
                document.getElementById('cfg_ban_enabled').checked = !!ab.enabled;
                document.getElementById('cfg_ban_foreign_only').checked = ab.foreign_only !== false;
                document.getElementById('cfg_ban_seconds').value = ab.threshold_seconds || 60;
                document.getElementById('cfg_ban_count').value = ab.threshold_count || 10;
                document.getElementById('cfg_ban_modules').value = (ab.whitelist_modules || []).join('\n');
                document.getElementById('cfg_ban_ips').value = (ab.whitelist_ips || []).join('\n');
            } else {
                document.getElementById('modal-msg').innerText = '配置加载失败';
                document.getElementById('modal-msg').style.color = '#ef4444';
            }
        });
}

function closeSettings() {
    document.getElementById('settings-modal').classList.remove('active');
}
document.getElementById('settings-modal').addEventListener('click', function (e) {
    if (e.target === this) closeSettings();
});

function saveSettings() {
    const msgEl = document.getElementById('modal-msg');

    const changePwd = document.getElementById('cfg_change_pwd').checked;
    const pwd1 = document.getElementById('m_new_pwd').value;
    const pwd2 = document.getElementById('m_confirm_pwd').value;
    if (changePwd && pwd1 !== pwd2) {
        msgEl.innerText = '两次输入的新密码不一致';
        msgEl.style.color = '#ef4444';
        return;
    }

    msgEl.innerText = '正在保存并应用修改...';
    msgEl.style.color = '#888';

    const payload = {
        home_country: document.getElementById('cfg_home_country').value.trim(),
        frequent_threshold: parseInt(document.getElementById('cfg_frequent_threshold').value) || 5,
        foreign_highlight: document.getElementById('cfg_foreign_highlight').checked,
        admin_username: document.getElementById('cfg_admin_user').value.trim() || 'root',
        auto_ban: {
            enabled: document.getElementById('cfg_ban_enabled').checked,
            foreign_only: document.getElementById('cfg_ban_foreign_only').checked,
            threshold_seconds: parseInt(document.getElementById('cfg_ban_seconds').value) || 60,
            threshold_count: parseInt(document.getElementById('cfg_ban_count').value) || 10,
            whitelist_modules: document.getElementById('cfg_ban_modules').value.split('\n').map(s => s.trim()).filter(Boolean),
            whitelist_ips: document.getElementById('cfg_ban_ips').value.split('\n').map(s => s.trim()).filter(Boolean)
        },
        change_pwd: changePwd,
        old_password: document.getElementById('m_old_pwd').value,
        new_password: pwd1
    };

    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            msgEl.style.color = '#10b981';
            msgEl.innerText = data.msg;
            foreignHighlight = payload.foreign_highlight;
            updateHighlightBtn();
            setTimeout(closeSettings, 1500);
        } else {
            msgEl.style.color = '#ef4444';
            msgEl.innerText = data.msg;
        }
    }).catch(() => {
        msgEl.style.color = '#ef4444';
        msgEl.innerText = '网络请求失败，请重试';
    });
}
