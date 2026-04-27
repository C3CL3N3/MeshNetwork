// =============================================
// GLOBAL VARIABLES
// =============================================
let currentTab = 'home';
let device, server, service, ctrlChar;

// LoRa metrics & graphing
let loraCsvRows  = [["Timestamp", "Direction", "Message", "LoRa_SNR", "LoRa_RSSI", "Hops"]];
let loraGraphData = [];

// =============================================
// UI & LOGGING
// =============================================
function log(msg) {
    const t = document.getElementById('terminal');
    if (!t) return;
    const time = new Date().toLocaleTimeString().split(' ')[0];
    t.innerHTML += `<div><span style="opacity:0.5">[${time}]</span> ${msg}</div>`;
    t.scrollTop = t.scrollHeight;
}

function setTab(id) {
    currentTab = id;
    document.querySelectorAll('.view-section').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const targetView = document.getElementById('view-' + id);
    if (targetView) targetView.classList.add('active');

    const btn = document.querySelector(`button[onclick="setTab('${id}')"]`);
    if (btn) btn.classList.add('active');

    if (id === 'lora' && loraGraphData.length > 0) setTimeout(drawLoraRssiChart, 100);
    if (id === 'mesh') setTimeout(meshResize, 50);
}

// =============================================
// BLUETOOTH CORE
// =============================================
async function connect() {
    try {
        const gidVal = document.getElementById('gid').value;
        const gid    = parseInt(gidVal);
        const hex    = gid.toString(16).padStart(2, '0');
        const base   = `13172b58-${hex}`;

        const freq  = 900 + (gid - 1);
        const badge = document.querySelector('.badge');
        if (badge) badge.innerText = `${freq} MHz`;
        document.getElementById('loraBadge').innerText = `${freq} MHz`;

        const UUIDS = {
            svc:  `${base}40-4150-b42d-22f30b0a0499`,
            ctrl: `${base}42-4150-b42d-22f30b0a0499`,
        };

        log(`Connecting Group ${gid}…`);

        device = await navigator.bluetooth.requestDevice({
            filters: [{ services: [UUIDS.svc] }],
            optionalServices: [UUIDS.svc]
        });
        device.addEventListener('gattserverdisconnected', onDisconnect);

        server  = await device.gatt.connect();
        service = await server.getPrimaryService(UUIDS.svc);

        ctrlChar = await service.getCharacteristic(UUIDS.ctrl);
        await ctrlChar.startNotifications();
        ctrlChar.addEventListener('characteristicvaluechanged', handleControlData);

        document.getElementById('connStatus').innerText = "Connected";
        document.getElementById('statusDot').classList.add('active');
        document.getElementById('conBtn').disabled  = true;
        document.getElementById('disBtn').disabled  = false;

        // Initialise mesh topology
        meshMyId = gid;
        meshNodes.clear();
        meshLinks.clear();
        meshParticles.length = 0;
        meshMsgCount = 0;
        document.getElementById('meshMsgCount').innerText  = '0';
        document.getElementById('meshNodeCount').innerText = '0';
        document.getElementById('meshMyNodeId').innerText  = `Node ${gid}`;
        document.getElementById('meshFreq').innerText      = `${freq} MHz`;
        const mc = document.getElementById('meshCanvas');
        meshNodes.set(meshMyId, {
            id: meshMyId, hops: 0, rssi: 0, snr: 0, msgCount: 0,
            x: mc ? mc.clientWidth  / 2 : 300,
            y: mc ? mc.clientHeight / 2 : 200,
            vx: 0, vy: 0, lastSeen: Date.now()
        });

        log("Connected!");
    } catch (e) {
        log("Error: " + e);
    }
}

function disconnect() {
    if (device && device.gatt.connected) device.gatt.disconnect();
}

function onDisconnect() {
    document.getElementById('connStatus').innerText = "Disconnected";
    document.getElementById('statusDot').classList.remove('active');
    document.getElementById('conBtn').disabled = false;
    document.getElementById('disBtn').disabled = true;
    log("Disconnected");
}

