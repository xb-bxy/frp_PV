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

// ── Globe 初始化 ────────────────────────────────────────

// 粒子贴图 (代替高耗能几何体)
const canvas = document.createElement('canvas');
canvas.width = 64; canvas.height = 64;
const context = canvas.getContext('2d');
const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
gradient.addColorStop(0, 'rgba(255,255,255,1)');
gradient.addColorStop(0.2, 'rgba(59, 130, 246, 1)');
gradient.addColorStop(0.5, 'rgba(59, 130, 246, 0.5)');
gradient.addColorStop(1, 'rgba(0,0,0,0)');
context.fillStyle = gradient;
context.fillRect(0, 0, 64, 64);
const particleTexture = new THREE.CanvasTexture(canvas);

const globeContainer = document.getElementById('globe-container');
const world = Globe()
    (globeContainer)
    .globeImageUrl(GLOBE_IMAGE_URL)
    .backgroundColor('#030305')
    .atmosphereAltitude(0.12)

    // 自定义精灵层 (替代高耗能 point 组件)
    .customLayerData([])
    .customThreeObject(d => {
        const group = new THREE.Group();

        const foreign = foreignHighlight && !d.isTarget && d.country && d.country !== HOME_COUNTRY;
        const material = new THREE.SpriteMaterial({
            map: particleTexture,
            color: d.isTarget ? 0xffffff : (foreign ? 0xff4444 : 0x3b82f6),
            transparent: true,
            blending: THREE.AdditiveBlending
        });
        const sprite = new THREE.Sprite(material);
        sprite.scale.set(d.isTarget ? 4 : 2.5, d.isTarget ? 4 : 2.5, 1);
        group.add(sprite);

        if (!d.isTarget && d.desc) {
            const textCanvas = document.createElement('canvas');
            textCanvas.width = 512;
            textCanvas.height = 128;
            const ctx = textCanvas.getContext('2d');
            ctx.font = 'bold 36px "Microsoft YaHei", sans-serif';
            ctx.fillStyle = foreign ? '#ff6666' : '#93c5fd';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(d.desc.replace(' - ', ' '), 256, 64);

            const textTexture = new THREE.CanvasTexture(textCanvas);
            textTexture.minFilter = THREE.LinearFilter;

            const textMaterial = new THREE.SpriteMaterial({
                map: textTexture,
                transparent: true,
                depthTest: false
            });
            const textSprite = new THREE.Sprite(textMaterial);
            textSprite.position.set(0, 1.8, 0);
            textSprite.scale.set(10, 2.5, 1);
            group.add(textSprite);
        }

        return group;
    })
    .customThreeObjectUpdate((obj, d) => {
        Object.assign(obj.position, world.getCoords(d.lat, d.lng, 0.01));
    })

    // 涟漪
    .ringColor(d => foreignHighlight && d.country && d.country !== HOME_COUNTRY
        ? 'rgba(239, 68, 68, 0.5)'
        : 'rgba(59, 130, 246, 0.4)'
    )
    .ringMaxRadius(2)
    .ringPropagationSpeed(1.5)
    .ringRepeatPeriod(2000)
    .ringResolution(12)

    // 弧线
    .arcStartLat(d => d.lat)
    .arcStartLng(d => d.lng)
    .arcEndLat(() => TARGET_LOC.lat)
    .arcEndLng(() => TARGET_LOC.lng)
    .arcColor(d => {
        const isForeign = foreignHighlight && d.country && d.country !== HOME_COUNTRY;
        if (d.arcType === 'base') {
            return isForeign
                ? ['rgba(239, 68, 68, 0.1)', 'rgba(239, 68, 68, 0.5)']
                : ['rgba(59, 130, 246, 0.1)', 'rgba(59, 130, 246, 0.5)'];
        } else {
            return isForeign
                ? ['rgba(255, 80, 80, 0.8)', 'rgba(255, 255, 255, 1)']
                : ['rgba(130, 180, 255, 0.8)', 'rgba(255, 255, 255, 1)'];
        }
    })
    .arcAltitudeAutoScale(0.3)
    .arcStroke(d => d.arcType === 'base' ? 0.3 : 0.9)
    .arcDashLength(d => d.arcType === 'base' ? 1 : 0.2)
    .arcDashGap(d => d.arcType === 'base' ? 0 : 0.8)
    .arcDashInitialGap(d => d.arcType === 'base' ? 0 : (d._randGap !== undefined ? d._randGap : Math.random()))
    .arcDashAnimateTime(d => d.arcType === 'base' ? 0 : (d._randTime || 2500))
    .arcsTransitionDuration(0);

world.pointOfView({ lat: TARGET_LOC.lat - 15, lng: TARGET_LOC.lng + 10, altitude: 2.2 });
world.controls().autoRotate = false;
world.controls().enableZoom = true;

window.addEventListener('resize', () => {
    world.width(window.innerWidth);
    world.height(window.innerHeight);
});

// ── Globe 数据 ──────────────────────────────────────────

const logStream = document.getElementById('log-stream');
const allLogsStream = document.getElementById('all-logs-stream');
let attackPointsData = [], attackArcsData = [], attackRingsData = [];

function updateGlobeThreatData() {
    const fullData = attackPointsData.concat([{ ...TARGET_LOC, isTarget: true }]);
    world.customLayerData(fullData);
    world.arcsData(attackArcsData);
    world.ringsData(attackRingsData);
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
    addSysLogEntry(data.msg, data.type);
});

socket.on('event_log_init', (logs) => {
    (logs || []).forEach(e => {
        if (e.kind === 'conn') addLogEntry(e.data);
        else if (e.kind === 'disconn') addDisconnectLogEntry(e.data);
        else if (e.kind === 'sys') addSysLogEntry(e.data.msg, e.data.type);
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
document.addEventListener('mouseover', function (e) {
    const badge = e.target.closest('.port-badge');
    if (!badge || !badge.dataset.ports) return;
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
document.addEventListener('mouseout', function (e) {
    const badge = e.target.closest('.port-badge');
    if (badge) portTip.style.display = 'none';
});

// ── 拦截记录追踪 ────────────────────────────────────────

socket.on('blocked_update', (data) => {
    document.getElementById('blocked-count').innerText = data.blocked || 0;
});

const blockedRecords = [];

socket.on('blocked_init', (list) => {
    blockedRecords.length = 0;
    if (Array.isArray(list)) {
        list.forEach(r => blockedRecords.push(r));
    }
    renderBlockedTable();
});

socket.on('blocked_event', (rec) => {
    blockedRecords.push(rec);
    if (blockedRecords.length > 200) blockedRecords.splice(0, blockedRecords.length - 200);
    renderBlockedTable();
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

function addSysLogEntry(msg, type) {
    const entry = document.createElement('div');
    entry.className = 'log-entry';

    const color = type === 'unban' ? '#10b981' : '#ef4444';
    const bgColor = type === 'unban' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)';
    const title = type === 'unban' ? '系统操作' : '系统拦截';

    entry.style.background = bgColor;
    entry.style.borderLeft = `3px solid ${color}`;

    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

    const innerHTML = `
        <div><span class="timestamp" style="color: ${color}">[${timeStr}] ${title}</span></div>
        <span class="geo" style="color: ${type === 'unban' ? '#34d399' : '#f87171'}; font-weight: bold; margin-top: 4px; display: block;">${msg}</span>
    `;

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
