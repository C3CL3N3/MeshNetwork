// =============================================
// GLOBAL VARIABLES
// =============================================
let currentTab = 'home';
let device, server, service, writeChar, notifyChar;


// =============================================
// UI & LOGGING
// =============================================
function log(msg) {
    const isErr = msg.startsWith('Error') || msg.toLowerCase().includes('error') || msg.startsWith('Flash error');
    if (isErr) console.error('[mesh]', msg);
    else       console.log('[mesh]', msg);

    // Update status dot text for connection events
    const status = document.getElementById('connStatus');
    if (status && (msg.includes('Connected') || msg.includes('disconnected') || msg.includes('Error') || msg.startsWith('Flash'))) {
        status.innerText = msg;
    }

    // Append to monitor box
    const box = document.getElementById('monitorBox');
    if (box) appendMonitorLine(box, msg, isErr ? ' monitor-err' : '', 200);
}

function appendMonitorLine(box, msg, extraClass = '', maxLines = 200) {
    if (!box) return;
    const empty = box.querySelector('.monitor-empty');
    if (empty) empty.remove();
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
    const line = document.createElement('div');
    line.className = 'monitor-line' + extraClass;
    line.textContent = `[${time}] ${msg}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
    while (box.children.length > maxLines) box.removeChild(box.firstChild);
}

function ensureMonitorPlaceholder(box, text) {
    if (!box) return;
    const hasRealLines = [...box.children].some(child => !child.classList.contains('monitor-empty'));
    if (hasRealLines || box.querySelector('.monitor-empty')) return;
    const line = document.createElement('div');
    line.className = 'monitor-line monitor-empty';
    line.textContent = text;
    box.appendChild(line);
}

function setTab(id) {
    currentTab = id;
    document.querySelectorAll('.view-section').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const targetView = document.getElementById('view-' + id);
    if (targetView) targetView.classList.add('active');

    const btn = document.querySelector(`button[onclick="setTab('${id}')"]`);
    if (btn) btn.classList.add('active');

    if (id === 'mesh') setTimeout(() => meshResize({ recenter: true, heat: false }), 50);
    if (id === 'control') setTimeout(() => { updateControlMap(); updateControlDstSelect(); }, 100);
}

// =============================================
// BLUETOOTH CORE
// =============================================

// Reconnect / keepalive state
let _gattUUIDs         = null;
let _userDisconnected  = false;
let _reconnectTimer    = null;
let _reconnectAttempts = 0;
let _keepaliveTimer    = null;
const _RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 15000]; // ms, last repeated

async function _setupGatt() {
    server  = await device.gatt.connect();
    service = await server.getPrimaryService(_gattUUIDs.svc);
    writeChar  = await service.getCharacteristic(_gattUUIDs.write);
    notifyChar = await service.getCharacteristic(_gattUUIDs.notify);
    await notifyChar.startNotifications();
    notifyChar.addEventListener('characteristicvaluechanged', handleControlData);
}

function _setConnectedUI(state) {
    // state: 'ok' | 'warn' | 'off'
    const dot    = document.getElementById('statusDot');
    const status = document.getElementById('connStatus');
    const conBtn = document.getElementById('conBtn');
    const disBtn = document.getElementById('disBtn');
    if (state === 'ok') {
        dot.className = 'dot ok'; status.innerText = 'connected';
        conBtn.disabled = true;  disBtn.disabled = false;
    } else if (state === 'warn') {
        dot.className = 'dot warn'; status.innerText = `reconnecting… (${_reconnectAttempts})`;
        conBtn.disabled = true;  disBtn.disabled = false;
    } else {
        dot.className = 'dot'; status.innerText = 'disconnected';
        conBtn.disabled = false; disBtn.disabled = true;
    }
}

function _startKeepalive() {
    _stopKeepalive();
    // Send a null byte every 15s — nRF strips it (replace '\x00',''), cmd check skips empty string.
    // Prevents browser GATT idle-disconnect.
    _keepaliveTimer = setInterval(async () => {
        if (!writeChar) return;
        try {
            const b = new Uint8Array([0]);
            if (writeChar.properties.writeWithoutResponse) await writeChar.writeValueWithoutResponse(b);
            else await writeChar.writeValue(b);
        } catch (_) { /* disconnect event fires separately */ }
    }, 15000);
}

function _stopKeepalive() {
    if (_keepaliveTimer) { clearInterval(_keepaliveTimer); _keepaliveTimer = null; }
}

async function _attemptReconnect() {
    if (!device || _userDisconnected) return;
    _reconnectAttempts++;
    const delay = _RECONNECT_DELAYS[Math.min(_reconnectAttempts - 1, _RECONNECT_DELAYS.length - 1)];
    log(`reconnect attempt ${_reconnectAttempts}…`);
    _setConnectedUI('warn');
    try {
        await _setupGatt();
        _reconnectAttempts = 0;
        _setConnectedUI('ok');
        _startKeepalive();
        log('✓ Reconnected');
    } catch (e) {
        log(`reconnect failed: ${e.message} — retry in ${delay / 1000}s`);
        _reconnectTimer = setTimeout(_attemptReconnect, delay);
    }
}

async function connect() {
    try {
        const gidVal = document.getElementById('gid').value;
        const gid    = parseInt(gidVal);
        const hex    = gid.toString(16).padStart(2, '0');
        const base   = `13172b58-${hex}`;

        const freq  = 900 + (gid - 1);
        const badge = document.querySelector('.badge');
        if (badge) badge.innerText = `${freq} MHz`;

        _gattUUIDs = {
            svc:    `${base}40-4150-b42d-22f30b0a0499`,
            write:  `${base}41-4150-b42d-22f30b0a0499`,
            notify: `${base}42-4150-b42d-22f30b0a0499`,
        };
        _userDisconnected = false;
        _reconnectAttempts = 0;

        log(`Connecting Group ${gid}…`);

        device = await navigator.bluetooth.requestDevice({
            filters:          [{ name: `MESH_G${gid}` }],
            optionalServices: [_gattUUIDs.svc],
        });
        device.addEventListener('gattserverdisconnected', onDisconnect);

        await _setupGatt();
        _setConnectedUI('ok');
        _startKeepalive();

        // Initialise mesh topology — use sentinel id=0 until MESH_INFO gives real NODE_ID
        meshMyId = 0;
        meshNodes.clear();
        meshLinks.clear();
        meshParticles.length = 0;
        meshMsgCount = 0;
        document.getElementById('meshMsgCount').innerText  = '0';
        document.getElementById('meshNodeCount').innerText = '0';
        document.getElementById('meshMyNodeId').innerText  = '…';

        const svg = document.getElementById('meshSvg');
        const w = svg ? svg.clientWidth  : 600;
        const h = svg ? svg.clientHeight : 400;
        meshNodes.set(0, {
            id: 0, hops: 0, rssi: 0, snr: 0, msgCount: 0, role: '?', stale: false,
            x: w / 2, y: h / 2, fx: w / 2, fy: h / 2,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
        meshD3Update();

        log('✓ Connected!');
    } catch (e) {
        log('Error: ' + e);
    }
}

function disconnect() {
    _userDisconnected = true;
    _stopKeepalive();
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    if (device && device.gatt.connected) device.gatt.disconnect();
}

function onDisconnect() {
    _stopKeepalive();
    writeChar = null; notifyChar = null;
    if (_userDisconnected) {
        _setConnectedUI('off');
        log('disconnected');
    } else {
        log('connection lost — auto-reconnecting…');
        _reconnectTimer = setTimeout(_attemptReconnect, _RECONNECT_DELAYS[0]);
    }
}

async function send(cmd) {
    if (!writeChar) return false;
    const data = new TextEncoder().encode(cmd);
    try {
        if (writeChar.properties.writeWithoutResponse) await writeChar.writeValueWithoutResponse(data);
        else await writeChar.writeValue(data);
        return true;
    } catch (e) {
        log('Tx Error: ' + e);
        return false;
    }
}

async function transportSend(cmd) {
    if (writeChar) {
        return await send(cmd);
    }
    log('No active BLE or serial transport.');
    return false;
}


function handleControlData(e) {
    const msg = new TextDecoder().decode(e.target.value);
    if (!msg || msg.length === 0) return;

    if (msg.startsWith("MESH_RX:"))     { handleMeshRx(msg.substring(8)); return; }
    if (msg.startsWith("MESH_TX:"))     { handleMeshTx(msg.substring(8)); return; }
    if (msg.startsWith("MESH_INFO:"))   { handleMeshInfo(msg.substring(10)); return; }
    if (msg.startsWith("MESH_ROUTE:"))  { handleMeshRoute(msg.substring(11)); return; }
    if (msg.startsWith("MESH_NB:"))     { handleMeshNeighbor(msg.substring(8)); return; }
    if (msg.startsWith("MESH_PING:"))   { /* heartbeat — silent */ return; }
    if (msg.startsWith("MESH_ERR:"))    { handleMeshErr(msg.substring(9)); return; }
    if (msg.startsWith("MESH_DROP:"))   { log("node_drop: " + msg.substring(10)); return; }
    if (msg.startsWith("MESH_TOPOLOGY:")) { handleMeshTopology(msg.substring(13)); return; }
    if (msg.startsWith("MESH_NODE_ADD:")) { handleMeshNodeAdd(parseInt(msg.substring(14))); return; }
    if (msg.startsWith("MESH_NODE_REMOVE:")) { handleMeshNodeRemove(parseInt(msg.substring(17))); return; }
    if (msg.startsWith("MESH_SF:"))         { updateSfDisplay(parseInt(msg.substring(8))); return; }
    if (msg.startsWith("MESH_ROUTE_MODE:")) { updateRouteModeDisplay(msg.substring(16)); return; }

    log("rx: " + msg);
}

function handleMeshErr(text) {
    const err = String(text || '');
    log("node_error: " + err);
    const noRoute = err.match(/^NO_ROUTE:(\d+)$/);
    if (!noRoute) return;
    const failedDst = noRoute[1];
    const selected = _selectedControlEndpoint();
    if (!selected || String(selected.id) !== failedDst) return;
    if (_ctlPending) {
        _ctlPending = false;
        _ctlAutoChain = false;
        _ctlMotion = null;
        if (_ctlAckTimer) { clearTimeout(_ctlAckTimer); _ctlAckTimer = null; }
        ctlLog('route failed to N' + failedDst + '; waypoint chain cancelled', 'ack-err');
        updateControlMap();
        updateWaypointList();
        return;
    }
    if (_ctlLastMove && (Date.now() - _ctlLastMove.at) <= 2000) {
        _ctlRoverX = _ctlLastMove.x;
        _ctlRoverY = _ctlLastMove.y;
        _ctlVisualRoverX = _ctlLastMove.visualX;
        _ctlVisualRoverY = _ctlLastMove.visualY;
        _ctlMotion = null;
        while (_ctlTrail.length > _ctlLastMove.trailLen) _ctlTrail.pop();
        _ctlLastMove = null;
        _ctlRebuildSegments();
        updateControlMap();
        updateWaypointList();
        ctlLog('route failed to N' + failedDst + '; local move reverted', 'ack-err');
    }
}

// ── Topology graph handlers ─────────────────────────────────────────────────

function handleMeshTopology(data) {
    const now = Date.now();
    if (data === 'none') {
        meshGraph.forEach(neighbors => {
            neighbors.forEach(info => {
                if (info.missedAt == null) info.missedAt = now;
            });
        });
        meshD3Update();
        addMeshLog('topology: 0 edges', 'rt');
        return;
    }
    const edges = data.split(';').filter(Boolean);
    const reported = new Set();
    for (const edge of edges) {
        const parts = edge.split(',').map(Number);
        const a = parts[0], b = parts[1], rssi = parts[2], snr = parts[3] ?? null;
        if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) continue;
        reported.add(meshEdgeKey(a, b));
        if (!meshGraph.has(a)) meshGraph.set(a, new Map());
        if (!meshGraph.has(b)) meshGraph.set(b, new Map());
        meshGraph.get(a).set(b, { rssi, snr, lastActive: now, missedAt: null });
        meshGraph.get(b).set(a, { rssi, snr, lastActive: now, missedAt: null });
    }
    meshGraph.forEach((neighbors, a) => {
        neighbors.forEach((info, b) => {
            if (!reported.has(meshEdgeKey(a, b)) && info.missedAt == null) {
                info.missedAt = now;
            }
        });
    });
    // Ensure referenced nodes exist, but do not count topology mentions as direct live presence.
    for (const [nid, neighbors] of meshGraph) {
        meshEnsureTopologyNode(nid, 1);
        for (const nbrId of neighbors.keys()) {
            meshEnsureTopologyNode(nbrId, 1);
        }
    }
    meshD3Update();
    addMeshLog(`topology: ${edges.length} edges`, 'rt');
}

function handleMeshNodeAdd(nodeId) {
    log(`topology: new node N${nodeId}`);
    meshEnsureTopologyNode(nodeId, 1);
    meshD3Update();
}

function handleMeshNodeRemove(nodeId) {
    log(`topology: node N${nodeId} removed`);
    meshGraph.delete(nodeId);
    for (const [nid, neighbors] of meshGraph) {
        neighbors.delete(nodeId);
    }
    // Don't remove from meshNodes — let stale detection handle it
    meshD3Update();
}

function handleMeshRoute(data) {
    // dest|next_hop|hops
    const [dest, nh, hops] = data.split('|');
    const destId  = parseInt(dest);
    const nhId    = parseInt(nh);
    const hopsNum = parseInt(hops);
    addMeshLog(`route N${dest}: next=N${nh} hops=${hops}`, 'rt');

    meshEnsureTopologyNode(destId, hopsNum);

    // Ensure relay (nh) node exists if not gateway
    if (nhId !== meshMyId) {
        meshEnsureTopologyNode(nhId, Math.max(1, hopsNum - 1));
    }

    // Only direct route ads represent a physical live local link. Multi-hop
    // route-table entries update reachability/hops, while physical relay links
    // come from topology snapshots so stale edges can fade correctly.
    if (destId === nhId) {
        meshMarkDirectNode(destId, 0, null, null, 1);
        const key = meshEdgeKey(destId, meshMyId);
        const existing = meshLinks.get(key);
        meshLinks.set(key, {
            rssi: existing ? existing.rssi : 0,
            snr:  existing ? existing.snr  : null,
            sf:   existing ? existing.sf   : undefined,
            hops: 0,
            lastActive: Date.now(),
            missedAt: null
        });
    }

    updateMeshNodeList();
    updateMeshDstSelect();
    meshD3Update();
}

function handleMeshNeighbor(data) {
    // node|rssi|snr|role  (role optional for backward compat)
    const parts = data.split('|');
    const nodeId  = parseInt(parts[0]);
    const rssiVal = parseFloat(parts[1]);
    const snrVal  = parseFloat(parts[2]);
    const role    = parts[3] || null;

    // Ensure node exists (direct neighbor = 1 hop)
    const existed = meshNodes.has(nodeId);
    meshMarkDirectNode(nodeId, rssiVal, snrVal, role, 1);
    if (!existed) {
        document.getElementById('meshNodeCount').innerText =
            [...meshNodes.keys()].filter(k => k !== meshMyId).length;
        updateMeshDstSelect();
    }

    // Always create/update the direct link
    meshLinks.set(meshEdgeKey(nodeId, meshMyId), { rssi: rssiVal, snr: snrVal, hops: 0, lastActive: Date.now(), missedAt: null });

    updateMeshNodeList();
    meshD3Update();
    addMeshLog(`neighbor N${nodeId}: rssi=${rssiVal} snr=${snrVal}`, 'rt');
}


// =============================================
// MESH NETWORK
// =============================================
const TTL_DEFAULT = 6;

let meshMyId      = 0;
let meshMsgCount  = 0;
const meshNodes     = new Map();
const meshLinks     = new Map();
const meshParticles = [];
const meshGraph     = new Map();  // Map<nodeId, Map<neighborId, {rssi, lastActive}>> — full topology

// D3 state
let meshSim          = null;
let meshSvgRoot      = null;
let meshZoomTransform = d3.zoomIdentity;
let selectedDst      = 0;
let _serialPort      = null;
let _serialWriter    = null;
let _particleId      = 0;
let _meshLayoutSignature = '';
let _meshLastSize = { w: 0, h: 0 };

// SF → link color (green=best, red=worst)
const STALE_TIMEOUT_MS = 12000;  // node considered stale after 12s no contact
const LINK_FADE_START_MS = 12000; // ordinary stale links turn dashed after 12s
const LINK_FADE_END_MS   = 30000; // dashed links fade out and disappear after 30s
const NODE_FADE_END_MS   = 150000; // disconnected nodes fade out after 2.5m

// Combined link quality — lower score = worse link. Uses both RSSI and SNR.
// RSSI: 0 (≤-120) to 90 (>-30). SNR: 0 (≤-15) to 35 (>20).
// Returns 0–125 where higher = better link.
function linkScore(rssi, snr) {
    const r = Math.max(-120, Math.min(-30, Number(rssi || -80)));
    const s = Math.max(-15, Math.min(20, Number(snr || 0)));
    const rScore = (r + 120) * (90 / 90);       // 0..90
    const sScore = (s + 15) * (35 / 35);         // 0..35
    return rScore + sScore;
}
// Link color based on combined quality
function linkQualityColor(rssi, snr) {
    const s = linkScore(rssi, snr);
    if (s > 80) return '#1A7F37';   // green — strong
    if (s > 50) return '#D29922';   // yellow — medium
    return '#CF222E';                // red — weak
}
function roleColor(role) {
    switch (role) {
        case 'C': return '#0969DA';  // blue — controller
        case 'E': return '#CF222E';  // red — endpoint
        case 'R': return '#1A7F37';  // green — relay
        default:  return '#8C959F';  // gray — unknown
    }
}

function meshEdgeKey(a, b) {
    return `${Math.min(a, b)}-${Math.max(a, b)}`;
}

function meshEnsureTopologyNode(id, hops = 1, role = null) {
    if (!Number.isFinite(id) || id === meshMyId) return;
    if (!meshNodes.has(id)) {
        meshAddOrUpdate(id, hops, 0, null, role || undefined);
        const n = meshNodes.get(id);
        if (n) {
            n._lastDirect = null;
            if (n._disconnectedSince == null) n._disconnectedSince = Date.now();
        }
    } else {
        const n = meshNodes.get(id);
        if (hops < (n.hops || 99)) n.hops = hops;
        if (role) n.role = role;
        n.gone = false;
    }
}

function meshMarkDirectNode(id, rssi = 0, snr = null, role = null, hops = 1) {
    if (!Number.isFinite(id) || id === meshMyId) return;
    if (!meshNodes.has(id)) {
        meshAddOrUpdate(id, hops, rssi, snr, role || undefined);
    }
    const n = meshNodes.get(id);
    if (!n) return;
    n.hops = Math.min(hops, n.hops || hops);
    if (Number.isFinite(rssi)) n.rssi = rssi;
    if (snr != null && Number.isFinite(snr)) n.snr = snr;
    if (role) n.role = role;
    n.lastSeen = Date.now();
    n._lastDirect = Date.now();
    n._disconnectedSince = null;
    n.stale = false;
    n.gone = false;
}

function meshInit() {
    const svgEl = document.getElementById('meshSvg');
    if (!svgEl) return;

    const svg = d3.select('#meshSvg');
    const w   = svgEl.clientWidth  || 600;
    const h   = svgEl.clientHeight || 400;
    svg.attr('width', w).attr('height', h);

    // Grid dot pattern background
    const defs = svg.append('defs');
    const pattern = defs.append('pattern')
        .attr('id', 'grid-dots').attr('width', 24).attr('height', 24)
        .attr('patternUnits', 'userSpaceOnUse');
    pattern.append('circle').attr('cx', 2).attr('cy', 2).attr('r', 1)
        .attr('fill', '#D0D7DE');
    svg.append('rect').attr('width', '100%').attr('height', '100%')
        .attr('fill', 'url(#grid-dots)');

    // Zoom
    const zoom = d3.zoom().scaleExtent([0.2, 4])
        .on('zoom', e => {
            meshZoomTransform = e.transform;
            if (meshSvgRoot) meshSvgRoot.attr('transform', e.transform);
        });
    svg.call(zoom);

    // Root group — layers in Z order
    meshSvgRoot = svg.append('g');
    meshSvgRoot.append('g').attr('class', 'mesh-rings');
    meshSvgRoot.append('g').attr('class', 'mesh-links');
    meshSvgRoot.append('g').attr('class', 'mesh-particles');
    meshSvgRoot.append('g').attr('class', 'mesh-nodes');

    // Force simulation — link distance varies with RSSI (strong=close, weak=far)
    function linkDistance(rssi, snr) {
        // Combined quality → distance: strong=close, weak=far
        const s = linkScore(rssi, snr);
        if (s > 80)      return 130 - (s - 80) * 3.0;       // green → 40–130px
        else if (s > 50) return 200 - (s - 50) * (70/30);   // yellow → 130–200px
        else             return 280 - s * (80/50);           // red → 200–280px
    }
    meshSim = d3.forceSimulation()
        .force('link', d3.forceLink().id(d => d.id).distance(d => linkDistance(d.rssi, d.snr)).strength(0.6))
        .force('charge', d3.forceManyBody().strength(d => (d._hasActiveLinks || d.id === meshMyId) ? -150 : 0))
        .force('collision', d3.forceCollide(40))
        .alphaDecay(0.08)
        .on('tick', meshD3Tick);

    meshAnimLoop();
    setInterval(updateMeshNodeList, 2000);
}

function meshResize(options = {}) {
    const svgEl = document.getElementById('meshSvg');
    if (!svgEl) return;
    const recenter = !!options.recenter;
    const heat = !!options.heat;
    const w = svgEl.clientWidth  || 600;
    const h = svgEl.clientHeight || 400;
    const cx = w / 2, cy = h / 2;
    const oldCx = (_meshLastSize.w || w) / 2;
    const oldCy = (_meshLastSize.h || h) / 2;
    const dx = cx - oldCx;
    const dy = cy - oldCy;
    _meshLastSize = { w, h };

    d3.select('#meshSvg').attr('width', w).attr('height', h);

    if (meshSim) {
        if (recenter && (dx || dy)) {
            meshNodes.forEach(n => {
                n.x = (n.x || cx) + dx;
                n.y = (n.y || cy) + dy;
                if (n.fx != null) n.fx += dx;
                if (n.fy != null) n.fy += dy;
            });
        }
        const gw = meshNodes.get(meshMyId);
        if (gw) { gw.x = cx; gw.y = cy; gw.fx = cx; gw.fy = cy; gw.vx = 0; gw.vy = 0; }
        if (heat) meshSim.alpha(Math.max(meshSim.alpha(), 0.04)).restart();
        else meshD3Tick();
    }
}

function meshUpdateSelection() {
    if (!meshSvgRoot) return;
    meshSvgRoot.select('.mesh-nodes').selectAll('g.mesh-node')
        .select('path.selection-ring')
        .attr('opacity', d => d.id === selectedDst ? 1 : 0);
}

function meshLayoutSignature(activeNodes, linksArr) {
    const nodes = activeNodes.map(n => `${n.id}:${n.role || '?'}`).sort().join(',');
    const links = linksArr.map(d => {
        const s = typeof d.source === 'object' ? d.source.id : d.source;
        const t = typeof d.target === 'object' ? d.target.id : d.target;
        return `${Math.min(s, t)}-${Math.max(s, t)}`;
    }).sort().join(',');
    return `${nodes}|${links}`;
}

function meshD3Update() {
    if (!meshSvgRoot || !meshSim) return;

    const svgEl = document.getElementById('meshSvg');
    const w  = svgEl ? (svgEl.clientWidth  || 600) : 600;
    const h  = svgEl ? (svgEl.clientHeight || 400) : 400;
    const cx = w / 2, cy = h / 2;

    const nodesArr = [...meshNodes.values()];

    // Ensure gateway starts pinned; meshResize owns later recentering.
    const gw = meshNodes.get(meshMyId);
    if (gw && gw.fx == null) { gw.x = cx; gw.y = cy; gw.fx = cx; gw.fy = cy; gw.vx = 0; gw.vy = 0; }

    const nowTs = Date.now();
    const goneNodes = new Set();

    // First pass: basic age properties
    nodesArr.forEach(n => {
        if (n.id === meshMyId) {
            n.lastSeen = nowTs; n.stale = false; n.gone = false; n._fade = 0;
            n._hasLinks = true; n._hasVisibleLinks = true; n._disconnectedSince = null;
            return;
        }
        n._fade = 0; n._hasLinks = false; n._hasVisibleLinks = false;
    });

    // Build links — include fading links (within LINK_FADE_END_MS), skip fully expired
    const linkByKey = new Map();
    function addConnectionLink(aId, bId, info, sourceKind) {
        if (aId === bId) return;
        const nodeA = meshNodes.get(aId);
        const nodeB = meshNodes.get(bId);
        if (!nodeA || !nodeB || nodeA.gone || nodeB.gone) return;
        const missedAge = info.missedAt != null ? (nowTs - info.missedAt) : null;
        const normalAge = nowTs - (info.lastActive || nowTs);
        const expired = missedAge != null
            ? missedAge > LINK_FADE_END_MS
            : normalAge > LINK_FADE_END_MS;
        if (expired) return;
        if (goneNodes.has(aId) || goneNodes.has(bId)) return;
        const key = meshEdgeKey(aId, bId);
        const existing = linkByKey.get(key);
        if (existing && existing.lastActive >= info.lastActive) return;
        const linkSnr = info.snr != null ? info.snr
            : (meshNodes.get(aId)?.snr ?? meshNodes.get(bId)?.snr ?? null);
        const linkFade = missedAge != null
            ? Math.max(0.01, Math.min(1, missedAge / LINK_FADE_END_MS))
            : Math.max(0, Math.min(1, (normalAge - LINK_FADE_START_MS) / (LINK_FADE_END_MS - LINK_FADE_START_MS)));
        const live = linkFade <= 0;
        linkByKey.set(key, {
            source: aId, target: bId,
            rssi: info.rssi, snr: linkSnr, sf: info.sf,
            hops: info.hops || 0, lastActive: info.lastActive,
            kind: sourceKind || 'connection',
            _fade: linkFade,
            _live: live
        });
    }
    meshLinks.forEach((link, key) => {
        const [aId, bId] = key.split('-').map(Number);
        if (aId === bId) { meshLinks.delete(key); return; }
        if (link.missedAt != null && nowTs - link.missedAt > LINK_FADE_END_MS) { meshLinks.delete(key); return; }
        if (link.missedAt == null && nowTs - (link.lastActive || 0) > LINK_FADE_END_MS) { meshLinks.delete(key); return; }
        addConnectionLink(aId, bId, link, 'route');
    });
    meshGraph.forEach((neighbors, srcId) => {
        neighbors.forEach((info, nbrId) => {
            if (info.missedAt != null && nowTs - info.missedAt > LINK_FADE_END_MS) {
                neighbors.delete(nbrId);
                return;
            }
            addConnectionLink(srcId, nbrId, info, 'topology');
        });
        if (neighbors.size === 0) meshGraph.delete(srcId);
    });
    const linksArr = [...linkByKey.values()];

    // Visible dashed links keep the topology stable until their 30s countdown ends.
    // Only live solid links keep nodes colored/connected.
    const visibleLinkNodes = new Set();
    const liveLinkNodes = new Set();
    linksArr.forEach(link => {
        const s = typeof link.source === 'object' ? link.source.id : link.source;
        const t = typeof link.target === 'object' ? link.target.id : link.target;
        visibleLinkNodes.add(s); visibleLinkNodes.add(t);
        if (link._live) { liveLinkNodes.add(s); liveLinkNodes.add(t); }
    });

    // Second pass: node fade, grey, freeze, unfreeze
    nodesArr.forEach(n => {
        if (n.id === meshMyId) return;
        n._hasLinks = liveLinkNodes.has(n.id);
        n._hasVisibleLinks = visibleLinkNodes.has(n.id);
        if (n._hasLinks) {
            n._disconnectedSince = null;
            n.gone = false;
            n._fade = 0;
            n.stale = false;
        } else {
            if (n._disconnectedSince == null) n._disconnectedSince = nowTs;
            const disconnectedAge = nowTs - n._disconnectedSince;
            n.gone = disconnectedAge > NODE_FADE_END_MS;
            n._fade = Math.max(0, Math.min(1, disconnectedAge / NODE_FADE_END_MS));
            n.stale = true;
        }
        if (n.gone) { goneNodes.add(n.id); n._fade = 1; return; }
        // Freeze only after all visible links are gone. While dashed links are
        // fading, they still hold the topology in place.
        if (!n._hasVisibleLinks && !n.gone && !n.pinned && n.fx == null && n._wasLinked) {
            const angle = Math.atan2(n.y - cy, n.x - cx) || Math.random() * Math.PI * 2;
            n.fx = cx + Math.cos(angle) * 310;
            n.fy = cy + Math.sin(angle) * 310;
        }
        if (n._hasVisibleLinks) { n._wasLinked = true; }
        // Unfreeze when a live link comes back — node jumps back into the layout
        if (n._hasLinks && !n.pinned && n.fx != null) {
            n.fx = null; n.fy = null;
        }
    });
    // Mark for forces
    meshNodes.forEach(n => { n._hasActiveLinks = n._hasVisibleLinks || n.id === meshMyId; });

    // Subtle dashed hop-distance rings
    const ringsG = meshSvgRoot.select('.mesh-rings');
    const ringRadii = [120, 200, 280];
    const ringsSel = ringsG.selectAll('circle.orbit-ring').data(ringRadii);
    ringsSel.enter().append('circle').attr('class', 'orbit-ring')
        .merge(ringsSel)
        .attr('cx', cx).attr('cy', cy)
        .attr('r', d => d)
        .attr('fill', 'none')
        .attr('stroke', '#D0D7DE')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '4,8');
    ringsSel.exit().remove();

    // Links
    const linksG  = meshSvgRoot.select('.mesh-links');
    // Key by ID — source/target are numbers when fresh, objects after D3 simulation resolves them
    const linkSel = linksG.selectAll('g.link-group').data(linksArr, d => {
        const s = typeof d.source === 'object' ? d.source.id : d.source;
        const t = typeof d.target === 'object' ? d.target.id : d.target;
        return `${s}-${t}`;
    });

    const linkEnter = linkSel.enter().append('g').attr('class', 'link-group mesh-link');
    linkEnter.append('line');
    linkEnter.append('text').attr('class', 'link-dbm')
        .attr('font-family', "'JetBrains Mono', monospace")
        .attr('font-size', '9px')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('paint-order', 'stroke')
        .attr('stroke', '#F6F9FC')
        .attr('stroke-width', 3)
        .attr('stroke-linejoin', 'round');
    linkEnter.append('text').attr('class', 'link-snr')
        .attr('font-family', "'JetBrains Mono', monospace")
        .attr('font-size', '9px')
        .attr('font-weight', '600')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('paint-order', 'stroke')
        .attr('stroke', '#F6F9FC')
        .attr('stroke-width', 3)
        .attr('stroke-linejoin', 'round');

    const linkMerge = linkEnter.merge(linkSel);
    // Line: solid when _fade=0, dashed + fading opacity as _fade→1
    linkMerge.select('line')
        .attr('stroke', d => d._fade > 0 ? '#D0D7DE' : linkQualityColor(d.rssi, d.snr))
        .attr('stroke-width', 2)
        .attr('stroke-opacity', d => Math.max(0, 0.7 * (1 - d._fade)))
        .attr('stroke-dasharray', d => d._fade > 0 ? '4,6' : null);
    // dBm label
    linkMerge.select('text.link-dbm')
        .attr('display', d => d._live && Number.isFinite(d.rssi) ? null : 'none')
        .attr('fill', d => {
            if (d._fade > 0) return '#D0D7DE';
            const c = linkQualityColor(d.rssi, d.snr);
            return c === '#1A7F37' ? '#0D4A1E' : c === '#D29922' ? '#8B5E00' : '#8B0000';
        })
        .attr('opacity', d => Math.max(0, 1 - d._fade))
        .text(d => {
            if (!Number.isFinite(d.rssi)) return '';
            return d._fade >= 1 ? '' : `${d.rssi}dBm`;
        });
    // SNR label
    linkMerge.select('text.link-snr')
        .attr('display', d => d._live && Number.isFinite(d.snr) ? null : 'none')
        .attr('fill', d => {
            if (d._fade > 0) return '#D0D7DE';
            if (d.snr == null) return 'transparent';
            const c = linkQualityColor(d.rssi, d.snr);
            return c === '#1A7F37' ? '#0D4A1E' : c === '#D29922' ? '#8B5E00' : '#8B0000';
        })
        .attr('opacity', d => Math.max(0, 1 - d._fade))
        .text(d => {
            if (!Number.isFinite(d.snr)) return '';
            return d._fade >= 1 ? '' : `SNR${Math.round(d.snr)}`;
        });

    linkSel.exit().remove();

    // Nodes — exclude gone nodes from SVG rendering
    const activeNodes = nodesArr.filter(n => !n.gone);
    const nodesG   = meshSvgRoot.select('.mesh-nodes');
    const nodeSel  = nodesG.selectAll('g.mesh-node').data(activeNodes, d => d.id);

    const nodeEnter = nodeSel.enter().append('g').attr('class', 'mesh-node');

    // Role-based shape path
    function shapePath(d, sz) {
        const s = sz || 20;
        switch (d.role) {
            case 'C': return `M0,${-s} L${s},0 L0,${s} L${-s},0 Z`;                // diamond
            case 'E': return `M${-s*0.85},${-s*0.85} L${s*0.85},${-s*0.85} L${s*0.85},${s*0.85} L${-s*0.85},${s*0.85} Z`;  // square
            case 'R': return `M0,${-s} L${s*0.87},${s*0.5} L${-s*0.87},${s*0.5} Z`; // triangle
            default:           return `M${-s},0 A${s},${s} 0 1,1 ${s},0 A${s},${s} 0 1,1 ${-s},0 Z`;  // circle
        }
    }
    function nodeSize(d) { return d.id === meshMyId ? 24 : 18; }

    nodeEnter.append('path').attr('class', 'node-shape');
    // Selection ring — larger accent outline
    nodeEnter.append('path').attr('class', 'selection-ring')
        .attr('fill', 'none')
        .attr('stroke', '#0969DA')
        .attr('stroke-width', 2);
    // Label
    nodeEnter.append('text').attr('class', 'node-label')
        .attr('font-family', "'JetBrains Mono', monospace")
        .attr('font-weight', '700')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle');
    // Sublabel
    nodeEnter.append('text').attr('class', 'node-sublabel')
        .attr('font-family', "'JetBrains Mono', monospace")
        .attr('font-size', '9px')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', '#8C959F');

    // Drag — gateway node is pinned, other nodes stay where the user places them.
    // Double-click a node to release its manual pin back to the live layout.
    const drag = d3.drag()
        .filter((event, d) => d.id !== meshMyId)
        .on('start', (event, d) => {
            if (!event.active) meshSim.alphaTarget(0.08).restart();
            d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => {
            if (!event.active) meshSim.alphaTarget(0);
            d.fx = event.x; d.fy = event.y;
            d.pinned = true;
            d.vx = 0; d.vy = 0;
        });

    nodeEnter.call(drag);

    // Click to select destination
    nodeEnter.on('click', (event, d) => {
        if (d.id === meshMyId) return;
        selectedDst = (selectedDst === d.id) ? 0 : d.id;
        const sel = document.getElementById('meshDstSelect');
        if (sel) sel.value = String(selectedDst);
        meshUpdateSelection();
    });
    nodeEnter.on('dblclick', (event, d) => {
        if (d.id === meshMyId) return;
        event.stopPropagation();
        d.pinned = false;
        d.fx = null; d.fy = null;
        meshSim.alpha(Math.max(meshSim.alpha(), 0.08)).restart();
        meshD3Update();
    });

    const nodeMerge = nodeEnter.merge(nodeSel);

    // All nodes: role-colored fill, black edges. Gateway: thicker border.
    nodeMerge.select('path.node-shape')
        .attr('d', d => shapePath(d, nodeSize(d)))
        .attr('fill', d => (d._hasLinks || d.id === meshMyId) ? roleColor(d.role) : '#8C959F')
        .attr('stroke', '#1F2328')
        .attr('stroke-width', d => d.id === meshMyId ? 3 : 2)
        .attr('opacity', d => Math.max(0.08, 1 - d._fade));

    nodeMerge.select('path.selection-ring')
        .attr('d', d => shapePath(d, nodeSize(d) + 8))
        .attr('opacity', d => d.id === selectedDst ? 1 : 0);

    nodeMerge.select('text.node-label')
        .attr('font-size', d => d.id === meshMyId ? '12px' : '11px')
        .attr('fill', d => '#FFFFFF')
        .attr('opacity', d => Math.max(0.08, 1 - d._fade))
        .text(d => {
            if (d.id === 0) return '?';
            const roleTag = d.role && d.role !== '?' ? d.role : '';
            return `N${d.id}${roleTag}`;
        });

    nodeMerge.select('text.node-sublabel')
        .attr('dy', d => (nodeSize(d)) + 14)
        .attr('opacity', d => Math.max(0, 1 - d._fade))
        .text(d => {
            if (d.id === meshMyId) return d.role || 'gateway';
            if (!d._hasLinks && d._fade > 0) return d._fade >= 1 ? '' : 'lost';
            return d.hops > 0 ? `${d.hops}hop` : '';
        });

    nodeSel.exit().remove();

    // Update simulation — exclude gone nodes
    const signature = meshLayoutSignature(activeNodes, linksArr);
    const layoutChanged = signature !== _meshLayoutSignature;
    _meshLayoutSignature = signature;
    meshSim.nodes(activeNodes);
    meshSim.force('link').links(linksArr);
    if (layoutChanged) {
        meshSim.alpha(Math.max(meshSim.alpha(), 0.14)).restart();
    } else {
        meshD3Tick();
    }
    if (document.getElementById('controlDstSelect')) updateControlDstSelect();
}

function meshD3Tick() {
    if (!meshSvgRoot) return;

    // Gateway is pinned by fx/fy. Avoid recalculating center on every tick;
    // panel resize handlers update it deliberately.
    if (meshMyId > 0) {
        const gw = meshNodes.get(meshMyId);
        if (gw && gw.fx != null) { gw.x = gw.fx; gw.y = gw.fy; gw.vx = 0; gw.vy = 0; }
    }

    // Update links
    meshSvgRoot.select('.mesh-links').selectAll('g.link-group').each(function(d) {
        const g    = d3.select(this);
        const src  = typeof d.source === 'object' ? d.source : meshNodes.get(d.source);
        const tgt  = typeof d.target === 'object' ? d.target : meshNodes.get(d.target);
        if (!src || !tgt) return;
        g.select('line')
            .attr('x1', src.x).attr('y1', src.y)
            .attr('x2', tgt.x).attr('y2', tgt.y);
        const mx = (src.x + tgt.x) / 2, my = (src.y + tgt.y) / 2;
        g.select('text.link-dbm')
            .attr('x', mx)
            .attr('y', my - 9);
        g.select('text.link-snr')
            .attr('x', mx)
            .attr('y', my + 9);
    });

    // Update nodes
    meshSvgRoot.select('.mesh-nodes').selectAll('g.mesh-node')
        .attr('transform', d => `translate(${d.x},${d.y})`);
}

function meshAnimLoop() {
    // Animate particles each rAF frame
    const particlesG = meshSvgRoot ? meshSvgRoot.select('.mesh-particles') : null;
    if (particlesG) {
        const now = Date.now();
        // Remove expired particles
        for (let i = meshParticles.length - 1; i >= 0; i--) {
            const p = meshParticles[i];
            const t = (now - p.born) / 700;
            if (t >= 1) meshParticles.splice(i, 1);
        }

        // Data join for SVG circles
        const circles = particlesG.selectAll('circle.mesh-pkt').data(meshParticles, d => d.id);

        circles.enter().append('circle')
            .attr('class', 'mesh-pkt')
            .attr('r', 5);

        particlesG.selectAll('circle.mesh-pkt').each(function(d) {
            const t       = (now - d.born) / 700;
            const srcNode = meshNodes.get(d.srcId);
            const dstNode = meshNodes.get(d.dstId);
            if (!srcNode || !dstNode) return;
            const x = srcNode.x + (dstNode.x - srcNode.x) * t;
            const y = srcNode.y + (dstNode.y - srcNode.y) * t;
            d3.select(this)
                .attr('cx', x).attr('cy', y)
                .attr('fill', d.color)
                .attr('opacity', 1 - t);
        });

        circles.exit().remove();
    }

    requestAnimationFrame(meshAnimLoop);
}

function meshAddOrUpdate(id, hops, rssi, snr, role) {
    const svgEl = document.getElementById('meshSvg');
    const cx    = svgEl ? (svgEl.clientWidth  || 600) / 2 : 300;
    const cy    = svgEl ? (svgEl.clientHeight || 400) / 2 : 200;

    if (!meshNodes.has(id)) {
        const angle = Math.random() * Math.PI * 2;
        const dist  = 100 + hops * 80 + Math.random() * 30;
        meshNodes.set(id, {
            id, hops, rssi, snr, msgCount: 1, role: role || '?', stale: false,
            x: cx + Math.cos(angle) * dist,
            y: cy + Math.sin(angle) * dist,
            vx: 0, vy: 0, lastSeen: Date.now(), _lastDirect: Date.now(), _wasLinked: false, pinned: false
        });
    } else {
        const n = meshNodes.get(id);
        n.hops = hops; n.rssi = rssi; n.snr = snr;
        n.msgCount++; n.lastSeen = Date.now(); n.stale = false;
        if (role) n.role = role;
    }

    const otherCount = [...meshNodes.values()].filter(n => n.id !== meshMyId && (n._fade || 0) < 1).length;
    document.getElementById('meshNodeCount').innerText = otherCount;
    updateMeshNodeList();
    updateMeshDstSelect();
    meshD3Update();
}

function updateMeshNodeList() {
    const list = document.getElementById('meshNodeList');
    if (!list) return;
    list.innerHTML = '';
    const now = Date.now();
    meshNodes.forEach(n => {
        if (n.id === meshMyId) return;
        const age      = Math.round((now - n.lastSeen) / 1000);
        const hasLinks = n._hasLinks;
        const fade     = n._fade || 0;
        const gone     = fade >= 1;
        const color    = roleColor(n.role);
        const el       = document.createElement('div');
        el.className = 'mesh-node-row' + (fade > 0 ? ' stale-row' : '') + (gone ? ' gone-row' : '');
        const roleLabel = n.role && n.role !== '?' ? ` ${n.role}` : '';
        let meta;
        if (gone) {
            meta = `lost &nbsp;·&nbsp;${age}s ago`;
        } else if (!hasLinks) {
            meta = `no links &nbsp;·&nbsp;${age}s ago`;
        } else if (n.hops === 0) {
            meta = `${n.rssi} dBm &nbsp;·&nbsp;${age}s ago`;
        } else {
            meta = `${n.hops} hop${n.hops > 1 ? 's' : ''} &nbsp;·&nbsp;${age}s ago`;
        }
        const opacity = gone ? 0.25 : (fade > 0 ? Math.max(0.4, 1 - fade) : 1);
        el.innerHTML = `
            <span class="mesh-node-id" style="color:${color};opacity:${opacity}">N${n.id}${roleLabel}</span>
            <span class="mesh-node-meta">${meta}</span>`;
        list.appendChild(el);
    });
}

function updateMeshDstSelect() {
    const sel = document.getElementById('meshDstSelect');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="0">broadcast</option><option value="255">echo_all [255]</option>';
    if (!writeChar && _serialMyId) {
        const selfOpt = document.createElement('option');
        selfOpt.value = 'self';
        selfOpt.textContent = `self [N${_serialMyId}]`;
        sel.appendChild(selfOpt);
    }
    meshNodes.forEach(n => {
        if (n.id === meshMyId) return;
        if ((n._fade || 0) >= 1) return;
        const opt = document.createElement('option');
        opt.value = String(n.id);
        opt.textContent = `N${n.id}`;
        sel.appendChild(opt);
    });
    // Restore previous selection if still valid
    if ([...sel.options].some(o => o.value === current)) {
        sel.value = current;
    } else {
        sel.value = '0';
        selectedDst = 0;
    }
}

function handleMeshInfo(data) {
    const match = data.match(/NODE_ID:(\d+)(?:\|SF:(\d+))?/);
    if (!match) return;
    const nodeId = parseInt(match[1]);
    if (match[2]) {
        updateSfDisplay(parseInt(match[2]));
    }
    // Parse role from MESH_INFO line
    const roleMatch = data.match(/\bROLE:(\w+)/);
    const role = roleMatch ? roleMatch[1] : 'R';
    const routeMatch = data.match(/\bROUTE:(fastest|reliable)\b/i);
    if (routeMatch) updateRouteModeDisplay(routeMatch[1]);

    if (nodeId === meshMyId) {
        // Update role on existing gateway node
        const gw = meshNodes.get(meshMyId);
        if (gw) {
            gw.role = role;
            gw.lastSeen = Date.now();
            gw.stale = false;
            gw.gone = false;
            meshD3Update();
        }
        return;
    }

    // Move gateway placeholder node to the real NODE_ID
    const svgEl = document.getElementById('meshSvg');
    const cx = svgEl ? svgEl.clientWidth  / 2 : 300;
    const cy = svgEl ? svgEl.clientHeight / 2 : 200;
    const oldNode = meshNodes.get(meshMyId);
    meshNodes.delete(meshMyId);
    meshMyId = nodeId;
    if (oldNode) {
        oldNode.id = meshMyId;
        oldNode.role = role;
        oldNode.fx = cx; oldNode.fy = cy;
        meshNodes.set(meshMyId, oldNode);
    } else {
        meshNodes.set(meshMyId, {
            id: meshMyId, role: role, hops: 0, rssi: 0, snr: 0, msgCount: 0, stale: false,
            x: cx, y: cy, fx: cx, fy: cy,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
    }
    document.getElementById('meshMyNodeId').innerText = `N${meshMyId}`;
    log(`Gateway NODE_ID = ${meshMyId}  role=${role}`);
    meshD3Update();

    // Pull current topology snapshot from gateway
    setTimeout(async () => {
        await send('NEIGHBORS');
        await new Promise(r => setTimeout(r, 150));
        await send('ROUTES');
    }, 200);
}

function handleMeshRx(data) {
    // format: src|dst|mid|ttl|rssi|snr|payload
    const parts = data.split('|');
    if (parts.length < 7) return;
    const src     = parseInt(parts[0]);
    const dst     = parseInt(parts[1]);
    const mid     = parseInt(parts[2]);
    const ttl     = parseInt(parts[3]);
    const rssi    = parseFloat(parts[4]);
    const snr     = parseFloat(parts[5]);
    const payload = parts.slice(6).join('|');
    const hops    = TTL_DEFAULT - ttl;

    _ctlConsumeAck(src, payload);

    meshMsgCount++;
    document.getElementById('meshMsgCount').innerText = meshMsgCount;

    if (hops === 0) {
        meshMarkDirectNode(src, rssi, snr, null, 1);
    } else {
        meshEnsureTopologyNode(src, hops);
        const nd = meshNodes.get(src);
        if (nd) {
            nd.rssi = rssi;
            nd.snr = snr;
        }
    }

    // Only draw a direct RF link when the packet arrived with 0 relays.
    // Multi-hop topology is built from MESH_ROUTE events instead.
    if (hops === 0) {
        const key = meshEdgeKey(src, meshMyId);
        const ex = meshLinks.get(key) || {};
        meshLinks.set(key, { rssi, snr, sf: ex.sf, hops: 0, lastActive: Date.now(), missedAt: null });
    } else {
        const ex = meshLinks.get(meshEdgeKey(src, meshMyId));
        if (ex) { ex.rssi = rssi; ex.snr = snr; }
    }

    // Particle from src to my node
    meshParticles.push({
        id: _particleId++,
        srcId: src,
        dstId: meshMyId,
        color: rssiColor(rssi),
        born: Date.now()
    });

    const hopStr = hops === 0 ? 'direct' : `${hops} hop${hops > 1 ? 's' : ''}`;
    addMeshLog(`N${src} [${hopStr}] RSSI:${rssi} SNR:${snr}  "${payload}"`, 'rx');
}

function handleMeshTx(data) {
    // format: src|dst|next_hop|mid|ttl|payload
    const parts = data.split('|');
    if (parts.length < 6) return;
    const dst     = parts[1];
    const payload = parts.slice(5).join('|');
    const dstLabel = dst === '0' ? 'broadcast' : `→ N${dst}`;
    addMeshLog(`→ TX [${dstLabel}] "${payload}"`, 'tx');
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

const CONTROL_PAYLOAD_PREFIXES = [
    'CMD:', 'ENDPOINT:', 'SERVO:', 'CAPS?', 'PING',
    'F', 'B', 'L', 'R', 'S', '+', '-',
    'H:', 'V:', 'HEADING:', 'SPEED:', 'FWD:', 'BACK:',
];

function isControlPayload(text) {
    return CONTROL_PAYLOAD_PREFIXES.some(prefix => String(text).startsWith(prefix));
}

function allowAddressedControl(dst, payload) {
    if (String(dst) !== '0' || !isControlPayload(payload)) return true;
    log('Control payloads must target a specific endpoint node, not broadcast.');
    return false;
}

async function sendMesh() {
    const input = document.getElementById('meshMsgInput');
    if (!input || !input.value.trim()) return;
    const msg = input.value.trim();
    const sel = document.getElementById('meshDstSelect');
    const dst = sel ? sel.value : '0';
    if (!allowAddressedControl(dst, msg)) return;
    const meshConvId = (dst === '0' || dst === 'self') ? 0 : parseInt(dst);
    input.value = '';

    if (writeChar) {
        if (dst === '0') await send('SEND_MESH:' + msg);
        else await send(`SEND_NODE:${dst}:${msg}`);
        addMeshLog(`→ BLE ${dst === '0' ? '[broadcast]' : `[N${dst}]`} "${msg}"`, 'tx');
        mirrorSerialOutgoingBubble(msg, Number.isFinite(meshConvId) ? meshConvId : 0);
        return;
    }
    if (_serialWriter) {
        if (!_serialMyId) {
            log('Serial connected, but mesh app is not detected yet. Wait for "Node ..." or "TX H ..." before sending.');
            return;
        }
        if (dst === '0' || dst === 'self') await _serialWriter.write(msg + '\n');
        else await _serialWriter.write(`TO:${dst}:${msg}\n`);
        const serialCmd = dst === '0' || dst === 'self' ? msg : `TO:${dst}:${msg}`;
        addMeshLog(`→ serial: "${serialCmd}"`, 'tx');
        mirrorSerialOutgoingBubble(msg, Number.isFinite(meshConvId) ? meshConvId : 0);
        return;
    }
    log('No active BLE or serial transport.');
}

function selectedMeshDestination() {
    const sel = document.getElementById('meshDstSelect');
    return sel ? sel.value : '0';
}

async function sendEndpointDebug(action) {
    const dst = selectedMeshDestination();
    if (dst === '0' || dst === 'self') {
        log('debug: select a specific endpoint node first (current: ' + dst + ')');
        return;
    }
    let payload = 'ENDPOINT:DEBUG:' + action;
    if (action === 'ON') {
        const target = meshMyId && meshMyId > 0 ? meshMyId : 1;
        payload += ':' + target;
    }
    log('debug: sending ' + payload + ' to N' + dst);
    if (writeChar) {
        await send('SEND_NODE:' + dst + ':' + payload);
        return;
    }
    if (_serialWriter) {
        if (!_serialMyId) {
            log('Serial connected, but mesh app not detected yet');
            return;
        }
        await _serialWriter.write('TO:' + dst + ':' + payload + '\n');
        addMeshLog('-> debug [N' + dst + ']: "' + payload + '"', 'tx');
        return;
    }
    log('No active BLE or serial transport.');
}

// ── Topology reporting toggle ───────────────────────────────────────────────

let _topoReporting = true;

async function toggleTopoReporting() {
    _topoReporting = !_topoReporting;
    const cmd = _topoReporting ? 'TOPO:ON' : 'TOPO:OFF';
    const btn = document.getElementById('topoToggleBtn');
    if (btn) {
        btn.textContent = _topoReporting ? 'topo: on' : 'topo: off';
        btn.style.background = _topoReporting ? 'var(--ok)' : 'var(--text-dim)';
    }
    await _sendTopoCmd(cmd);
    log(`topology reporting ${_topoReporting ? 'enabled' : 'disabled'}`);
}

async function setTopoInterval() {
    const input = document.getElementById('topoIntervalInput');
    const secs = parseInt(input?.value || '0', 10);
    if (isNaN(secs) || secs < 0) return;
    await _sendTopoCmd(`TOPO:INTERVAL:${secs}`);
    log(`topology interval set to ${secs}s`);
}

async function _sendTopoCmd(cmd) {
    if (writeChar) {
        await send(`SEND_MESH:${cmd}`);
    } else if (_serialWriter && _serialMyId) {
        await _serialWriter.write(cmd + '\n');
        addMeshLog(`→ serial: "${cmd}"`, 'tx');
    }
}

// ── Routing policy ─────────────────────────────────────────────────────────

function updateRouteModeDisplay(mode) {
    const normalized = String(mode || '').trim().toLowerCase();
    if (normalized !== 'fastest' && normalized !== 'reliable') return;
    const sel = document.getElementById('routeModeSelect');
    if (sel) sel.value = normalized;
}

async function setRouteMode(mode) {
    const normalized = String(mode || '').trim().toLowerCase();
    if (normalized !== 'fastest' && normalized !== 'reliable') return;
    updateRouteModeDisplay(normalized);
    const cmd = `ROUTE_MODE:${normalized}`;
    if (writeChar) {
        await send(cmd);
    } else if (_serialWriter && _serialMyId) {
        await _serialWriter.write(cmd + '\n');
        addMeshLog(`→ serial: "${cmd}"`, 'tx');
    }
    log(`routing mode set to ${normalized}`);
}

// ── SF control ──────────────────────────────────────────────────────────────

function setSfManual(value) {
    const cmd = value === 'AUTO' ? 'SF:AUTO' : `SF:${value}`;
    _sendTopoCmd(cmd);
}

function updateSfDisplay(sf) {
    const el = document.getElementById('meshSfDisplay');
    if (el) el.innerText = `SF${sf}`;
}

// =============================================
// SERIAL (ESP32)
// =============================================
let _serialReader = null;

async function connectSerial() {
    if (!navigator.serial) { log('Web Serial requires Chrome 89+'); return; }
    try {
        _serialPort = await navigator.serial.requestPort();
        await _serialPort.open({ baudRate: 115200 });

        // TX: PC → ESP32
        const enc = new TextEncoderStream();
        enc.readable.pipeTo(_serialPort.writable);
        _serialWriter = enc.writable.getWriter();

        // RX: ESP32 → dashboard log
        const dec = new TextDecoderStream();
        _serialPort.readable.pipeTo(dec.writable);
        _serialReader = dec.readable.getReader();
        _serialReadLoop(_serialReader);

        document.getElementById('serialSendRow').style.display = 'flex';
        document.getElementById('serialBtn').textContent = 'disconnect_usb';
        document.getElementById('serialBtn').onclick = serialTabToggle;
        _serialTabSetUI(true);
        log('ESP32 serial connected (TX + RX)');
        appendMonitorLine(document.getElementById('serialRawLog'), 'serial connected', '', 300);
    } catch (e) {
        if (e.name !== 'NotFoundError') log('Serial error: ' + e.message);
    }
}

function normalizeSerialMeshLine(line) {
    return String(line)
        // CircuitPython can emit terminal-title OSC sequences around reload output.
        .replace(/\x1B\][\s\S]*?(?:\x07|\x1B\\)/g, '')
        // Some browsers/log paths surface the OSC body without the leading ESC.
        .replace(/\]0;[^\[]*(?=\[)/g, '')
        .replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, '')
        .replace(/^\[\s*\d+(?:\.\d+)?\]\s*/, '')
        .trim();
}

async function _serialReadLoop(reader) {
    let buf = '';
    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += value;
            const lines = buf.split('\n');
            buf = lines.pop();
            lines.forEach(line => {
                try {
                const t = line.trim();
                if (!t) return;
                const parsed = normalizeSerialMeshLine(t);
                if (!parsed) return;

                // Classify for mesh log colour
                const type = parsed.startsWith('TX') ? 'tx'
                           : parsed.startsWith('RX')  ? 'rx'
                           : 'rt';
                addMeshLog(`[esp32] ${t}`, type);

                // Raw terminal in serial tab
                const rawBox = document.getElementById('serialRawLog');
                if (rawBox) {
                    appendMonitorLine(
                        rawBox,
                        t,
                        parsed.startsWith('RX') ? '' : parsed.startsWith('TX') ? ' monitor-tx' : '',
                        300
                    );
                }

                // Parse DELIVER → incoming chat bubble (new: "DELIVER C N1→N2 'payload'")
                const dlv = parsed.match(/DELIVER\s+(\w)\s+N(\d+)→N(\d+)\s+'?(.*?)'?\s*$/);
                if (dlv) {
                    const _src = parseInt(dlv[2]), _dst = parseInt(dlv[3]);
                    addSerialChatBubble(dlv[4], 'in', _dst === 0 ? 0 : _src);
                }

                // Parse RX H / RX D → node discovery for dst selector
                const rxNode = parsed.match(/RX_[HD]\s+N(\d+)/);
                if (rxNode) _serialTabNodeAdd(parseInt(rxNode[1]));

                // ── Serial → mesh viz ─────────────────────────────────────
                // Node identity: MESH_INFO, TX_H, or startup "Node X role=Y"
                const mStart = parsed.match(/^Node (\d+)\s+role=(\w)/);
                if (mStart) _serialMeshSetId(parseInt(mStart[1]), mStart[2]);
                const mInfo = parsed.match(/MESH_INFO:NODE_ID:(\d+)/);
                if (mInfo) {
                    const rm = parsed.match(/\bROLE:(\w)/);
                    _serialMeshSetId(parseInt(mInfo[1]), rm ? rm[1] : null);
                    const routeInfo = parsed.match(/\bROUTE:(fastest|reliable)\b/i);
                    if (routeInfo) updateRouteModeDisplay(routeInfo[1]);
                }
                // TX_H format: "TX_H N2|C|SF7" (from log_event)
                const mId = parsed.match(/TX_H N(\d+)\|(\w)\|/);
                if (mId) _serialMeshSetId(parseInt(mId[1]), mId[2]);

                // RX_H format: "RX_H N1|E|rssi=-79 snr=13" (from log_event)
                const mH = parsed.match(/RX_H N(\d+)\|(\w)\|rssi=(-?\d+)\s+snr=([-\d.]+)/);
                if (mH) _serialMeshNeighbor(parseInt(mH[1]), parseInt(mH[3]), parseFloat(mH[4]), mH[2]);

                // RX WELCOME: role learned from welcome (unchanged print)
                const mW = parsed.match(/RX WELCOME from N(\d+)\s+role=(\w)/);
                if (mW) _serialMeshUpdateRole(parseInt(mW[1]), mW[2]);

                // ROUTES_DUMP: controller dumps full route/neighbor table periodically.
                // Clear old route-derived links so the fresh dump replaces them.
                if (parsed === 'ROUTES_DUMP') {
                    meshLinks.forEach((link, key) => {
                        if (link.sourceKind === 'route') meshLinks.delete(key);
                    });
                } else {

                const mNb = parsed.match(/^NEIGHBOR:N(\d+)\|RSSI:(-?\d+)\|SNR:([-\d.]+)/);
                if (mNb) _serialMeshNeighbor(parseInt(mNb[1]), parseInt(mNb[2]), parseFloat(mNb[3]));

                // RX R format: "RX R N1←N2 hops=1 mid=3 →nh=N1 total=1 [NEW]" or "[known]"
                const mR = parsed.match(/RX R N(\d+)←N(\d+)\s+hops=\d+\s+mid=\d+\s+→nh=N(\d+)\s+total=(\d+)\s+\[(?:NEW|known)\]/);
                if (mR) _serialMeshRoute(parseInt(mR[1]), parseInt(mR[3]), parseInt(mR[4]), parseInt(mR[2]));

                const mRt = parsed.match(/^ROUTE:N(\d+)\|NH:N(\d+)\|HOPS:(\d+)/);
                if (mRt) _serialMeshRoute(parseInt(mRt[1]), parseInt(mRt[2]), parseInt(mRt[3]));

                // RX D format: "RX D N4→N3→N1 mid=5 ttl=4 rssi=-80 snr=13.0 'payload'"
                const mD = parsed.match(/RX D N(\d+)→(?:N(\d+)→)?N(\d+)\s+mid=\d+\s+ttl=(\d+)\s+rssi=(-?\d+)\s+snr=([-\d.]+)/);
                if (mD) _serialMeshData(parseInt(mD[1]), parseInt(mD[4]), parseInt(mD[5]), parseFloat(mD[6]));

                // RX D with WELCOME payload
                const mDw = parsed.match(/RX D N(\d+).*?'WELCOME:(\w)'/);
                if (mDw) _serialMeshUpdateRole(parseInt(mDw[1]), mDw[2]);

                // SF change: "SF_CHG 7→8" or "SF: locked to 8 (local)" or "SF: mode=auto (local)"
                const mSf = parsed.match(/SF_CHG\s+\d+→(\d+)/);
                if (mSf) updateSfDisplay(parseInt(mSf[1]));
                const mSfLock = parsed.match(/SF:\s+locked\s+to\s+(\d+)/);
                if (mSfLock) updateSfDisplay(parseInt(mSfLock[1]));
                const mSfAuto = parsed.match(/SF:\s+mode=auto/);
                if (mSfAuto) {
                    const sfSel = document.getElementById('sfSelect');
                    if (sfSel) sfSel.value = 'AUTO';
                }

                const mRouteMode = parsed.match(/^(?:MESH_)?ROUTE_MODE:(fastest|reliable)$/i);
                if (mRouteMode) updateRouteModeDisplay(mRouteMode[1]);

                const mTopology = parsed.match(/^MESH_TOPOLOGY:(.*)$/);
                if (mTopology) handleMeshTopology(mTopology[1]);

                // TOPO_EDGE: serial topology dump (from serial TOPOLOGY command)
                const mTe = parsed.match(/^TOPO_EDGE:N(\d+)-N(\d+)\|RSSI:(-?\d+)(?:\|SNR:([-\d.]+))?/);
                if (mTe) {
                    const na = parseInt(mTe[1]), nb = parseInt(mTe[2]), r = parseInt(mTe[3]);
                    const s = mTe[4] != null ? parseFloat(mTe[4]) : null;
                    if (!meshGraph.has(na)) meshGraph.set(na, new Map());
                    if (!meshGraph.has(nb)) meshGraph.set(nb, new Map());
                    meshGraph.get(na).set(nb, { rssi: r, snr: s, lastActive: Date.now(), missedAt: null });
                    meshGraph.get(nb).set(na, { rssi: r, snr: s, lastActive: Date.now(), missedAt: null });
                    meshEnsureTopologyNode(na, 1);
                    meshEnsureTopologyNode(nb, 1);
                    meshD3Update();
                }
                } // end else (not ROUTES_DUMP)
                } catch (err) {
                    log('Serial parse/render error: ' + (err && err.message ? err.message : err));
                }
            });
        }
    } catch (_) { /* port closed */ }
}

async function disconnectSerial() {
    // Clear state first so reconnect works even if close() throws
    const reader = _serialReader; _serialReader = null;
    const writer = _serialWriter; _serialWriter = null;
    const port   = _serialPort;   _serialPort   = null;
    try { if (reader) await reader.cancel(); } catch (e) { /* ignore */ }
    try { if (writer) await writer.close();   } catch (e) { /* ignore */ }
    try { if (port)   await port.close();     } catch (e) { /* ignore */ }
    document.getElementById('serialSendRow').style.display = 'none';
    const btn = document.getElementById('serialBtn');
    if (btn) { btn.textContent = 'connect_usb'; btn.onclick = serialTabToggle; }
    _serialTabSetUI(false);
    log('ESP32 serial disconnected');
    appendMonitorLine(document.getElementById('serialRawLog'), 'serial disconnected', '', 300);
}

async function sendSerial(msg) {
    const input = document.getElementById('serialInput');
    const text  = msg !== undefined ? msg : (input ? input.value.trim() : '');
    if (!text || !_serialWriter) return;
    if (!_serialMyId) {
        log('Serial connected, but mesh app is not detected yet. Wait for "Node ..." or "TX H ..." before sending.');
        return;
    }
    try {
        await _serialWriter.write(text + '\n');
        addMeshLog(`→ ESP32 serial: "${text}"`, 'tx');
        if (input) input.value = '';
    } catch (e) {
        log('Serial write error: ' + e.message);
    }
}

// =============================================
// SERIAL → MESH VIZ
// =============================================
let _serialMyId   = null;
let _serialMyRole = '?';

function _serialMeshSetId(id, role) {
    if (_serialMyId === id && (role == null || _serialMyRole === role)) {
        const n = meshNodes.get(id);
        if (n) {
            n.lastSeen = Date.now();
            n.stale = false;
            n.gone = false;
            if (role != null) n.role = role;
            meshD3Update();
        }
        if (n && meshMyId === id) return;
    }
    if (role != null) _serialMyRole = role;
    if (_serialMyId === id) {
        // same id, role updated — just refresh the node
        const n = meshNodes.get(id);
        if (n) {
            n.role = _serialMyRole;
            n.lastSeen = Date.now();
            n.stale = false;
            n.gone = false;
            meshD3Update();
        }
        if (n && meshMyId === id) return;
    }
    _serialMyId = id;
    if (writeChar) return; // BLE active — it owns the viz
    meshMyId = id;
    document.getElementById('meshMyNodeId').innerText = `N${id}`;
    meshNodes.clear(); meshLinks.clear(); meshParticles.length = 0;
    meshMsgCount = 0;
    document.getElementById('meshMsgCount').innerText = '0';
    document.getElementById('meshNodeCount').innerText = '0';
    const svgEl = document.getElementById('meshSvg');
    const cx = svgEl ? svgEl.clientWidth / 2 : 300;
    const cy = svgEl ? svgEl.clientHeight / 2 : 200;
    meshNodes.set(id, { id, hops: 0, rssi: 0, snr: 0, msgCount: 0,
        role: _serialMyRole, stale: false,
        x: cx, y: cy, fx: cx, fy: cy, vx: 0, vy: 0, lastSeen: Date.now() });
    meshD3Update();
    log(`serial node: N${id}  role=${_serialMyRole}`);
}

function _serialMeshNeighbor(nid, rssi, snr, role) {
    if (writeChar) return;
    meshMarkDirectNode(nid, rssi, snr, role, 1);
    if (_serialMyId) {
        meshLinks.set(meshEdgeKey(nid, _serialMyId), { rssi, snr, hops: 0, lastActive: Date.now(), missedAt: null });
        meshD3Update();
    }
}

function _serialMeshUpdateRole(nid, role) {
    if (writeChar) return;
    const n = meshNodes.get(nid);
    if (n && role) { n.role = role; meshD3Update(); }
}

function _serialMeshRoute(orig, nh, totalHops, fwd = null) {
    if (writeChar) return;
    meshEnsureTopologyNode(orig, totalHops);
    if (_serialMyId && nh !== _serialMyId) {
        meshEnsureTopologyNode(nh, Math.max(1, totalHops - 1));
    }
    if (_serialMyId && fwd != null && fwd !== _serialMyId) {
        meshMarkDirectNode(fwd, 0, null, null, 1);
    }

    // Direct route ads are reported as orig == next_hop. Draw local <-> orig,
    // not a self-link at orig, otherwise labels render on top of the node.
    if (orig === nh && (fwd == null || fwd === orig)) {
        meshMarkDirectNode(orig, 0, null, null, 1);
        const key = meshEdgeKey(meshMyId, orig);
        const existing = meshLinks.get(key);
        meshLinks.set(key, {
            rssi: existing ? existing.rssi : 0,
            snr:  existing ? existing.snr  : null,
            hops: 0,
            lastActive: Date.now(),
            missedAt: null,
            sourceKind: 'route'
        });
    }
    updateMeshNodeList(); updateMeshDstSelect(); meshD3Update();
}

function _serialMeshData(src, ttl, rssi, snr) {
    if (writeChar) return;
    const hops = TTL_DEFAULT - ttl;
    if (hops === 0) {
        meshMarkDirectNode(src, rssi, (snr != null) ? snr : null, null, 1);
        if (_serialMyId) {
            const key = meshEdgeKey(src, _serialMyId);
            const ex = meshLinks.get(key) || {};
            meshLinks.set(key, { rssi, snr, sf: ex.sf, hops: 0, lastActive: Date.now(), missedAt: null });
        }
    } else {
        meshEnsureTopologyNode(src, hops);
        const n = meshNodes.get(src);
        if (n) {
            n.rssi = rssi;
            if (snr != null) n.snr = snr;
        }
    }
    meshMsgCount++;
    document.getElementById('meshMsgCount').innerText = meshMsgCount;
    meshD3Update();
}

// =============================================
// SERIAL TAB — per-node conversations
// =============================================
let _serialActiveConv = 0;  // 0 = broadcast

function _serialTabSetUI(connected) {
    const btn   = document.getElementById('serialTabConnBtn');
    const badge = document.getElementById('serialTabBadge');
    if (btn)   btn.textContent = connected ? 'disconnect_usb' : 'connect_usb';
    if (badge) { badge.textContent = connected ? 'connected' : 'disconnected'; badge.style.color = connected ? 'var(--ok)' : ''; }
}

function _serialEnsureConv(id) {
    if (document.getElementById(`serialChat-${id}`)) return;

    const pane = document.createElement('div');
    pane.id = `serialChat-${id}`;
    pane.className = 'chat-area serial-chat-pane';
    document.getElementById('serialChatWrap').appendChild(pane);

    const item = document.createElement('div');
    item.className = 'serial-conv-item';
    item.dataset.convid = String(id);
    item.onclick = () => serialSelectConv(id);
    item.innerHTML = `<span class="conv-name">${id}</span><span class="conv-badge" id="convBadge-${id}"></span>`;
    document.getElementById('serialConvList').appendChild(item);
}

function _serialTabNodeAdd(id) {
    _serialEnsureConv(id);
}

function serialSelectConv(id) {
    _serialActiveConv = id;
    document.querySelectorAll('.serial-chat-pane').forEach(p => p.classList.remove('active-pane'));
    const pane = document.getElementById(`serialChat-${id}`);
    if (pane) pane.classList.add('active-pane');
    document.querySelectorAll('.serial-conv-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll(`.serial-conv-item[data-convid="${id}"]`).forEach(el => el.classList.add('active'));
    const title = document.getElementById('serialChatTitle');
    if (title) title.textContent = id === 0 ? 'broadcast' : String(id);
    const badge = document.getElementById(`convBadge-${id}`);
    if (badge) badge.textContent = '';
}

function addSerialChatBubble(text, type, srcId) {
    const convId = type === 'in' ? (srcId ?? 0) : _serialActiveConv;
    if (type === 'in') _serialEnsureConv(convId);

    const box = document.getElementById(`serialChat-${convId}`);
    if (!box) return;
    if (box.querySelector('.chat-placeholder')) box.innerHTML = '';

    const div = document.createElement('div');
    div.className = `msg ${type}`;
    const txt = document.createElement('span');
    txt.textContent = text;
    div.appendChild(txt);
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;

    if (type === 'in' && convId !== _serialActiveConv) {
        const badge = document.getElementById(`convBadge-${convId}`);
        if (badge) badge.textContent = (parseInt(badge.textContent) || 0) + 1;
    }
}

function mirrorSerialOutgoingBubble(text, convId) {
    if (typeof _serialEnsureConv === 'function') _serialEnsureConv(convId);
    const prevConv = _serialActiveConv;
    _serialActiveConv = convId;
    addSerialChatBubble(text, 'out');
    _serialActiveConv = prevConv;
}

async function serialTabToggle() {
    if (_serialPort) await disconnectSerial();
    else             await connectSerial();
}

async function serialTabSend() {
    const input = document.getElementById('serialMsgInput');
    if (!input || !input.value.trim()) return;
    if (!_serialWriter) { log('Serial not connected'); return; }
    if (!_serialMyId) {
        log('Serial connected, but mesh app is not detected yet. Wait for "Node ..." or "TX H ..." before sending.');
        return;
    }

    const text = input.value.trim();
    const dst  = _serialActiveConv;
    if (!allowAddressedControl(dst, text)) return;
    const cmd  = dst === 0 ? text : `TO:${dst}:${text}`;

    try {
        await _serialWriter.write(cmd + '\n');
        addSerialChatBubble(text, 'out', null);
        addMeshLog(`→ ESP32 serial: "${cmd}"`, 'tx');
    } catch (e) { log('Serial write error: ' + e.message); }
    input.value = '';
}


// =============================================
// FIRMWARE FLASH  — persistent CIRCUITPY handles via IndexedDB
// =============================================

// ── IndexedDB helpers ─────────────────────────────────────────────────────────
function _dbOpen() {
    return new Promise((res, rej) => {
        const req = indexedDB.open('mesh-flash-v1', 1);
        req.onupgradeneeded = e => e.target.result.createObjectStore('handles');
        req.onsuccess  = e => res(e.target.result);
        req.onerror    = e => rej(e.target.error);
    });
}
async function _handleGet(key) {
    try {
        const db = await _dbOpen();
        return await new Promise(res => {
            const tx = db.transaction('handles', 'readonly');
            tx.objectStore('handles').get(key).onsuccess = e => res(e.target.result ?? null);
        });
    } catch { return null; }
}
async function _handleSet(key, handle) {
    try {
        const db = await _dbOpen();
        await new Promise((res, rej) => {
            const tx = db.transaction('handles', 'readwrite');
            tx.objectStore('handles').put(handle, key);
            tx.oncomplete = res; tx.onerror = rej;
        });
    } catch { /* non-fatal */ }
}
async function _handleDel(key) {
    try {
        const db = await _dbOpen();
        await new Promise((res, rej) => {
            const tx = db.transaction('handles', 'readwrite');
            tx.objectStore('handles').delete(key);
            tx.oncomplete = res; tx.onerror = rej;
        });
    } catch { /* non-fatal */ }
}

// Verify or request write permission. Returns the handle or null.
async function _verifyPermission(handle) {
    const opts = { mode: 'readwrite' };
    if ((await handle.queryPermission(opts)) === 'granted') return handle;
    if ((await handle.requestPermission(opts)) === 'granted') return handle;
    return null;
}

async function _probeCircuitPyHandle(handle) {
    try {
        // boot_out.txt is normally present on CIRCUITPY and is safe to read.
        await handle.getFileHandle('boot_out.txt');
        return true;
    } catch {
        return false;
    }
}

// ── Drive status UI ───────────────────────────────────────────────────────────
async function _refreshDriveStatus(board) {
    const handle = await _handleGet('drive-' + board);
    const nameEl   = document.getElementById('driveName-' + board);
    const forgetEl = document.getElementById('forgetBtn-' + board);
    if (!nameEl) return;
    if (handle) {
        nameEl.textContent = handle.name;
        nameEl.style.color = 'var(--accent)';
        if (forgetEl) forgetEl.style.display = 'inline-block';
    } else {
        nameEl.textContent = '– (first flash: pick drive)';
        nameEl.style.color = '';
        if (forgetEl) forgetEl.style.display = 'none';
    }
}

async function forgetDrive(board) {
    await _handleDel('drive-' + board);
    await _refreshDriveStatus(board);
    log(`Drive forgotten for ${board}.`);
}

// ── Variant / node-id toggles ─────────────────────────────────────────────────
let _boardRoles = {
    nrf: 'C',
    esp32: 'R',
};
let _selectedFlashBoard = 'nrf';
let _flashNodeId  = 1;
let _controllerId = 1;   // auto-set when flashing a controller; used by endpoints to know where to report

const BOARD_ROLE_OPTIONS = {
    nrf: ['C', 'E'],
    esp32: ['C', 'R', 'E'],
};

function setFlashNodeId(n, btn) {
    _flashNodeId = n;
    btn.closest('#nodeIdCtrl').querySelectorAll('.var-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function setFlashBoard(board, btn) {
    _selectedFlashBoard = board;
    btn.closest('#boardCtrl').querySelectorAll('.var-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderRoleButtons();
    updateBoardRoleHints();
    updateFlashButtonLabel();
}

function setBoardRole(board, role, btn) {
    _boardRoles[board] = role;
    btn.closest('.variant-ctrl').querySelectorAll('.var-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    updateBoardRoleHints();
    updateFlashButtonLabel();
}

function renderRoleButtons() {
    const roleCtrl = document.getElementById('roleCtrl');
    if (!roleCtrl) return;
    roleCtrl.innerHTML = '';
    const board = _selectedFlashBoard;
    const selectedRole = _boardRoles[board];
    BOARD_ROLE_OPTIONS[board].forEach(role => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'var-btn' + (role === selectedRole ? ' active' : '');
        button.textContent = role;
        button.onclick = () => setBoardRole(board, role, button);
        roleCtrl.appendChild(button);
    });
}

function updateBoardRoleHints() {
    const hint = document.getElementById('flashRoleHint');
    if (!hint) return;
    const board = _selectedFlashBoard;
    const role = _boardRoles[board];
    if (board === 'nrf') {
        if (role === 'E') hint.textContent = '// nRF endpoint — software endpoint, useful for packet tests';
        else hint.textContent = '// BLE gateway controller, recommended default for nRF52840';
        return;
    }
    if (role === 'C') hint.textContent = '// ESP32 controller — supported, but nRF is the preferred BLE gateway';
    else if (role === 'E') hint.textContent = '// endpoint node — addressed CAPS?, PING, SERVO:<angle>';
    else hint.textContent = '// relay node only routes and forwards addressed packets';
}

function updateFlashButtonLabel() {
    const button = document.getElementById('btnFlashSelected');
    if (!button) return;
    const label = _selectedFlashBoard === 'nrf' ? 'flash nrf52840' : 'flash esp32_s3';
    button.innerHTML = `
        <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" style="margin-right:5px">
            <path d="M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM17 13l-5 5-5-5h3V9h4v4h3z"/>
        </svg>
        <span id="btnFlashSelectedLabel">${label}</span>
    `;
}

const STRUCTURED_FW_FILES = [
    ['../toDevice/sx1262.py',    'sx1262.py'],
    ['../toDevice/mesh_core.py', 'mesh_core.py'],
    ['../toDevice/code.py',      'code.py'],
];

function firmwareSettings(board) {
    const role = _boardRoles[board];
    // When flashing a controller, remember its ID so endpoints know where to report
    if (role === 'C') _controllerId = _flashNodeId;
    return {
        groupId: parseInt(document.getElementById('gid')?.value || '13', 10),
        nodeId: _flashNodeId,
        boardProfile: board === 'nrf' ? 'nrf52840_sx1262' : 'esp32_sx1262',
        role,
        controllerId: _controllerId,
    };
}

function validateFirmwareSettings(settings) {
    // No restrictions — any role can use any node ID.
}

function pythonBool(value) {
    return value ? 'True' : 'False';
}

function patchFirmwareSettings(path, content, settings) {
    if (path !== 'mesh_core.py') return content;
    return content
        .replace(/^GROUP_ID\s*=\s*\d+/m, `GROUP_ID = ${settings.groupId}`)
        .replace(/^NODE_ID\s*=\s*\d+/m, `NODE_ID = ${settings.nodeId}`)
        .replace(/^BOARD_PROFILE\s*=\s*["'][^"']+["'].*$/m, `BOARD_PROFILE = "${settings.boardProfile}"`)
        .replace(/^ROLE\s*=\s*["'][^"']+["'].*$/m, `ROLE = "${settings.role}"`)
        .replace(/^ALLOW_EXTERNAL_COMMANDS\s*=.*$/m, `ALLOW_EXTERNAL_COMMANDS = ${pythonBool(settings.role === 'C')}`)
        .replace(/^REPORT_TOPOLOGY\s*=.*$/m, `REPORT_TOPOLOGY = ${pythonBool(settings.role !== 'C')}`)
        .replace(/^CONTROLLER_ID\s*=\s*\d+/m, `CONTROLLER_ID = ${settings.controllerId}`);
}

function orderFirmwareForWrite(firmware) {
    // Write the entrypoint last so CIRCUITPY does not reload mid-flash.
    return [...firmware].sort((a, b) => {
        if (a[0] === 'code.py') return 1;
        if (b[0] === 'code.py') return -1;
        return a[0].localeCompare(b[0]);
    });
}

async function getSubdirectory(root, path) {
    let dir = root;
    if (!path) return dir;
    for (const part of path.split('/')) {
        if (part) dir = await dir.getDirectoryHandle(part, { create: true });
    }
    return dir;
}

async function writeFirmwareFile(root, path, text) {
    const slashAt = path.lastIndexOf('/');
    const dirPath = slashAt >= 0 ? path.slice(0, slashAt) : '';
    const fileName = slashAt >= 0 ? path.slice(slashAt + 1) : path;
    const dir = await getSubdirectory(root, dirPath);
    const fh = await dir.getFileHandle(fileName, { create: true });
    const wr = await fh.createWritable();
    await wr.write(text);
    await wr.close();
}

async function resolveFlashDirectory(board, label) {
    let destDir = await _handleGet('drive-' + board);
    if (destDir) {
        destDir = await _verifyPermission(destDir);
    }
    if (destDir && !(await _probeCircuitPyHandle(destDir))) {
        log(`[Flash ${label}] Stored drive handle is stale. Re-select the CIRCUITPY drive.`);
        await _handleDel('drive-' + board);
        await _refreshDriveStatus(board);
        destDir = null;
    }
    if (!destDir) {
        log(`[Flash ${label}] Select the CIRCUITPY drive…`);
        destDir = await window.showDirectoryPicker({ id: 'circuitpy-' + board, mode: 'readwrite' });
        destDir = await _verifyPermission(destDir);
        if (!destDir) throw new Error('Write permission was not granted for the selected CIRCUITPY drive');
        if (!(await _probeCircuitPyHandle(destDir))) {
            throw new Error('Selected directory does not look like a CIRCUITPY drive');
        }
        await _handleSet('drive-' + board, destDir);
        await _refreshDriveStatus(board);
    }
    return destDir;
}

function flashSelectedDevice() {
    return flashDevice(_selectedFlashBoard);
}

// ── Main flash function ───────────────────────────────────────────────────────
async function flashDevice(board) {
    if (!window.showDirectoryPicker) {
        log('Flash requires Chrome 86+ with File System Access API.');
        return;
    }

    const settings = firmwareSettings(board);
    try {
        validateFirmwareSettings(settings);
    } catch (e) {
        log(`Flash error: ${e.message}`);
        return;
    }
    const label = `${board === 'nrf' ? 'nRF52840' : 'ESP32-S3'} ${settings.role}`;
    const btns    = document.querySelectorAll('.btn-flash');
    btns.forEach(b => b.classList.add('flashing'));

    try {
        // ── Fetch firmware files ───────────────────────────────────────────────
        log(`[Flash ${label}] Fetching firmware (G${settings.groupId}, N${settings.nodeId})…`);
        const firmware = await Promise.all(STRUCTURED_FW_FILES.map(async ([source, target]) => {
            const resp = await fetch(source);
            if (!resp.ok) throw new Error(`Cannot fetch ${source} (${resp.status})`);
            const text = await resp.text();
            return [target, patchFirmwareSettings(target, text, settings)];
        })).then(orderFirmwareForWrite);

        // ── Resolve CIRCUITPY drive handle ────────────────────────────────────
        const destDir = await resolveFlashDirectory(board, label);

        // ── Write files (3 files to root, no subdirectories) ──────────────────
        for (const [target, text] of firmware) {
            log(`[Flash ${label}] Writing ${target}…`);
            const fh = await destDir.getFileHandle(target, { create: true });
            const wr = await fh.createWritable();
            await wr.write(text);
            await wr.close();
        }

        log(`✓ ${label} N${settings.nodeId} → ${destDir.name}/  (board restarts)`);
    } catch (e) {
        if (e.name !== 'AbortError') log(`Flash error: ${e.message}`);
    } finally {
        btns.forEach(b => b.classList.remove('flashing'));
    }
}

// =============================================
// LOG FILE MANAGEMENT
// =============================================
async function downloadLog(board) {
    let dir = await _handleGet('drive-' + board);
    if (dir) dir = await _verifyPermission(dir);
    if (!dir) { log('Select drive first (flash once to remember it).'); return; }
    try {
        const fh   = await dir.getFileHandle('log.txt');
        const file = await fh.getFile();
        const text = await file.text();
        const a    = document.createElement('a');
        a.href     = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
        a.download = `log_${board}_${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.txt`;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        log(`✓ log.txt downloaded (${text.length} bytes)`);
    } catch (e) { log(`Download log error: ${e.message}`); }
}

// =============================================
// PARROT TESTS
// =============================================
async function parrotTest() {
    if (!writeChar) { log("Not connected"); return; }
    const tag = Date.now() % 10000;
    log(`BLE parrot → sending PARROT:${tag} …`);
    await send(`PARROT:${tag}`);
}

async function loraParrotTest() {
    if (!writeChar) { log("Not connected"); return; }
    const tag = Date.now() % 10000;
    log(`LoRa parrot → sending PARROT:${tag} over mesh …`);
    await send(`SEND_MESH:PARROT:${tag}`);
}

// =============================================
// INITIALIZATION

// ═══════════════════════════════════════════════════════════════════════════════
// CONTROL TAB — rover waypoint planner, compass, grid map
// ═══════════════════════════════════════════════════════════════════════════════

let _ctlBearing = 0;          // compass bearing: 0=N, 90=E, 180=S, 270=W
let _ctlSpeed   = 2.5;        // movement speed in grid cells per second
let _ctlRoverX  = 0, _ctlRoverY = 0;  // world coordinates: +X east, +Y north
let _ctlMapW = 700, _ctlMapH = 560, _ctlMapReady = false;
const CTL_VIEW_W = 700;
const CTL_VIEW_H = 560;
const CTL_GRID = 40;
const CTL_FRESH_ENDPOINT_MS = STALE_TIMEOUT_MS;
let _waypoints  = [];         // pending world targets: {x,y,bearing,distance,speed}
let _ctlTrail   = [];         // completed simulated segments
let _ctlPending = false;
let _ctlAutoChain = false;
let _ctlAckTimer = null;
let _ctlVisualRoverX = 0, _ctlVisualRoverY = 0, _ctlVisualBearing = 0;
let _ctlDrawRaf = 0, _ctlMotion = null;
let _ctlHoverWp = -1, _ctlDragWp = -1, _ctlDragMoved = false;
let _ctlPointerStart = null;
let _ctlLastMove = null;
let _ctlAckWait = null;

function initControlTab() {
    drawCompass();
    const bearingInput = document.getElementById('bearingInput');
    setBearing(bearingInput ? bearingInput.value : _ctlBearing, true);
    const sel = document.getElementById('controlDstSelect');
    if (sel && !sel.dataset.bound) {
        sel.dataset.bound = '1';
        sel.addEventListener('change', _updateControlLock);
    }
    _ctlBindMapEvents();
    updateControlMap();
    updateWaypointList();
    updateControlDstSelect();
    _updateControlLock();
}

function _ctlNodeIsFresh(node) {
    return !!(node && (Date.now() - (node.lastSeen || 0)) <= CTL_FRESH_ENDPOINT_MS);
}

function updateControlDstSelect() {
    const sel = document.getElementById('controlDstSelect');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="0">-- select node --</option>';
    meshNodes.forEach(n => {
        if (n.id === meshMyId) return;
        if ((n._fade || 0) >= 1) return;
        if ((n.role || '').toUpperCase() !== 'E') return;
        if (!n._hasLinks) return;
        if (!_ctlNodeIsFresh(n)) return;
        const opt = document.createElement('option');
        opt.value = String(n.id);
        opt.textContent = 'N' + n.id + (n.role ? ' [' + n.role + ']' : '');
        sel.appendChild(opt);
    });
    if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
    else sel.value = '0';
    _updateControlLock();
}

function _selectedControlEndpoint() {
    const sel = document.getElementById('controlDstSelect');
    const dst = sel?.value || '0';
    if (dst === '0') return null;
    const node = meshNodes.get(parseInt(dst, 10));
    if (!node) return null;
    if ((node.role || '').toUpperCase() !== 'E') return null;
    if ((node._fade || 0) >= 1 || node.gone) return null;
    if (!node._hasLinks) return null;
    if (!_ctlNodeIsFresh(node)) return null;
    return { id: dst, node };
}

function _controlTransportReady() {
    return !!(writeChar || (_serialWriter && _serialMyId));
}

function _controlSendTarget() {
    const endpoint = _selectedControlEndpoint();
    if (!endpoint) return { ok: false, reason: 'select a live endpoint first' };
    if (!_controlTransportReady()) return { ok: false, reason: 'connect BLE or USB before sending' };
    return { ok: true, endpoint };
}

async function _ctlSendEndpointCommand(dst, cmd, mirrorLog = true) {
    try {
        if (writeChar) {
            const ok = await send('SEND_NODE:' + dst + ':' + cmd);
            if (!ok) return false;
        } else if (_serialWriter && _serialMyId) {
            await _serialWriter.write('TO:' + dst + ':' + cmd + '\n');
        } else {
            return false;
        }
        if (mirrorLog) addMeshLog('-> rover [' + dst + ']: "' + cmd + '"', 'tx');
        return true;
    } catch (e) {
        ctlLog('send failed: ' + (e && e.message ? e.message : e), 'ack-err');
        return false;
    }
}

function _ctlConsumeAck(src, payload) {
    if (!_ctlAckWait) return false;
    if (String(src) !== String(_ctlAckWait.dst)) return false;
    if (payload === ('ACK:CTRL:' + _ctlAckWait.cmd)) {
        const wait = _ctlAckWait;
        _ctlAckWait = null;
        if (wait.timer) clearTimeout(wait.timer);
        wait.resolve(payload);
        return true;
    }
    if (payload === ('ERROR:CTRL:' + _ctlAckWait.cmd) || payload === 'ERROR:ENDPOINT:UNSUPPORTED') {
        const wait = _ctlAckWait;
        _ctlAckWait = null;
        if (wait.timer) clearTimeout(wait.timer);
        wait.reject(new Error(payload));
        return true;
    }
    return false;
}

async function _ctlSendEndpointCommandAwaitAck(dst, cmd, timeoutMs = 4500) {
    if (_ctlAckWait) {
        ctlLog('control busy: waiting for previous ACK', 'ack-err');
        return false;
    }
    const sent = await _ctlSendEndpointCommand(dst, cmd);
    if (!sent) return false;
    try {
        await new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                if (_ctlAckWait && _ctlAckWait.timer === timer) _ctlAckWait = null;
                reject(new Error('ACK timeout for ' + cmd));
            }, timeoutMs);
            _ctlAckWait = { dst: String(dst), cmd: String(cmd), resolve, reject, timer };
        });
        return true;
    } catch (e) {
        ctlLog((e && e.message) ? e.message : ('ACK failed for ' + cmd), 'ack-err');
        return false;
    }
}

// ── Compass ──────────────────────────────────────────────────────────────

function drawCompass() {
    const g = document.getElementById('compassTicks');
    if (!g) return;
    g.innerHTML = '';
    for (let d = 0; d < 360; d += 5) {
        const rad = d * Math.PI / 180;
        const inner = (d % 15 === 0) ? 56 : (d % 5 === 0 ? 62 : 66);
        const x1 = 80 + Math.sin(rad) * inner;
        const y1 = 80 - Math.cos(rad) * inner;
        const x2 = 80 + Math.sin(rad) * 70;
        const y2 = 80 - Math.cos(rad) * 70;
        const tick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        tick.setAttribute('x1', x1); tick.setAttribute('y1', y1);
        tick.setAttribute('x2', x2); tick.setAttribute('y2', y2);
        tick.setAttribute('stroke', d % 15 === 0 ? '#656D76' : '#D0D7DE');
        tick.setAttribute('stroke-width', d % 15 === 0 ? '1.2' : '0.5');
        g.appendChild(tick);
    }
    // Compass convention: 0=N, 90=E, 180=S, 270=W
    const labels = [[0,'N'],[90,'E'],[180,'S'],[270,'W']];
    labels.forEach(([d, lbl]) => {
        const rad = d * Math.PI / 180;
        const tx = 80 + Math.sin(rad) * 48;
        const ty = 80 - Math.cos(rad) * 48;
        const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t.setAttribute('x', tx); t.setAttribute('y', ty);
        t.setAttribute('text-anchor', 'middle');
        t.setAttribute('dominant-baseline', 'central');
        t.setAttribute('font-size', '10'); t.setAttribute('font-weight', '700');
        t.setAttribute('fill', '#656D76'); t.setAttribute('font-family', 'JetBrains Mono, monospace');
        t.textContent = lbl;
        g.appendChild(t);
    });
    updateCompassNeedle();
}

function updateCompassNeedle() {
    const needle = document.getElementById('compassNeedle');
    if (!needle) return;
    // Compass convention: 0=N, 90=E, 180=S, 270=W.
    const rad = _ctlBearing * Math.PI / 180;
    needle.setAttribute('x2', 80 + Math.sin(rad) * 62);
    needle.setAttribute('y2', 80 - Math.cos(rad) * 62);
    document.getElementById('bearingInput').value = _ctlBearing.toFixed(1);
}

function setBearing(deg, immediate = true) {
    _ctlBearing = ((parseFloat(deg) || 0) % 360 + 360) % 360;
    if (immediate) _ctlVisualBearing = _ctlBearing;
    updateCompassNeedle();
    updateControlMap();
}

// Compass drag
(function() {
    let dragging = false;
    document.addEventListener('DOMContentLoaded', () => {
        const svg = document.getElementById('compassSvg');
        if (!svg) return;
        svg.addEventListener('mousedown', e => {
            dragging = true; e.preventDefault();
        });
        document.addEventListener('mousemove', e => {
            if (!dragging) return;
            const rect = svg.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            // Screen vector to compass bearing: 0=N, 90=E.
            const rawDeg = Math.atan2(e.clientX - cx, -(e.clientY - cy)) * 180 / Math.PI;
            let deg = ((rawDeg % 360) + 360) % 360;
            deg = Math.round(deg);
            setBearing(deg);
        });
        document.addEventListener('mouseup', () => { dragging = false; });
    });
})();

// ── Speed ────────────────────────────────────────────────────────────────

function updateSpeedLabel() {
    const sl = document.getElementById('speedSlider');
    const sv = document.getElementById('speedValue');
    if (sl && sv) { _ctlSpeed = parseFloat(sl.value); sv.textContent = _ctlSpeed.toFixed(1); }
}
// Expose for HTML onclick
window.updateSpeedLabel = updateSpeedLabel;

// ── Grid Map ─────────────────────────────────────────────────────────────

function _ctlResizeCanvas() {
    const canvas = document.getElementById('controlMap');
    if (!canvas) return null;
    const wrap = canvas.parentElement;
    if (!wrap) return canvas;
    const wrapW = Math.max(320, Math.floor(wrap.clientWidth || canvas.clientWidth || CTL_VIEW_W));
    const wrapH = Math.max(240, Math.floor(wrap.clientHeight || canvas.clientHeight || CTL_VIEW_H));
    const aspect = CTL_VIEW_W / CTL_VIEW_H;
    let cssW = wrapW;
    let cssH = Math.round(cssW / aspect);
    if (cssH > wrapH) {
        cssH = wrapH;
        cssW = Math.round(cssH * aspect);
    }
    const nextW = CTL_VIEW_W;
    const nextH = CTL_VIEW_H;
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const needResize = canvas.width !== Math.round(nextW * dpr) ||
        canvas.height !== Math.round(nextH * dpr) ||
        canvas.style.width !== cssW + 'px' ||
        canvas.style.height !== cssH + 'px';
    if (needResize) {
        _ctlMapReady = true;
        _ctlMapW = nextW; _ctlMapH = nextH;
        canvas.width = Math.round(nextW * dpr);
        canvas.height = Math.round(nextH * dpr);
        canvas.style.width = cssW + 'px';
        canvas.style.height = cssH + 'px';
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return canvas;
}

function _ctlNormBearing(deg) {
    return ((parseFloat(deg) || 0) % 360 + 360) % 360;
}

function _ctlBearingVector(bearing) {
    const rad = _ctlNormBearing(bearing) * Math.PI / 180;
    return { x: Math.sin(rad), y: Math.cos(rad) };
}

function _ctlWorldToScreen(x, y) {
    return { x: _ctlMapW / 2 + x, y: _ctlMapH / 2 - y };
}

function _ctlScreenToWorld(x, y) {
    return { x: x - _ctlMapW / 2, y: _ctlMapH / 2 - y };
}

function _ctlEventToCanvas(e, canvas) {
    const rect = canvas.getBoundingClientRect();
    return {
        x: (e.clientX - rect.left) * (_ctlMapW / Math.max(1, rect.width)),
        y: (e.clientY - rect.top) * (_ctlMapH / Math.max(1, rect.height))
    };
}

function _ctlClampPoint(x, y) {
    const margin = 18;
    const minX = -_ctlMapW / 2 + margin;
    const maxX =  _ctlMapW / 2 - margin;
    const minY = -_ctlMapH / 2 + margin;
    const maxY =  _ctlMapH / 2 - margin;
    return {
        x: Math.max(minX, Math.min(maxX, x)),
        y: Math.max(minY, Math.min(maxY, y))
    };
}

function _ctlWrapCoord(value, minValue, maxValue) {
    const range = maxValue - minValue;
    if (!(range > 0)) return value;
    let wrapped = value;
    while (wrapped < minValue) wrapped += range;
    while (wrapped > maxValue) wrapped -= range;
    return wrapped;
}

function _ctlWrapPoint(x, y) {
    const margin = 18;
    const minX = -_ctlMapW / 2 + margin;
    const maxX =  _ctlMapW / 2 - margin;
    const minY = -_ctlMapH / 2 + margin;
    const maxY =  _ctlMapH / 2 - margin;
    return {
        x: _ctlWrapCoord(x, minX, maxX),
        y: _ctlWrapCoord(y, minY, maxY)
    };
}

function _ctlWrapDelta(from, to, minValue, maxValue) {
    const range = maxValue - minValue;
    if (!(range > 0)) return to - from;
    let delta = to - from;
    if (Math.abs(delta) <= range / 2) return delta;
    return delta > 0 ? delta - range : delta + range;
}

function _ctlSpeedPxPerSec(speed = _ctlSpeed) {
    return Math.max(1, Number(speed || 0) * CTL_GRID);
}

function _ctlPlanOrigin() {
    if (_waypoints.length) {
        const last = _waypoints[_waypoints.length - 1];
        return { x: last.x, y: last.y };
    }
    return { x: _ctlRoverX, y: _ctlRoverY };
}

function _ctlSegmentFrom(ox, oy, tx, ty) {
    const dx = tx - ox;
    const dy = ty - oy;
    const distance = Math.round(Math.sqrt(dx * dx + dy * dy));
    const rawDeg = Math.atan2(dx, dy) * 180 / Math.PI;
    const bearing = Math.round(_ctlNormBearing(rawDeg) * 10) / 10;
    return { bearing, distance };
}

function _ctlRebuildSegments() {
    let ox = _ctlRoverX, oy = _ctlRoverY;
    _waypoints.forEach(wp => {
        const seg = _ctlSegmentFrom(ox, oy, wp.x, wp.y);
        wp.bearing = seg.bearing;
        wp.distance = seg.distance;
        if (!Number.isFinite(wp.speed) || wp.speed <= 0) wp.speed = _ctlSpeed;
        ox = wp.x; oy = wp.y;
    });
}

function _ctlHitWaypoint(screenX, screenY) {
    for (let i = _waypoints.length - 1; i >= 0; i--) {
        const p = _ctlWorldToScreen(_waypoints[i].x, _waypoints[i].y);
        const dx = screenX - p.x;
        const dy = screenY - p.y;
        if ((dx * dx + dy * dy) <= 20 * 20) return i;
    }
    return -1;
}

function _ctlShortestBearingDelta(from, to) {
    return ((((to - from) % 360) + 540) % 360) - 180;
}

function _ctlEaseOutCubic(t) {
    return 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
}

function _ctlStartMotion(x1, y1, x2, y2, delayMs, durationMs) {
    const now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    const margin = 18;
    const minX = -_ctlMapW / 2 + margin;
    const maxX =  _ctlMapW / 2 - margin;
    const minY = -_ctlMapH / 2 + margin;
    const maxY =  _ctlMapH / 2 - margin;
    _ctlMotion = {
        x1, y1, x2, y2,
        dx: _ctlWrapDelta(x1, x2, minX, maxX),
        dy: _ctlWrapDelta(y1, y2, minY, maxY),
        minX, maxX, minY, maxY,
        start: now + Math.max(0, delayMs || 0),
        duration: Math.max(180, durationMs || 180)
    };
    updateControlMap();
}

function _ctlCurrentVisualPose(ts) {
    let targetX = _ctlRoverX;
    let targetY = _ctlRoverY;
    if (_ctlMotion) {
        const t = (ts - _ctlMotion.start) / _ctlMotion.duration;
        if (t >= 1) {
            targetX = _ctlMotion.x2;
            targetY = _ctlMotion.y2;
            _ctlMotion = null;
        } else {
            const p = _ctlEaseOutCubic(Math.max(0, t));
            targetX = _ctlWrapCoord(_ctlMotion.x1 + _ctlMotion.dx * p, _ctlMotion.minX, _ctlMotion.maxX);
            targetY = _ctlWrapCoord(_ctlMotion.y1 + _ctlMotion.dy * p, _ctlMotion.minY, _ctlMotion.maxY);
        }
        _ctlVisualRoverX = targetX;
        _ctlVisualRoverY = targetY;
    } else {
        _ctlVisualRoverX += (_ctlRoverX - _ctlVisualRoverX) * 0.22;
        _ctlVisualRoverY += (_ctlRoverY - _ctlVisualRoverY) * 0.22;
        if (Math.abs(_ctlRoverX - _ctlVisualRoverX) < 0.05) _ctlVisualRoverX = _ctlRoverX;
        if (Math.abs(_ctlRoverY - _ctlVisualRoverY) < 0.05) _ctlVisualRoverY = _ctlRoverY;
    }
    const bd = _ctlShortestBearingDelta(_ctlVisualBearing, _ctlBearing);
    _ctlVisualBearing = _ctlNormBearing(_ctlVisualBearing + bd * 0.28);
    if (Math.abs(bd) < 0.2) _ctlVisualBearing = _ctlBearing;
    return { x: _ctlVisualRoverX, y: _ctlVisualRoverY, bearing: _ctlVisualBearing };
}

function _ctlDrawGrid(ctx, w, h) {
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, w, h);
    const grid = CTL_GRID;
    const minX = -w / 2, maxX = w / 2;
    const minY = -h / 2, maxY = h / 2;
    for (let gx = Math.ceil(minX / grid) * grid; gx <= maxX; gx += grid) {
        const p = _ctlWorldToScreen(gx, 0);
        const major = Math.abs(gx % 200) < 0.001;
        ctx.strokeStyle = major ? '#8C959F' : '#D0D7DE';
        ctx.lineWidth = major ? 1.1 : 0.7;
        ctx.beginPath(); ctx.moveTo(p.x + 0.5, 0); ctx.lineTo(p.x + 0.5, h); ctx.stroke();
    }
    for (let gy = Math.ceil(minY / grid) * grid; gy <= maxY; gy += grid) {
        const p = _ctlWorldToScreen(0, gy);
        const major = Math.abs(gy % 200) < 0.001;
        ctx.strokeStyle = major ? '#8C959F' : '#D0D7DE';
        ctx.lineWidth = major ? 1.1 : 0.7;
        ctx.beginPath(); ctx.moveTo(0, p.y + 0.5); ctx.lineTo(w, p.y + 0.5); ctx.stroke();
    }
    const origin = _ctlWorldToScreen(0, 0);
    ctx.strokeStyle = 'rgba(31, 35, 40, 0.55)';
    ctx.lineWidth = 1.3;
    ctx.beginPath(); ctx.moveTo(origin.x, 0); ctx.lineTo(origin.x, h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, origin.y); ctx.lineTo(w, origin.y); ctx.stroke();
}

function _ctlDrawSegment(ctx, x1, y1, x2, y2, color, dashed) {
    const p1 = _ctlWorldToScreen(x1, y1);
    const p2 = _ctlWorldToScreen(x2, y2);
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    if (dashed) ctx.setLineDash([6, 5]);
    ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
    ctx.restore();
}

function _ctlDrawRover(ctx, pose) {
    const p = _ctlWorldToScreen(pose.x, pose.y);
    // Canvas body points north in local coordinates, then rotates clockwise
    // by the same compass bearing used everywhere else: 0=N, 90=E.
    const headingRad = _ctlNormBearing(pose.bearing) * Math.PI / 180;
    const v = _ctlBearingVector(pose.bearing);
    ctx.save();
    ctx.strokeStyle = 'rgba(13, 71, 161, 0.22)';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x + v.x * 62, p.y - v.y * 62);
    ctx.stroke();

    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(headingRad);

    // Tires
    ctx.shadowColor = 'rgba(31, 35, 40, 0.16)';
    ctx.shadowBlur = 8;
    ctx.fillStyle = '#7D8590';
    ctx.strokeStyle = '#30363D';
    ctx.lineWidth = 1.4;
    _ctlRoundRect(ctx, -21, -16, 6, 12, 2);
    ctx.fill();
    ctx.stroke();
    _ctlRoundRect(ctx, 15, -16, 6, 12, 2);
    ctx.fill();
    ctx.stroke();
    _ctlRoundRect(ctx, -21, 4, 6, 12, 2);
    ctx.fill();
    ctx.stroke();
    _ctlRoundRect(ctx, 15, 4, 6, 12, 2);
    ctx.fill();
    ctx.stroke();

    // Main chassis
    ctx.fillStyle = '#0B4F8A';
    ctx.strokeStyle = '#1F2328';
    ctx.lineWidth = 2;
    _ctlRoundRect(ctx, -14, -22, 28, 44, 6);
    ctx.fill();
    ctx.stroke();

    ctx.shadowBlur = 0;

    // Nose / front wedge
    ctx.fillStyle = '#0F6CBD';
    ctx.beginPath();
    ctx.moveTo(0, -31);
    ctx.lineTo(-11, -17);
    ctx.lineTo(11, -17);
    ctx.closePath();
    ctx.fill();

    // Roof / cockpit
    ctx.fillStyle = '#1E6FB9';
    _ctlRoundRect(ctx, -9, -9, 18, 18, 4);
    ctx.fill();

    // Windshield and rear panel
    ctx.fillStyle = '#B6D6EE';
    _ctlRoundRect(ctx, -7, -13, 14, 8, 2);
    ctx.fill();
    ctx.fillStyle = '#73A9D8';
    _ctlRoundRect(ctx, -7, 5, 14, 5, 2);
    ctx.fill();

    // Panel lines / texture
    ctx.strokeStyle = 'rgba(230, 237, 243, 0.32)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(-8, -1);
    ctx.lineTo(8, -1);
    ctx.moveTo(-8, 13);
    ctx.lineTo(8, 13);
    ctx.stroke();

    // Front sensors / lights
    ctx.fillStyle = '#F2CC60';
    ctx.beginPath();
    ctx.arc(-5.5, -19, 1.7, 0, Math.PI * 2);
    ctx.arc(5.5, -19, 1.7, 0, Math.PI * 2);
    ctx.fill();

    // Rear module
    ctx.beginPath();
    ctx.fillStyle = '#1F2328';
    _ctlRoundRect(ctx, -4, 17, 8, 6, 2);
    ctx.fill();

    ctx.restore();

    ctx.fillStyle = '#1F2328';
    ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
}

function _ctlRoundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
}

function updateControlMap() {
    if (_ctlDrawRaf) return;
    const raf = window.requestAnimationFrame || (cb => setTimeout(() => cb(Date.now()), 16));
    _ctlDrawRaf = raf(_ctlRenderControlMap);
}

function _ctlRenderControlMap(ts) {
    _ctlDrawRaf = 0;
    const canvas = _ctlResizeCanvas();
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, _ctlMapW, _ctlMapH);
    _ctlRebuildSegments();
    _ctlDrawGrid(ctx, _ctlMapW, _ctlMapH);

    _ctlTrail.slice(-20).forEach(seg => _ctlDrawSegment(ctx, seg.x1, seg.y1, seg.x2, seg.y2, '#8C959F', true));

    let ox = _ctlRoverX, oy = _ctlRoverY;
    _waypoints.forEach((wp, i) => {
        _ctlDrawSegment(ctx, ox, oy, wp.x, wp.y, i === 0 && _ctlPending ? '#0969DA' : '#D29922', false);
        const mid = _ctlWorldToScreen((ox + wp.x) / 2, (oy + wp.y) / 2);
        ctx.fillStyle = 'rgba(255,255,255,0.88)';
        ctx.fillRect(mid.x - 30, mid.y - 9, 60, 18);
        ctx.fillStyle = '#57606A';
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(wp.distance + 'px', mid.x, mid.y);
        ox = wp.x; oy = wp.y;
    });

    _waypoints.forEach((wp, i) => {
        const p = _ctlWorldToScreen(wp.x, wp.y);
        const active = i === 0 && _ctlPending;
        const hovered = i === _ctlHoverWp;
        const dragged = i === _ctlDragWp;
        const r = dragged ? 13 : (hovered ? 11 : 8);
        ctx.save();
        ctx.shadowColor = dragged ? 'rgba(9,105,218,0.28)' : 'rgba(31,35,40,0.12)';
        ctx.shadowBlur = dragged || hovered ? 12 : 4;
        ctx.fillStyle = active ? '#0969DA' : (dragged || hovered ? '#BF8700' : '#D29922');
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = dragged ? 3 : 2;
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        ctx.fillStyle = '#FFFFFF';
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(i + 1), p.x, p.y + 0.5);
        ctx.restore();
    });

    const pose = _ctlCurrentVisualPose(ts || Date.now());
    _ctlDrawRover(ctx, pose);

    const stillMoving = _ctlMotion ||
        Math.abs(_ctlRoverX - _ctlVisualRoverX) > 0.05 ||
        Math.abs(_ctlRoverY - _ctlVisualRoverY) > 0.05 ||
        Math.abs(_ctlShortestBearingDelta(_ctlVisualBearing, _ctlBearing)) > 0.2 ||
        _ctlDragWp >= 0;
    if (stillMoving) updateControlMap();
}

function _ctlBindMapEvents() {
    const map = document.getElementById('controlMap');
    if (!map || map.dataset.bound === '1') return;
    map.dataset.bound = '1';

    map.addEventListener('pointerdown', e => {
        const p = _ctlEventToCanvas(e, map);
        const hit = _ctlHitWaypoint(p.x, p.y);
        _ctlPointerStart = { x: p.x, y: p.y };
        _ctlDragMoved = false;
        if (hit >= 0 && !_ctlPending) {
            _ctlDragWp = hit;
            _ctlHoverWp = hit;
            map.setPointerCapture(e.pointerId);
            map.classList.add('dragging');
            e.preventDefault();
            updateControlMap();
        }
    });

    map.addEventListener('pointermove', e => {
        const p = _ctlEventToCanvas(e, map);
        if (_ctlDragWp >= 0) {
            const start = _ctlPointerStart || p;
            if (Math.hypot(p.x - start.x, p.y - start.y) > 3) _ctlDragMoved = true;
            const world = _ctlScreenToWorld(p.x, p.y);
            const point = _ctlClampPoint(world.x, world.y);
            const wp = _waypoints[_ctlDragWp];
            if (wp) {
                wp.x = point.x;
                wp.y = point.y;
                _ctlRebuildSegments();
                updateControlMap();
                updateWaypointList();
            }
            e.preventDefault();
            return;
        }
        const hit = _ctlHitWaypoint(p.x, p.y);
        if (hit !== _ctlHoverWp) {
            _ctlHoverWp = hit;
            map.classList.toggle('hover-waypoint', hit >= 0 && !_ctlPending);
            updateControlMap();
        }
    });

    function endPointer(e) {
        const p = _ctlEventToCanvas(e, map);
        const wasDragging = _ctlDragWp >= 0;
        if (wasDragging) {
            _ctlDragWp = -1;
            _ctlHoverWp = _ctlHitWaypoint(p.x, p.y);
            map.classList.remove('dragging');
            updateControlMap();
            return;
        }
        if (!_ctlPending && _ctlPointerStart) {
            const moved = Math.hypot(p.x - _ctlPointerStart.x, p.y - _ctlPointerStart.y);
            if (moved < 4 && !_ctlDragMoved) addWaypointAt(p.x, p.y);
        }
        _ctlPointerStart = null;
    }

    map.addEventListener('pointerup', endPointer);
    map.addEventListener('pointercancel', e => {
        _ctlDragWp = -1;
        _ctlPointerStart = null;
        map.classList.remove('dragging');
        updateControlMap();
    });
    map.addEventListener('pointerleave', () => {
        if (_ctlDragWp >= 0) return;
        if (_ctlHoverWp !== -1) {
            _ctlHoverWp = -1;
            map.classList.remove('hover-waypoint');
            updateControlMap();
        }
    });
}

// ── Waypoints ────────────────────────────────────────────────────────────

function addWaypoint(bearing, distance, speed) {
    const origin = _ctlPlanOrigin();
    const b = bearing == null ? _ctlBearing : _ctlNormBearing(bearing);
    const dist = Math.max(10, parseInt(distance == null ? 120 : distance, 10) || 120);
    const v = _ctlBearingVector(b);
    const point = _ctlClampPoint(origin.x + v.x * dist, origin.y + v.y * dist);
    _waypoints.push({ x: point.x, y: point.y, bearing: b, distance: dist, speed: speed || _ctlSpeed });
    _ctlRebuildSegments();
    updateControlMap();
    updateWaypointList();
}

function addWaypointAt(x, y) {
    const world = _ctlScreenToWorld(x, y);
    const point = _ctlClampPoint(world.x, world.y);
    const origin = _ctlPlanOrigin();
    const seg = _ctlSegmentFrom(origin.x, origin.y, point.x, point.y);
    if (seg.distance < 10) return;
    _waypoints.push({ x: point.x, y: point.y, bearing: seg.bearing, distance: seg.distance, speed: _ctlSpeed });
    updateControlMap();
    updateWaypointList();
}

function removeWaypoint(idx) {
    _waypoints.splice(idx, 1);
    if (_ctlHoverWp === idx) _ctlHoverWp = -1;
    else if (_ctlHoverWp > idx) _ctlHoverWp -= 1;
    if (_ctlDragWp === idx) _ctlDragWp = -1;
    else if (_ctlDragWp > idx) _ctlDragWp -= 1;
    _ctlRebuildSegments();
    updateControlMap();
    updateWaypointList();
}

function clearWaypoints() {
    _waypoints = [];
    _ctlAutoChain = false;
    if (_ctlAckTimer) { clearTimeout(_ctlAckTimer); _ctlAckTimer = null; }
    if (_ctlAckWait && _ctlAckWait.timer) { clearTimeout(_ctlAckWait.timer); _ctlAckWait = null; }
    _ctlPending = false;
    _ctlLastMove = null;
    _ctlHoverWp = -1;
    _ctlDragWp = -1;
    updateControlMap();
    updateWaypointList();
}

function resetControlSim() {
    _waypoints = [];
    _ctlTrail = [];
    _ctlAutoChain = false;
    _ctlPending = false;
    if (_ctlAckTimer) { clearTimeout(_ctlAckTimer); _ctlAckTimer = null; }
    if (_ctlAckWait && _ctlAckWait.timer) { clearTimeout(_ctlAckWait.timer); _ctlAckWait = null; }
    _ctlRoverX = 0;
    _ctlRoverY = 0;
    _ctlVisualRoverX = 0;
    _ctlVisualRoverY = 0;
    _ctlVisualBearing = _ctlBearing;
    _ctlMotion = null;
    _ctlLastMove = null;
    _ctlHoverWp = -1;
    _ctlDragWp = -1;
    updateControlMap();
    updateWaypointList();
    ctlLog('simulation reset', 'ack-ok');
}

function toggleWaypoints() {
    const list = document.getElementById('waypointList');
    const btn = document.getElementById('btnToggleWaypoints');
    if (!list || !btn) return;
    const open = list.style.display !== 'none';
    list.style.display = open ? 'none' : '';
    btn.textContent = open ? 'waypoints ▸' : 'waypoints ▾';
}

function updateWaypointList() {
    const list = document.getElementById('waypointList');
    if (!list) return;
    list.innerHTML = '';
    if (!_waypoints.length) {
        const empty = document.createElement('div');
        empty.className = 'waypoint-row';
        empty.innerHTML = '<span class="wp-info">no pending waypoints</span>';
        list.appendChild(empty);
        return;
    }
    _waypoints.forEach((wp, i) => {
        const row = document.createElement('div');
        row.className = 'waypoint-row' +
            (i === 0 && _ctlPending ? ' pending' : '') +
            (i === _ctlHoverWp ? ' hover' : '') +
            (i === _ctlDragWp ? ' dragging' : '');
        row.innerHTML = '<span class="wp-idx">' + (i + 1) + '</span>' +
            '<span class="wp-info">bearing <span>' + wp.bearing.toFixed(1) + '</span> deg &nbsp;dist <span>' + wp.distance + '</span>px &nbsp;spd <span>' + wp.speed.toFixed(1) + '</span><br><span class="wp-coord">E ' + Math.round(wp.x) + ' / N ' + Math.round(wp.y) + '</span></span>' +
            '<button onclick="removeWaypoint(' + i + ')">&times;</button>';
        list.appendChild(row);
    });
}

// ── Send logic ───────────────────────────────────────────────────────────

function _ctlApplyRoverCommand(cmd) {
    const text = String(cmd || '').trim();
    if (!text) return;
    if (text === 'L') {
        setBearing(_ctlBearing - 15);
    } else if (text === 'R') {
        setBearing(_ctlBearing + 15);
    } else if (text.startsWith('H:') || text.startsWith('HEADING:')) {
        const value = parseFloat(text.split(':')[1]);
        if (Number.isFinite(value)) setBearing(value);
    } else if (text.startsWith('V:') || text.startsWith('SPEED:')) {
        const value = parseFloat(text.split(':')[1]);
        if (Number.isFinite(value) && value > 0) {
            _ctlSpeed = value;
            const slider = document.getElementById('speedSlider');
            const label = document.getElementById('speedValue');
            if (slider) slider.value = String(value);
            if (label) label.textContent = value.toFixed(1);
        }
    }
}

async function sendRoverCmd(cmd) {
    const target = _controlSendTarget();
    if (!target.ok) {
        ctlLog(target.reason, 'ack-err');
        _updateControlLock();
        return false;
    }
    const dst = target.endpoint.id;
    ctlLog('sent: ' + cmd + ' (awaiting ACK)', 'ack-pending');
    const acked = await _ctlSendEndpointCommandAwaitAck(dst, cmd);
    if (!acked) {
        _updateControlLock();
        return false;
    }
    _ctlApplyRoverCommand(cmd);
    ctlLog('ack: ' + cmd, 'ack-ok');
    return true;
}

function _isControlLocked() {
    return !_controlSendTarget().ok;
}

function _updateControlLock() {
    const wrap = document.querySelector('.control-map-wrap');
    const overlay = document.getElementById('mapOverlay');
    const label = document.getElementById('controlEndpointLabel');
    const endpoint = _selectedControlEndpoint();
    const dst = endpoint?.id || '0';
    const target = _controlSendTarget();
    const locked = !target.ok;
    if (wrap) wrap.classList.toggle('control-locked', locked);
    document.querySelectorAll('.rover-send').forEach(btn => { btn.disabled = locked; });
    if (overlay) overlay.querySelector('span').textContent = locked ? target.reason : 'target N' + dst;
    if (label) label.textContent = locked ? target.reason : 'target N' + dst;
}

async function sendCurrentBearing() {
    if (!_controlSendTarget().ok) {
        await sendRoverCmd('H:' + _ctlBearing.toFixed(1));
        return;
    }
    const input = document.getElementById('bearingInput');
    if (input) setBearing(input.value);
    await sendRoverCmd('H:' + _ctlBearing.toFixed(1));
}

async function sendCurrentSpeed() {
    await sendRoverCmd('V:' + _ctlSpeed.toFixed(1));
}

async function sendFwd() {
    const amt = parseInt(document.getElementById('fwdAmount')?.value || '500');
    const unit = document.getElementById('fwdUnit')?.value || 'time';
    let px = amt;
    if (unit === 'dist') {
        const ms = Math.round((amt / _ctlSpeedPxPerSec()) * 1000);
        if (!await sendRoverCmd('F:' + ms)) return;
    } else {
        if (!await sendRoverCmd('F:' + amt)) return;
        px = Math.round(_ctlSpeedPxPerSec() * (amt / 1000));
    }
    _ctlMoveRover(px);
}

async function sendBack() {
    const amt = parseInt(document.getElementById('backAmount')?.value || '300');
    const unit = document.getElementById('backUnit')?.value || 'time';
    let px = amt;
    if (unit === 'dist') {
        const ms = Math.round((amt / _ctlSpeedPxPerSec()) * 1000);
        if (!await sendRoverCmd('B:' + ms)) return;
    } else {
        if (!await sendRoverCmd('B:' + amt)) return;
        px = Math.round(_ctlSpeedPxPerSec() * (amt / 1000));
    }
    _ctlMoveRover(-px);
}

function _ctlMoveRover(px) {
    if (!Number.isFinite(px) || px === 0) return;
    const v = _ctlBearingVector(_ctlBearing);
    const x1 = _ctlRoverX, y1 = _ctlRoverY;
    _ctlLastMove = {
        at: Date.now(),
        x: x1,
        y: y1,
        visualX: _ctlVisualRoverX,
        visualY: _ctlVisualRoverY,
        trailLen: _ctlTrail.length
    };
    const point = _ctlWrapPoint(_ctlRoverX + v.x * px, _ctlRoverY + v.y * px);
    const durationMs = Math.max(180, Math.min(1600, Math.round(Math.abs(px) / _ctlSpeedPxPerSec() * 1000)));
    _ctlStartMotion(x1, y1, point.x, point.y, 0, durationMs);
    _ctlRoverX = point.x; _ctlRoverY = point.y;
    if (Math.abs(point.x - x1) < (_ctlMapW / 2) && Math.abs(point.y - y1) < (_ctlMapH / 2)) {
        _ctlTrail.push({ x1, y1, x2: point.x, y2: point.y });
    }
    if (_ctlTrail.length > 80) _ctlTrail.shift();
    _ctlRebuildSegments();
    updateControlMap();
    updateWaypointList();
}

async function sendNextWaypoint() {
    const target = _controlSendTarget();
    if (!target.ok) { ctlLog(target.reason, 'ack-err'); _updateControlLock(); return; }
    if (_ctlPending) { ctlLog('waypoint already running', 'ack-pending'); return; }
    const idx = _waypoints.findIndex(w => !w.sent);
    if (idx < 0) { ctlLog('all waypoints done', 'ack-ok'); return; }
    await _executeWaypoint(idx);
}

async function sendAllWaypoints() {
    const target = _controlSendTarget();
    if (!target.ok) { ctlLog(target.reason, 'ack-err'); _updateControlLock(); return; }
    if (_ctlPending) { ctlLog('waypoint already running', 'ack-pending'); return; }
    if (!_waypoints.length) { _ctlAutoChain = false; ctlLog('all waypoints done', 'ack-ok'); return; }
    _ctlAutoChain = true;
    await _executeWaypoint(0);
}

async function _executeWaypoint(idx) {
    if (idx < 0 || idx >= _waypoints.length) {
        _ctlPending = false;
        _ctlAutoChain = false;
        return;
    }
    const wp = _waypoints[idx];
    const target = _controlSendTarget();
    if (!target.ok) {
        _ctlPending = false;
        _ctlAutoChain = false;
        ctlLog(target.reason, 'ack-err');
        _updateControlLock();
        return;
    }
    const dst = target.endpoint.id;
    const bearing = wp.bearing;
    const distance = wp.distance;
    const speed = wp.speed || _ctlSpeed;
    const pxPerSec = _ctlSpeedPxPerSec(speed);
    const durationMs = Math.round((distance / pxPerSec) * 1000);
    const cmds = [
        'H:' + bearing.toFixed(1),
        'V:' + speed.toFixed(1),
    ];
    if (durationMs > 0) cmds.push('F:' + durationMs);
    _ctlPending = true;
    updateControlMap();
    updateWaypointList();
    ctlLog('wp ' + (idx + 1) + ': bearing=' + bearing + ' dist=' + distance + 'px -> ' + cmds.join(', '), 'ack-pending');
    await _sendCmdChain(dst, cmds, 0, () => {
        const x1 = _ctlRoverX, y1 = _ctlRoverY;
        _ctlTrail.push({ x1, y1, x2: wp.x, y2: wp.y });
        if (_ctlTrail.length > 80) _ctlTrail.shift();
        _ctlRoverX = wp.x;
        _ctlRoverY = wp.y;
        _waypoints.splice(idx, 1);
        _ctlRebuildSegments();
        _ctlPending = false;
        _ctlLastMove = null;
        updateControlMap();
        updateWaypointList();
        ctlLog('wp ' + (idx + 1) + ' done', 'ack-ok');
        if (_waypoints.length && _ctlAutoChain) {
            setTimeout(() => { void _executeWaypoint(0); }, 200);
        } else {
            _ctlAutoChain = false;
        }
    });
}

async function _sendCmdChain(dst, cmds, i, done) {
    if (i >= cmds.length) { done(); return; }
    const cmd = cmds[i];
    ctlLog('  ' + cmd + ' (awaiting ACK)', 'ack-pending');
    const acked = dst !== '0' ? await _ctlSendEndpointCommandAwaitAck(dst, cmd) : false;
    if (!acked) {
        _ctlPending = false;
        _ctlAutoChain = false;
        ctlLog('command chain aborted at ' + cmd, 'ack-err');
        updateControlMap();
        updateWaypointList();
        return;
    }
    _ctlApplyRoverCommand(cmd);
    if (cmd.startsWith('F:')) {
        const movingWp = _waypoints[0];
        if (movingWp) _ctlStartMotion(_ctlRoverX, _ctlRoverY, movingWp.x, movingWp.y, 0, parseInt(cmd.slice(2)) || 180);
    }
    // Estimate time for this command + chain
    let waitMs = 300; // default: turn/speed set
    if (cmd.startsWith('F:')) waitMs = parseInt(cmd.slice(2)) + 100;
    if (cmd.startsWith('B:')) waitMs = parseInt(cmd.slice(2)) + 100;
    ctlLog('  ack ' + cmd + ' (wait ' + waitMs + 'ms)', 'ack-ok');
    _ctlAckTimer = setTimeout(() => { void _sendCmdChain(dst, cmds, i + 1, done); }, waitMs);
}

function ctlLog(msg, cls) {
    const log = document.getElementById('ackLog');
    if (!log) return;
    const div = document.createElement('div');
    div.className = cls || '';
    div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    while (log.children.length > 40) log.removeChild(log.firstChild);
}

// Expose to HTML onclick
window.setBearing = setBearing;
window.addWaypoint = addWaypoint;
window.resetControlSim = resetControlSim;
window.removeWaypoint = removeWaypoint;
window.clearWaypoints = clearWaypoints;
window.sendRoverCmd = sendRoverCmd;
window.sendCurrentBearing = sendCurrentBearing;
window.sendCurrentSpeed = sendCurrentSpeed;
window.sendFwd = sendFwd;
window.sendBack = sendBack;
window.sendNextWaypoint = sendNextWaypoint;
window.sendAllWaypoints = sendAllWaypoints;
window.toggleWaypoints = toggleWaypoints;

// Hook into existing updateMeshDstSelect to also refresh control dest
const _origUpdateMeshDstSelect = updateMeshDstSelect;
updateMeshDstSelect = function() {
    _origUpdateMeshDstSelect();
    updateControlDstSelect();
};

document.addEventListener('DOMContentLoaded', () => {
    meshInit();
    renderRoleButtons();
    updateBoardRoleHints();
    updateFlashButtonLabel();
    _refreshDriveStatus('nrf');
    _refreshDriveStatus('esp32');
    ensureMonitorPlaceholder(
        document.getElementById('serialRawLog'),
        '// raw USB serial output appears here after you connect a board'
    );

    window.addEventListener('resize', () => {
        meshResize({ recenter: true, heat: false });
    });

    if (window.ResizeObserver) {
        const meshViz = document.getElementById('meshViz');
        if (meshViz) {
            const observer = new ResizeObserver(() => meshResize({ recenter: false, heat: false }));
            observer.observe(meshViz);
        }
    }

    // Reconnect when tab becomes visible again (browser may have dropped BLE in background)
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && device && !device.gatt.connected && !_userDisconnected && !_reconnectTimer) {
            log('tab visible — reconnecting…');
            _attemptReconnect();
        }
    });

    // ── Resize handles ──────────────────────────────────────────────────────
    function initResizeHandle(handleId, axis, getSize, setSize, onResize) {
        const handle = document.getElementById(handleId);
        if (!handle) return;

        let dragging = false;
        let startPos = 0;
        let startSize = 0;

        handle.addEventListener('mousedown', (e) => {
            dragging = true;
            startPos = axis === 'x' ? e.clientX : e.clientY;
            startSize = getSize();
            handle.classList.add('dragging');
            document.body.classList.add(axis === 'x' ? 'resizing-x' : 'resizing-y');
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            const delta = (axis === 'x' ? e.clientX : e.clientY) - startPos;
            // X: dragging right = larger sidebar. Y: dragging down = smaller log (delta positive → log shrinks)
            const newSize = axis === 'x'
                ? startSize + delta
                : startSize - delta;
            setSize(newSize);
            if (onResize) onResize();
        });

        document.addEventListener('mouseup', () => {
            if (!dragging) return;
            dragging = false;
            handle.classList.remove('dragging');
            document.body.classList.remove('resizing-x', 'resizing-y');
            // Store final size
            try {
                localStorage.setItem('mesh-' + handleId, getSize());
            } catch (_) { /* ignore */ }
        });
    }

    const sidebar = document.querySelector('.glass-sidebar');
    const logPanel = document.getElementById('meshLog');

    initResizeHandle('sidebarResizeHandle', 'x',
        () => sidebar ? sidebar.offsetWidth : 260,
        (w) => {
            if (!sidebar) return;
            const clamped = Math.max(200, Math.min(500, w));
            sidebar.style.width = clamped + 'px';
        },
        () => { if (meshSim) meshResize({ recenter: false, heat: false }); }
    );

    initResizeHandle('logResizeHandle', 'y',
        () => logPanel ? logPanel.offsetHeight : 140,
        (h) => {
            if (!logPanel) return;
            const maxH = window.innerHeight * 0.55;
            const clamped = Math.max(80, Math.min(maxH, h));
            logPanel.style.height = clamped + 'px';
            logPanel.style.maxHeight = 'none';
        },
        () => { if (meshSim) meshResize({ recenter: false, heat: false }); }
    );

    // Restore saved sizes
    try {
        const savedSidebar = localStorage.getItem('mesh-sidebarResizeHandle');
        if (savedSidebar && sidebar) {
            const w = Math.max(200, Math.min(500, parseInt(savedSidebar, 10)));
            sidebar.style.width = w + 'px';
        }
        const savedLog = localStorage.getItem('mesh-logResizeHandle');
        if (savedLog && logPanel) {
            const h = Math.max(80, Math.min(window.innerHeight * 0.55, parseInt(savedLog, 10)));
            logPanel.style.height = h + 'px';
            logPanel.style.maxHeight = 'none';
        }
    } catch (_) { /* ignore */ }

    // ── Control tab initialisation ────────────────────────────────────────
    if (typeof initControlTab === 'function') initControlTab();
    const initialTab = (window.location.hash || '').replace('#', '');
    if (['home', 'mesh', 'serial', 'control'].includes(initialTab)) setTab(initialTab);
});