async function send(cmd) {
    if (!ctrlChar) return;
    const data = new TextEncoder().encode(cmd);
    try {
        if (ctrlChar.properties.writeWithoutResponse) await ctrlChar.writeValueWithoutResponse(data);
        else await ctrlChar.writeValue(data);
    } catch (e) { log("Tx Error: " + e); }
}

// =============================================
// LORA PLOTTING & CHAT
// =============================================
function drawLoraRssiChart() {
    const cv = document.getElementById('loraChartCanvas');
    if (!cv || loraGraphData.length === 0) return;

    const cx   = cv.getContext('2d');
    const w    = cv.width  = cv.clientWidth;
    const h    = cv.height = cv.clientHeight;
    cx.clearRect(0, 0, w, h);

    const padX = 40, padY = 20;
    const minX = loraGraphData[0].dist;
    const maxX = Math.max(loraGraphData[loraGraphData.length - 1].dist, minX + 1);
    const minY = -130, maxY = -10;

    function getX(val) { return padX + ((val - minX) / (maxX - minX)) * (w - padX * 2); }
    function getY(val) { return padY + (1 - ((val - minY) / (maxY - minY))) * (h - padY * 2); }

    cx.font = '10px Inter, sans-serif';
    cx.textAlign = 'right';
    cx.textBaseline = 'middle';
    cx.fillStyle = '#86868b';

    [-130, -100, -70, -40, -10].forEach(tick => {
        const yPos = getY(tick);
        cx.fillText(tick, padX - 8, yPos);
        cx.beginPath(); cx.strokeStyle = 'rgba(0,0,0,0.05)';
        cx.moveTo(padX, yPos); cx.lineTo(w - 10, yPos); cx.stroke();
    });

    cx.strokeStyle = 'rgba(0,0,0,0.15)';
    cx.beginPath(); cx.moveTo(padX, padY); cx.lineTo(padX, h - padY); cx.lineTo(w - 10, h - padY); cx.stroke();

    cx.strokeStyle = '#0071e3'; cx.lineWidth = 2; cx.beginPath();
    loraGraphData.forEach((pt, i) => {
        if (i === 0) cx.moveTo(getX(pt.dist), getY(pt.lora));
        else cx.lineTo(getX(pt.dist), getY(pt.lora));
    });
    cx.stroke();

    cx.textAlign = 'center';
    loraGraphData.forEach(pt => {
        cx.fillStyle = '#0071e3';
        cx.beginPath(); cx.arc(getX(pt.dist), getY(pt.lora), 4, 0, Math.PI * 2); cx.fill();
        cx.fillStyle = '#86868b';
        cx.fillText(pt.dist + 'm', getX(pt.dist), h - 5);
    });
}

function handleControlData(e) {
    const msg = new TextDecoder().decode(e.target.value);
    if (!msg || msg.length === 0) return;

    if (msg.startsWith("MESH_RX:")) { handleMeshRx(msg.substring(8)); return; }
    if (msg.startsWith("MESH_TX:")) { handleMeshTx(msg.substring(8)); return; }

    // Legacy format kept for backward compat
    if (msg.startsWith("LORA_RX:")) {
        const parts = msg.substring(8).split('|');
        if (parts.length >= 4) {
            const [snr, rssi, ble_rssi] = parts;
            const text = parts.slice(3).join('|');
            addChatBubble(`${text}\n<span style="font-size:0.75rem;opacity:0.7">[SNR:${snr} RSSI:${rssi} BLE:${ble_rssi}]</span>`, 'in');
            loraCsvRows.push([new Date().toISOString(), "RX", text, snr, rssi, ble_rssi]);
        }
        return;
    }

    log("Rx: " + msg);
}

async function sendLoRa() {
    const input = document.getElementById('loraTxt');
    if (input && input.value) {
        await send("SEND_MESH:" + input.value);
        addChatBubble(input.value, 'out');
        loraCsvRows.push([new Date().toISOString(), "TX", input.value, "", "", ""]);
        input.value = "";
    }
}

function downloadLoraCSV() {
    if (loraCsvRows.length < 2) { alert("No LoRa data to download yet."); return; }
    const content = loraCsvRows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([content], { type: 'text/csv' }));
    a.download = `lora_metrics_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

function addChatBubble(txt, type) {
    const box = document.getElementById('loraChat');
    if (!box) return;
    if (box.querySelector('.chat-placeholder')) box.innerHTML = '';
    const div = document.createElement('div');
    div.className = `msg ${type}`;
    div.innerHTML = txt;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}

// =============================================
// MESH NETWORK
// =============================================
const TTL_DEFAULT = 5;

let meshMyId      = 0;
let meshMsgCount  = 0;
const meshNodes     = new Map();
const meshLinks     = new Map();
const meshParticles = [];

function meshInit() {
    meshResize();
    meshAnimLoop();
    setInterval(updateMeshNodeList, 2000);
}

function meshResize() {
    const c = document.getElementById('meshCanvas');
    if (!c) return;
    c.width  = c.clientWidth;
    c.height = c.clientHeight;
    const myNode = meshNodes.get(meshMyId);
    if (myNode) { myNode.x = c.width / 2; myNode.y = c.height / 2; }
}

function meshAnimLoop() {
    if (document.getElementById('view-mesh')?.classList.contains('active')) {
        meshPhysicsStep();
        meshDraw();
    }
    requestAnimationFrame(meshAnimLoop);
}

function meshPhysicsStep() {
    const c = document.getElementById('meshCanvas');
    if (!c) return;
    const cx = c.width / 2, cy = c.height / 2;
    const nodes = [...meshNodes.values()];

    const myNode = meshNodes.get(meshMyId);
    if (myNode) { myNode.x = cx; myNode.y = cy; myNode.vx = 0; myNode.vy = 0; }

    for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i], b = nodes[j];
            const dx = b.x - a.x, dy = b.y - a.y;
            const d  = Math.sqrt(dx * dx + dy * dy) || 1;
            const f  = 3000 / (d * d);
            const fx = (dx / d) * f, fy = (dy / d) * f;
            if (a.id !== meshMyId) { a.vx -= fx; a.vy -= fy; }
            if (b.id !== meshMyId) { b.vx += fx; b.vy += fy; }
        }
    }

    nodes.forEach(n => {
        if (n.id === meshMyId) return;
        const targetR = 120 + (n.hops || 1) * 80;
        const dx = n.x - cx, dy = n.y - cy;
        const d  = Math.sqrt(dx * dx + dy * dy) || 1;
        const sf = (d - targetR) * 0.03;
        n.vx -= (dx / d) * sf; n.vy -= (dy / d) * sf;
    });

    nodes.forEach(n => {
        if (n.id === meshMyId) return;
        n.vx *= 0.85; n.vy *= 0.85;
        n.x  += n.vx; n.y  += n.vy;
        if (c) {
            n.x = Math.max(40, Math.min(c.width  - 40, n.x));
            n.y = Math.max(40, Math.min(c.height - 40, n.y));
        }
    });
}

function rssiColor(rssi) {
    if (rssi > -70) return '#30d158';
    if (rssi > -90) return '#ff9f0a';
    return '#ff453a';
}

function meshDraw() {
    const c = document.getElementById('meshCanvas');
    if (!c) return;
    const ctx = c.getContext('2d');
    const w = c.width, h = c.height, cx = w / 2, cy = h / 2;
    const now = Date.now();

    ctx.fillStyle = '#0c1020';
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = 'rgba(255,255,255,0.025)';
    for (let x = 0; x < w; x += 32)
        for (let y = 0; y < h; y += 32) {
            ctx.beginPath(); ctx.arc(x, y, 1, 0, Math.PI * 2); ctx.fill();
        }

    ctx.setLineDash([3, 8]);
    [120, 200, 280].forEach((r, i) => {
        ctx.strokeStyle = `rgba(255,255,255,${0.04 - i * 0.01})`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    });
    ctx.setLineDash([]);

    meshLinks.forEach((link, key) => {
        const [aId, bId] = key.split('-').map(Number);
        const a = meshNodes.get(aId), b = meshNodes.get(bId);
        if (!a || !b) return;
        const age = (now - link.lastActive) / 30000;
        ctx.globalAlpha = Math.max(0.08, 1 - age) * 0.75;
        ctx.strokeStyle = rssiColor(link.rssi || -100);
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        ctx.fillStyle = rssiColor(link.rssi || -100);
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(`${link.rssi} dBm`, (a.x + b.x) / 2, (a.y + b.y) / 2 - 9);
        ctx.globalAlpha = 1;
    });

    const myNode = meshNodes.get(meshMyId);
    meshNodes.forEach(n => {
        if (n.id === meshMyId || n.hops === 0 || !myNode) return;
        const age = (now - n.lastSeen) / 30000;
        ctx.globalAlpha = Math.max(0.04, 1 - age) * 0.4;
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 1; ctx.setLineDash([4, 7]);
        ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(myNode.x, myNode.y); ctx.stroke();
        ctx.setLineDash([]); ctx.globalAlpha = 1;
    });

    for (let i = meshParticles.length - 1; i >= 0; i--) {
        const p = meshParticles[i];
        p.t = (now - p.born) / 700;
        if (p.t >= 1) { meshParticles.splice(i, 1); continue; }
        const x = p.x0 + (p.x1 - p.x0) * p.t;
        const y = p.y0 + (p.y1 - p.y0) * p.t;
        ctx.globalAlpha = 1 - p.t;
        ctx.shadowColor = p.color; ctx.shadowBlur = 14;
        ctx.fillStyle = p.color;
        ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0; ctx.globalAlpha = 1;
    }

    meshNodes.forEach(n => {
        const isMe  = n.id === meshMyId;
        const age   = (now - n.lastSeen) / 60000;
        const alpha = Math.max(0.4, 1 - age * 0.5);
        const color = isMe ? '#007aff' : (n.hops === 0 ? rssiColor(n.rssi || -80) : '#636366');
        const r     = isMe ? 30 : 22;

        ctx.globalAlpha = alpha;
        ctx.shadowColor = color; ctx.shadowBlur = isMe ? 28 : 16;
        ctx.fillStyle = color;
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;

        if (isMe) {
            ctx.strokeStyle = 'rgba(255,255,255,0.25)'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(n.x, n.y, r + 7, 0, Math.PI * 2); ctx.stroke();
        }

        ctx.fillStyle = 'white';
        ctx.font = `bold ${isMe ? 14 : 12}px Inter, sans-serif`;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(`N${n.id}`, n.x, n.y);
        ctx.fillStyle = 'rgba(255,255,255,0.55)';
        ctx.font = '10px Inter, sans-serif';
        ctx.fillText(isMe ? 'YOU' : (n.hops === 0 ? 'direct' : `${n.hops}h`), n.x, n.y + r + 14);
        ctx.globalAlpha = 1;
    });
}

function meshAddOrUpdate(id, hops, rssi, snr) {
    const c  = document.getElementById('meshCanvas');
    const cx = c ? c.width  / 2 : 300;
    const cy = c ? c.height / 2 : 200;

    if (!meshNodes.has(id)) {
        const angle = Math.random() * Math.PI * 2;
        const dist  = 100 + hops * 80 + Math.random() * 30;
        meshNodes.set(id, {
            id, hops, rssi, snr, msgCount: 1,
            x: cx + Math.cos(angle) * dist,
            y: cy + Math.sin(angle) * dist,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
    } else {
        const n = meshNodes.get(id);
        n.hops = hops; n.rssi = rssi; n.snr = snr;
        n.msgCount++; n.lastSeen = Date.now();
    }

    const otherCount = [...meshNodes.keys()].filter(k => k !== meshMyId).length;
    document.getElementById('meshNodeCount').innerText = otherCount;
    updateMeshNodeList();
}

function updateMeshNodeList() {
    const list = document.getElementById('meshNodeList');
    if (!list) return;
    list.innerHTML = '';
    const now = Date.now();
    meshNodes.forEach(n => {
        if (n.id === meshMyId) return;
        const age   = Math.round((now - n.lastSeen) / 1000);
        const color = n.hops === 0 ? rssiColor(n.rssi || -100) : '#8e8e93';
        const el    = document.createElement('div');
        el.className = 'mesh-node-row';
        el.innerHTML = `
            <span class="mesh-node-id" style="color:${color}">N${n.id}</span>
            <span class="mesh-node-meta">
                ${n.hops === 0 ? `${n.rssi} dBm` : `${n.hops} hop${n.hops > 1 ? 's' : ''}`}
                &nbsp;·&nbsp;${age}s ago
            </span>`;
        list.appendChild(el);
    });
}

function handleMeshRx(data) {
    // format: src|mid|ttl|rssi|snr|payload
    const parts = data.split('|');
    if (parts.length < 6) return;
    const src     = parseInt(parts[0]);
    const mid     = parseInt(parts[1]);
    const ttl     = parseInt(parts[2]);
    const rssi    = parseFloat(parts[3]);
    const snr     = parseFloat(parts[4]);
    const payload = parts.slice(5).join('|');
    const hops    = TTL_DEFAULT - ttl;

    meshMsgCount++;
    document.getElementById('meshMsgCount').innerText = meshMsgCount;

    meshAddOrUpdate(src, hops, rssi, snr);

    if (hops === 0) {
        meshLinks.set(`${src}-${meshMyId}`, { rssi, snr, lastActive: Date.now() });
    }

    const srcNode = meshNodes.get(src);
    const myNode  = meshNodes.get(meshMyId);
    if (srcNode && myNode) {
        meshParticles.push({
            x0: srcNode.x, y0: srcNode.y,
            x1: myNode.x,  y1: myNode.y,
            color: rssiColor(rssi), born: Date.now(), t: 0
        });
    }

    const hopStr = hops === 0 ? 'direct' : `${hops} hop${hops > 1 ? 's' : ''}`;
    addMeshLog(`N${src} [${hopStr}] RSSI:${rssi} SNR:${snr}  "${payload}"`, 'rx');

    // Mirror to LoRa chat so both tabs stay in sync
    addChatBubble(
        `${payload}\n<span style="font-size:0.75rem;opacity:0.7">[N${src} · ${hopStr} · RSSI:${rssi} · SNR:${snr}]</span>`,
        'in'
    );
    loraCsvRows.push([new Date().toISOString(), "RX", payload, snr, rssi, hops]);

    // Auto-plot if payload is a distance string ("1m", "5 meters", …)
    const distMatch = payload.match(/^([\d.]+)\s*m(eter(s)?)?$/i);
    if (distMatch) {
        const distance = parseFloat(distMatch[1]);
        loraGraphData.push({ dist: distance, lora: rssi });
        loraGraphData.sort((a, b) => a.dist - b.dist);
        document.getElementById('loraGraphPanel').style.display = 'block';
        drawLoraRssiChart();
    }
}

function handleMeshTx(data) {
    const parts   = data.split('|');
    if (parts.length < 4) return;
    const payload = parts.slice(3).join('|');
    addMeshLog(`→ TX broadcast  "${payload}"`, 'tx');
}

function addMeshLog(msg, type) {
    const log = document.getElementById('meshLog');
    if (!log) return;
    const time = new Date().toLocaleTimeString().split(' ')[0];
    const div  = document.createElement('div');
    div.className = `mesh-log-entry mesh-log-${type || 'rx'}`;
    div.innerHTML = `<span class="mesh-log-time">[${time}]</span><span>${msg}</span>`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    while (log.children.length > 120) log.removeChild(log.firstChild);
}

async function sendMesh() {
    const input = document.getElementById('meshMsgInput');
    if (!input || !input.value.trim()) return;
    await send('SEND_MESH:' + input.value.trim());
    input.value = '';
}

// =============================================
// INITIALIZATION
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    meshInit();

    window.addEventListener('resize', () => {
        if (loraGraphData.length > 0) drawLoraRssiChart();
        meshResize();
    });
});
