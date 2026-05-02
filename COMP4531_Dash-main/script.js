// =============================================
// GLOBAL VARIABLES
// =============================================
let currentTab = 'home';
let device, server, service, writeChar, notifyChar;

// LoRa metrics & graphing
let loraCsvRows  = [["Timestamp", "Direction", "Message", "LoRa_SNR", "LoRa_RSSI", "Hops"]];
let loraGraphData = [];

// =============================================
// UI & LOGGING
// =============================================
function log(msg) {
    const isErr = msg.startsWith('Error') || msg.toLowerCase().includes('error') || msg.startsWith('Flash error');
    if (isErr) console.error('[mesh]', msg);
    else       console.log('[mesh]', msg);
    // Update status text for connection events
    const status = document.getElementById('connStatus');
    if (status && (msg.includes('Connected') || msg.includes('disconnected') || msg.includes('Error') || msg.startsWith('Flash'))) {
        status.innerText = msg;
    }
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
    if (id === 'sim')  setTimeout(() => { if (!simState) simGenerate(); else _simDraw(null); }, 50);
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
        document.getElementById('loraBadge').innerText = `${freq} MHz`;

        _gattUUIDs = {
            svc:    `${base}40-4150-b42d-22f30b0a0499`,
            write:  `${base}41-4150-b42d-22f30b0a0499`,
            notify: `${base}42-4150-b42d-22f30b0a0499`,
        };
        _userDisconnected = false;
        _reconnectAttempts = 0;

        log(`Connecting Group ${gid}…`);

        device = await navigator.bluetooth.requestDevice({
            filters:          [
                { services: [_gattUUIDs.svc] },
                { name: `MESH_G${gid}` },
            ],
            optionalServices: [_gattUUIDs.svc],
        });
        device.addEventListener('gattserverdisconnected', onDisconnect);

        await _setupGatt();
        _setConnectedUI('ok');
        _startKeepalive();

        // Initialise mesh topology
        meshMyId = gid;
        meshNodes.clear();
        meshLinks.clear();
        meshParticles.length = 0;
        meshMsgCount = 0;
        document.getElementById('meshMsgCount').innerText  = '0';
        document.getElementById('meshNodeCount').innerText = '0';
        document.getElementById('meshMyNodeId').innerText  = `N${gid}`;

        const svg = document.getElementById('meshSvg');
        const w = svg ? svg.clientWidth  : 600;
        const h = svg ? svg.clientHeight : 400;
        meshNodes.set(meshMyId, {
            id: meshMyId, hops: 0, rssi: 0, snr: 0, msgCount: 0,
            x: w / 2, y: h / 2,
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
    if (!writeChar) return;
    const data = new TextEncoder().encode(cmd);
    try {
        if (writeChar.properties.writeWithoutResponse) await writeChar.writeValueWithoutResponse(data);
        else await writeChar.writeValue(data);
    } catch (e) { log('Tx Error: ' + e); }
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

    cx.font = "10px 'JetBrains Mono', monospace";
    cx.textAlign = 'right';
    cx.textBaseline = 'middle';
    cx.fillStyle = '#8C959F';

    [-130, -100, -70, -40, -10].forEach(tick => {
        const yPos = getY(tick);
        cx.fillText(tick, padX - 8, yPos);
        cx.beginPath(); cx.strokeStyle = 'rgba(0,0,0,0.05)';
        cx.moveTo(padX, yPos); cx.lineTo(w - 10, yPos); cx.stroke();
    });

    cx.strokeStyle = 'rgba(0,0,0,0.15)';
    cx.beginPath(); cx.moveTo(padX, padY); cx.lineTo(padX, h - padY); cx.lineTo(w - 10, h - padY); cx.stroke();

    cx.strokeStyle = '#0969DA'; cx.lineWidth = 2; cx.beginPath();
    loraGraphData.forEach((pt, i) => {
        if (i === 0) cx.moveTo(getX(pt.dist), getY(pt.lora));
        else cx.lineTo(getX(pt.dist), getY(pt.lora));
    });
    cx.stroke();

    cx.font = "10px 'JetBrains Mono', monospace";
    cx.textAlign = 'center';
    loraGraphData.forEach(pt => {
        cx.fillStyle = '#0969DA';
        cx.beginPath(); cx.arc(getX(pt.dist), getY(pt.lora), 4, 0, Math.PI * 2); cx.fill();
        cx.fillStyle = '#8C959F';
        cx.fillText(pt.dist + 'm', getX(pt.dist), h - 5);
    });
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
    if (msg.startsWith("MESH_ERR:"))    { log("node_error: " + msg.substring(9)); return; }

    log("rx: " + msg);
}

function handleMeshRoute(data) {
    // dest|next_hop|hops
    const [dest, nh, hops] = data.split('|');
    const destId  = parseInt(dest);
    const nhId    = parseInt(nh);
    const hopsNum = parseInt(hops);
    addMeshLog(`route N${dest}: next=N${nh} hops=${hops}`, 'rt');

    const svgEl = document.getElementById('meshSvg');
    const cx = svgEl ? (svgEl.clientWidth  || 600) / 2 : 300;
    const cy = svgEl ? (svgEl.clientHeight || 400) / 2 : 200;

    // Ensure dest node exists at correct hop distance
    if (!meshNodes.has(destId)) {
        const angle = Math.random() * Math.PI * 2;
        const dist  = 100 + hopsNum * 80 + Math.random() * 30;
        meshNodes.set(destId, {
            id: destId, hops: hopsNum, rssi: 0, snr: 0, msgCount: 0,
            x: cx + Math.cos(angle) * dist, y: cy + Math.sin(angle) * dist,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
    } else {
        meshNodes.get(destId).hops = hopsNum;
    }

    // Ensure relay (nh) node exists if not gateway
    if (nhId !== meshMyId) {
        if (!meshNodes.has(nhId)) {
            const angle = Math.random() * Math.PI * 2;
            const dist  = 100 + (hopsNum - 1) * 80 + Math.random() * 30;
            meshNodes.set(nhId, {
                id: nhId, hops: hopsNum - 1, rssi: 0, snr: 0, msgCount: 0,
                x: cx + Math.cos(angle) * dist, y: cy + Math.sin(angle) * dist,
                vx: 0, vy: 0, lastSeen: Date.now()
            });
        } else {
            const n = meshNodes.get(nhId);
            if (hopsNum - 1 < (n.hops || 99)) n.hops = hopsNum - 1;
        }
    }

    // Draw last-hop link: dest <-> nh (or dest <-> gateway when hops=1)
    const lkA = Math.min(destId, nhId), lkB = Math.max(destId, nhId);
    const existing = meshLinks.get(`${lkA}-${lkB}`);
    meshLinks.set(`${lkA}-${lkB}`, {
        rssi: existing ? existing.rssi : 0,
        snr:  existing ? existing.snr  : 0,
        sf:   existing ? existing.sf   : undefined,
        hops: 1,
        lastActive: Date.now()
    });

    updateMeshNodeList();
    updateMeshDstSelect();
    meshD3Update();
}

function handleMeshNeighbor(data) {
    // node|rssi|snr
    const [nid, rssi, snr] = data.split('|');
    const nodeId = parseInt(nid);
    const lkA = Math.min(nodeId, meshMyId), lkB = Math.max(nodeId, meshMyId);
    const existing = meshLinks.get(`${lkA}-${lkB}`);
    if (existing) { existing.rssi = parseFloat(rssi); existing.snr = parseFloat(snr); meshD3Update(); }
    addMeshLog(`neighbor N${nid}: rssi=${rssi} snr=${snr}`, 'rt');
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

// D3 state
let meshSim          = null;
let meshSvgRoot      = null;
let meshZoomTransform = d3.zoomIdentity;
let selectedDst      = 0;
let _serialPort      = null;
let _serialWriter    = null;
let _particleId      = 0;

// SF → link color (green=best, red=worst)
const SF_COLOR = { 7:'#1A7F37', 8:'#3FB950', 9:'#D29922', 10:'#F0883E', 11:'#CF222E', 12:'#8B0000' };
function sfColor(sf) { return SF_COLOR[sf] || '#8C959F'; }
function rssiColor(rssi) {
    if (rssi > -70) return '#1A7F37';
    if (rssi > -90) return '#D29922';
    return '#CF222E';
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

    // Force simulation — tighter than before, lighter feel
    meshSim = d3.forceSimulation()
        .force('link', d3.forceLink().id(d => d.id).distance(140).strength(0.5))
        .force('charge', d3.forceManyBody().strength(-500))
        .force('center', d3.forceCenter(w / 2, h / 2))
        .force('collision', d3.forceCollide(36))
        .alphaDecay(0.03)
        .on('tick', meshD3Tick);

    meshAnimLoop();
    setInterval(updateMeshNodeList, 2000);
}

function meshResize() {
    const svgEl = document.getElementById('meshSvg');
    if (!svgEl) return;
    const w = svgEl.clientWidth  || 600;
    const h = svgEl.clientHeight || 400;
    const cx = w / 2, cy = h / 2;

    d3.select('#meshSvg').attr('width', w).attr('height', h);

    if (meshSim) {
        meshSim.force('center', d3.forceCenter(cx, cy));
        // Fix gateway position
        const gw = meshNodes.get(meshMyId);
        if (gw) { gw.fx = cx; gw.fy = cy; }
        meshSim.alpha(0.1).restart();
    }
}

function meshD3Update() {
    if (!meshSvgRoot || !meshSim) return;

    const svgEl = document.getElementById('meshSvg');
    const w  = svgEl ? (svgEl.clientWidth  || 600) : 600;
    const h  = svgEl ? (svgEl.clientHeight || 400) : 400;
    const cx = w / 2, cy = h / 2;

    const nodesArr = [...meshNodes.values()];

    // Fix gateway at center
    const gw = meshNodes.get(meshMyId);
    if (gw) { gw.fx = cx; gw.fy = cy; }

    // Build links array for D3 (include sf for color)
    const linksArr = [];
    meshLinks.forEach((link, key) => {
        const [aId, bId] = key.split('-').map(Number);
        linksArr.push({ source: aId, target: bId, rssi: link.rssi, sf: link.sf, hops: link.hops, lastActive: link.lastActive });
    });

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
    const linkSel = linksG.selectAll('g.link-group').data(linksArr, d => `${d.source}-${d.target}`);

    const linkEnter = linkSel.enter().append('g').attr('class', 'link-group mesh-link');
    linkEnter.append('line');
    linkEnter.append('text')
        .attr('font-family', "'JetBrains Mono', monospace")
        .attr('font-size', '9px')
        .attr('fill', '#8C959F')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle');

    const linkMerge = linkEnter.merge(linkSel);
    linkMerge.select('line')
        .attr('stroke', d => d.sf ? sfColor(d.sf) : rssiColor(d.rssi || -100))
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 0.75)
        .attr('stroke-dasharray', d => (d.hops > 1) ? '5,3' : null);
    linkMerge.select('text')
        .text(d => d.sf ? `SF${d.sf}·${d.rssi}dBm` : `${d.rssi}dBm`);

    linkSel.exit().remove();

    // Nodes
    const nodesG   = meshSvgRoot.select('.mesh-nodes');
    const nodeSel  = nodesG.selectAll('g.mesh-node').data(nodesArr, d => d.id);

    const nodeEnter = nodeSel.enter().append('g').attr('class', 'mesh-node');

    nodeEnter.append('circle').attr('class', 'node-circle');
    // Selection ring — accent blue outline, no fill
    nodeEnter.append('circle').attr('class', 'selection-ring')
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

    // Drag
    const drag = d3.drag()
        .on('start', (event, d) => {
            if (!event.active) meshSim.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => {
            if (!event.active) meshSim.alphaTarget(0);
            if (d.id !== meshMyId) { d.fx = null; d.fy = null; }
        });

    nodeEnter.call(drag);

    // Click to select destination
    nodeEnter.on('click', (event, d) => {
        if (d.id === meshMyId) return;
        selectedDst = (selectedDst === d.id) ? 0 : d.id;
        const sel = document.getElementById('meshDstSelect');
        if (sel) sel.value = String(selectedDst);
        meshD3Update();
    });

    const nodeMerge = nodeEnter.merge(nodeSel);

    // Gateway: solid dark fill + white text. Others: white fill + dark stroke.
    nodeMerge.select('circle.node-circle')
        .attr('r', d => d.id === meshMyId ? 26 : 20)
        .attr('fill', d => d.id === meshMyId ? '#1F2328' : '#FFFFFF')
        .attr('stroke', d => d.id === meshMyId ? '#1F2328' : '#D0D7DE')
        .attr('stroke-width', 2);

    nodeMerge.select('circle.selection-ring')
        .attr('r', d => d.id === meshMyId ? 34 : 28)
        .attr('opacity', d => d.id === selectedDst ? 1 : 0);

    nodeMerge.select('text.node-label')
        .attr('font-size', d => d.id === meshMyId ? '12px' : '11px')
        .attr('fill', d => d.id === meshMyId ? '#FFFFFF' : '#1F2328')
        .text(d => `N${d.id}`);

    nodeMerge.select('text.node-sublabel')
        .attr('dy', d => (d.id === meshMyId ? 26 : 20) + 14)
        .text(d => {
            if (d.id === meshMyId) return 'gateway';
            if (d.rssi) return `${d.rssi}dBm`;
            return d.hops > 0 ? `${d.hops}hop` : '';
        });

    nodeSel.exit().remove();

    // Update simulation
    meshSim.nodes(nodesArr);
    meshSim.force('link').links(linksArr);
    meshSim.alpha(0.3).restart();
}

function meshD3Tick() {
    if (!meshSvgRoot) return;

    // Update links
    meshSvgRoot.select('.mesh-links').selectAll('g.link-group').each(function(d) {
        const g    = d3.select(this);
        const src  = typeof d.source === 'object' ? d.source : meshNodes.get(d.source);
        const tgt  = typeof d.target === 'object' ? d.target : meshNodes.get(d.target);
        if (!src || !tgt) return;
        g.select('line')
            .attr('x1', src.x).attr('y1', src.y)
            .attr('x2', tgt.x).attr('y2', tgt.y);
        g.select('text')
            .attr('x', (src.x + tgt.x) / 2)
            .attr('y', (src.y + tgt.y) / 2 - 9);
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

function meshAddOrUpdate(id, hops, rssi, snr) {
    const svgEl = document.getElementById('meshSvg');
    const cx    = svgEl ? (svgEl.clientWidth  || 600) / 2 : 300;
    const cy    = svgEl ? (svgEl.clientHeight || 400) / 2 : 200;

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
        const age   = Math.round((now - n.lastSeen) / 1000);
        const color = n.hops === 0 ? rssiColor(n.rssi || -100) : '#8C959F';
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

function updateMeshDstSelect() {
    const sel = document.getElementById('meshDstSelect');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="0">broadcast</option><option value="255">echo_all [255]</option>';
    meshNodes.forEach(n => {
        if (n.id === meshMyId) return;
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
    // data = "NODE_ID:<n>|SF:<sf>"
    const match = data.match(/NODE_ID:(\d+)(?:\|SF:(\d+))?/);
    if (!match) return;
    const nodeId = parseInt(match[1]);
    if (match[2]) {
        const el = document.getElementById('meshNetSf');
        if (el) el.innerText = `SF${match[2]}`;
    }
    if (nodeId === meshMyId) return;

    // Move the "YOU" node from the old meshMyId to the real NODE_ID
    const oldNode = meshNodes.get(meshMyId);
    meshNodes.delete(meshMyId);
    meshMyId = nodeId;
    if (oldNode) { oldNode.id = meshMyId; meshNodes.set(meshMyId, oldNode); }
    else {
        const svgEl = document.getElementById('meshSvg');
        meshNodes.set(meshMyId, {
            id: meshMyId, hops: 0, rssi: 0, snr: 0, msgCount: 0,
            x: svgEl ? svgEl.clientWidth  / 2 : 300,
            y: svgEl ? svgEl.clientHeight / 2 : 200,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
    }
    document.getElementById('meshMyNodeId').innerText = `N${meshMyId}`;
    log(`Gateway NODE_ID = ${meshMyId}`);
    meshD3Update();
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

    meshMsgCount++;
    document.getElementById('meshMsgCount').innerText = meshMsgCount;

    meshAddOrUpdate(src, hops, rssi, snr);

    // Only draw a direct RF link when the packet arrived with 0 relays.
    // Multi-hop topology is built from MESH_ROUTE events instead.
    if (hops === 0) {
        const lkA = Math.min(src, meshMyId), lkB = Math.max(src, meshMyId);
        const ex = meshLinks.get(`${lkA}-${lkB}`) || {};
        meshLinks.set(`${lkA}-${lkB}`, { rssi, snr, sf: ex.sf, hops: 0, lastActive: Date.now() });
    } else {
        // Update RSSI on the dest end of an existing route link if present
        const lkA = Math.min(src, meshMyId), lkB = Math.max(src, meshMyId);
        const ex = meshLinks.get(`${lkA}-${lkB}`);
        if (ex) { ex.rssi = rssi; ex.snr = snr; ex.lastActive = Date.now(); }
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
    // format: src|dst|mid|ttl|payload
    const parts = data.split('|');
    if (parts.length < 5) return;
    const dst     = parts[1];
    const payload = parts.slice(4).join('|');
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

async function sendMesh() {
    const input = document.getElementById('meshMsgInput');
    if (!input || !input.value.trim()) return;
    const msg = input.value.trim();
    const sel = document.getElementById('meshDstSelect');
    const dst = sel ? sel.value : '0';
    input.value = '';

    addChatBubble(msg, 'out');
    loraCsvRows.push([new Date().toISOString(), "TX", msg, "", "", ""]);

    if (dst === '0') {
        await send('SEND_MESH:' + msg);
    } else {
        await send(`SEND_NODE:${dst}:${msg}`);
    }
}

async function sendServo() {
    if (!writeChar) { log('Not connected'); return; }
    const id    = parseInt(document.getElementById('servoId').value) || 1;
    const angle = parseInt(document.getElementById('servoSlider').value);
    const sel   = document.getElementById('meshDstSelect');
    const dst   = sel ? sel.value : '0';
    const msg   = `SERVO:${id}:${angle}`;
    log(`→ SERVO N${id} @ ${angle}° → dst ${dst === '0' ? 'broadcast' : `N${dst}`}`);
    if (dst === '0') {
        await send('SEND_MESH:' + msg);
    } else {
        await send(`SEND_NODE:${dst}:${msg}`);
    }
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
        document.getElementById('serialBtn').textContent = 'disconnect_serial';
        document.getElementById('serialBtn').onclick = disconnectSerial;
        log('ESP32 serial connected (TX + RX)');
    } catch (e) {
        if (e.name !== 'NotFoundError') log('Serial error: ' + e.message);
    }
}

async function _serialReadLoop(reader) {
    let buf = '';
    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += value;
            const lines = buf.split('\n');
            buf = lines.pop(); // keep incomplete line
            lines.forEach(line => {
                const t = line.trim();
                if (!t) return;
                // Route mesh protocol lines to mesh log, rest to terminal
                const type = t.startsWith('TX') ? 'tx'
                           : t.startsWith('D ') || t.startsWith('H ') || t.startsWith('R ') ? 'rx'
                           : 'rt';
                addMeshLog(`[esp32] ${t}`, type);
            });
        }
    } catch (_) { /* port closed */ }
}

async function disconnectSerial() {
    try {
        if (_serialReader) { await _serialReader.cancel(); _serialReader = null; }
        if (_serialWriter) { await _serialWriter.close();  _serialWriter = null; }
        if (_serialPort)   { await _serialPort.close();    _serialPort   = null; }
    } catch (e) { /* ignore */ }
    document.getElementById('serialSendRow').style.display = 'none';
    const btn = document.getElementById('serialBtn');
    if (btn) { btn.textContent = 'Connect Serial'; btn.onclick = connectSerial; }
    log('ESP32 serial disconnected');
}

async function sendSerial(msg) {
    const input = document.getElementById('serialInput');
    const text  = msg !== undefined ? msg : (input ? input.value.trim() : '');
    if (!text || !_serialWriter) return;
    try {
        await _serialWriter.write(text + '\n');
        addMeshLog(`→ ESP32 serial: "${text}"`, 'tx');
        if (input) input.value = '';
    } catch (e) {
        log('Serial write error: ' + e.message);
    }
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

// ── Variant toggle ────────────────────────────────────────────────────────────
let _esp32Variant = 'standard';

function setEsp32Variant(v, btn) {
    _esp32Variant = v;
    btn.closest('.variant-ctrl').querySelectorAll('.var-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const hint = document.getElementById('esp32FwHint');
    if (hint) hint.textContent = v === 'servo' ? '// servo node — relay + MG90S PWM servo on D7  SERVO:<angle>'
                              :                 '// relay node — participates in mesh routing';
}

// ── Main flash function ───────────────────────────────────────────────────────
async function flashDevice(board) {
    if (!window.showDirectoryPicker) {
        log('Flash requires Chrome 86+ with File System Access API.');
        return;
    }

    const nodeId   = parseInt(document.getElementById('flashNodeId').value) || 1;
    const label    = board === 'nrf' ? 'nRF52840' : 'ESP32-S3';
    const useServo = board === 'esp32' && _esp32Variant === 'servo';
    const codeFile = board === 'nrf' ? 'code_nrf.py'
                   : useServo        ? 'code_esp32_servo.py'
                   :                   'code_esp32.py';
    const btns    = document.querySelectorAll('.btn-flash');
    btns.forEach(b => b.classList.add('flashing'));

    try {
        // ── Fetch firmware files ───────────────────────────────────────────────
        const varLabel = useServo ? 'servo_node' : 'standard';
        log(`[Flash ${label}] Fetching firmware (Node ID = ${nodeId}, ${varLabel})…`);
        const [codeResp, commonResp, sx1262Resp, scservoResp] = await Promise.all([
            fetch(codeFile),
            fetch('mesh_common.py'),
            fetch('sx1262.py'),
            fetch('scservo.py'),
        ]);
        if (!codeResp.ok)    throw new Error(`Cannot fetch ${codeFile} (${codeResp.status})`);
        if (!commonResp.ok)  throw new Error(`Cannot fetch mesh_common.py (${commonResp.status})`);
        if (!sx1262Resp.ok)  throw new Error(`Cannot fetch sx1262.py (${sx1262Resp.status})`);
        if (!scservoResp.ok) throw new Error(`Cannot fetch scservo.py (${scservoResp.status})`);

        let codeContent      = await codeResp.text();
        const commonContent  = await commonResp.text();
        const sx1262Content  = await sx1262Resp.text();
        const scservoContent = await scservoResp.text();

        // Inject chosen NODE_ID
        codeContent = codeContent.replace(/^NODE_ID\s*=\s*\d+/m, `NODE_ID = ${nodeId}`);

        // ── Resolve CIRCUITPY drive handle ────────────────────────────────────
        let destDir = await _handleGet('drive-' + board);

        if (destDir) {
            destDir = await _verifyPermission(destDir);
        }

        if (!destDir) {
            // First flash for this board — ask once, then remember
            log(`[Flash ${label}] Select the CIRCUITPY drive…`);
            destDir = await window.showDirectoryPicker({ id: 'circuitpy-' + board, mode: 'readwrite' });
            await _handleSet('drive-' + board, destDir);
            await _refreshDriveStatus(board);
        }

        // ── Write files ───────────────────────────────────────────────────────
        async function writeFile(dir, name, text) {
            const fh = await dir.getFileHandle(name, { create: true });
            const wr = await fh.createWritable();
            await wr.write(text);
            await wr.close();
        }

        await writeFile(destDir, 'sx1262.py', sx1262Content);
        await writeFile(destDir, 'scservo.py', scservoContent);
        await writeFile(destDir, 'mesh_common.py', commonContent);
        await writeFile(destDir, 'code.py', codeContent);

        const varSuffix = useServo ? '  [servo_node]' : '';
        log(`✓ ${label} Node ${nodeId} → ${destDir.name}/  [sx1262+mesh_common+code]${varSuffix}  (board restarts)`);
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
// SCENARIO SIMULATOR
// =============================================

const SIM_SF_AIRTIME   = { 7: 41, 8: 72, 9: 144, 10: 289, 11: 577, 12: 1154 };
const SIM_NOISE_FLOOR  = -174 + 10 * Math.log10(125000) + 6; // ≈ -117 dBm (BW=125kHz, NF=6dB)

let simState   = null;
let simSvgRoot = null;

// ── Physics helpers ───────────────────────────────────────────────────────────
function _gaussRand(mu, sigma) {
    let u; do { u = Math.random(); } while (u === 0);
    let v; do { v = Math.random(); } while (v === 0);
    return mu + sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function _friisRSSI(distM, txDbm, n, sigmaDb) {
    const lambda  = 3e8 / 912e6;                              // ~0.329 m
    const plRef   = 20 * Math.log10(4 * Math.PI / lambda);   // free-space PL at 1 m ≈ 71.8 dB
    const pl      = plRef + 10 * n * Math.log10(Math.max(distM, 0.5));
    const shadow  = sigmaDb > 0 ? _gaussRand(0, sigmaDb) : 0;
    return txDbm - pl - shadow;
}

// SF from SNR — mirrors mesh_common.py SF_HOLD thresholds (step-up boundaries)
function _bestSF(snr) {
    if (snr >= -2.5)  return 7;
    if (snr >= -5.0)  return 8;
    if (snr >= -7.5)  return 9;
    if (snr >= -10.0) return 10;
    if (snr >= -12.5) return 11;
    if (snr >= -17.5) return 12;
    return null; // out of range
}

// ── Node placement ────────────────────────────────────────────────────────────
function _simPlaceNodes(count, topology, areaM) {
    const nodes = [];
    if (topology === 'grid') {
        const cols = Math.ceil(Math.sqrt(count));
        const rows = Math.ceil(count / cols);
        const dx = areaM / (cols + 1), dy = areaM / (rows + 1);
        for (let i = 0; i < count; i++)
            nodes.push({ id: i + 1, mx: dx * (i % cols + 1), my: dy * (Math.floor(i / cols) + 1) });
    } else if (topology === 'line') {
        const dx = areaM / (count + 1);
        for (let i = 0; i < count; i++)
            nodes.push({ id: i + 1, mx: dx * (i + 1), my: areaM / 2 });
    } else if (topology === 'ring') {
        const cx = areaM / 2, cy = areaM / 2, r = areaM * 0.4;
        for (let i = 0; i < count; i++) {
            const a = (2 * Math.PI * i / count) - Math.PI / 2;
            nodes.push({ id: i + 1, mx: cx + r * Math.cos(a), my: cy + r * Math.sin(a) });
        }
    } else if (topology === 'star') {
        const cx = areaM / 2, cy = areaM / 2, r = areaM * 0.38;
        nodes.push({ id: 1, mx: cx, my: cy });
        for (let i = 1; i < count; i++) {
            const a = (2 * Math.PI * (i - 1) / (count - 1)) - Math.PI / 2;
            nodes.push({ id: i + 1, mx: cx + r * Math.cos(a), my: cy + r * Math.sin(a) });
        }
    } else { // random
        for (let i = 0; i < count; i++)
            nodes.push({ id: i + 1, mx: 50 + Math.random() * (areaM - 100), my: 50 + Math.random() * (areaM - 100) });
    }
    return nodes;
}

// ── Bellman-Ford (bidirectional edges) ────────────────────────────────────────
function _bellmanFord(nodes, edges, srcId) {
    const dist = {}, prev = {};
    nodes.forEach(n => { dist[n.id] = n.id === srcId ? 0 : Infinity; });

    for (let iter = 0; iter < nodes.length; iter++) {
        let changed = false;
        edges.forEach(e => {
            if (!isFinite(e.cost)) return;
            if (dist[e.src] + e.cost < dist[e.dst]) {
                dist[e.dst] = dist[e.src] + e.cost; prev[e.dst] = e.src; changed = true;
            }
            if (dist[e.dst] + e.cost < dist[e.src]) {
                dist[e.src] = dist[e.dst] + e.cost; prev[e.src] = e.dst; changed = true;
            }
        });
        if (!changed) break;
    }

    function getPath(dstId) {
        if (dstId === srcId) return [srcId];
        if (!isFinite(dist[dstId])) return null;
        const path = []; let cur = dstId, guard = 0;
        while (cur !== srcId && guard++ < 30) { path.unshift(cur); cur = prev[cur]; }
        if (cur !== srcId) return null;
        return [srcId, ...path];
    }
    return { dist, getPath };
}

// ── Main generate ─────────────────────────────────────────────────────────────
function simGenerate() {
    const count   = parseInt(document.getElementById('simNodeCount').value);
    const topo    = document.getElementById('simTopology').value;
    const areaM   = parseInt(document.getElementById('simArea').value);
    const envParts = document.getElementById('simEnv').value.split(':');
    const n       = parseFloat(envParts[0]);
    const sigma   = parseFloat(envParts[1]);
    const txPow   = parseInt(document.getElementById('simTxPower').value);
    const intPct  = parseInt(document.getElementById('simInterference').value) / 100;
    const failPct = parseInt(document.getElementById('simFailure').value) / 100;

    const nodes = _simPlaceNodes(count, topo, areaM);

    // Apply random failures (never fail node 1 = gateway)
    nodes.forEach((nd, i) => { nd.failed = i > 0 && Math.random() < failPct; });

    const active = nodes.filter(nd => !nd.failed);

    // Compute pairwise links
    const links = [];
    for (let i = 0; i < active.length; i++) {
        for (let j = i + 1; j < active.length; j++) {
            const a = active[i], b = active[j];
            const dist  = Math.sqrt((a.mx - b.mx) ** 2 + (a.my - b.my) ** 2);
            const rssi  = _friisRSSI(dist, txPow, n, sigma);
            const snr   = rssi - SIM_NOISE_FLOOR;
            const sf    = _bestSF(snr);
            if (sf === null) continue;
            links.push({
                src:  a.id, dst: b.id,
                distM: Math.round(dist),
                rssi: Math.round(rssi),
                snr:  Math.round(snr * 10) / 10,
                sf,
                cost: SIM_SF_AIRTIME[sf],
            });
        }
    }

    // Network-wide SF = worst (highest SF) of all direct links
    const networkSF = links.length > 0 ? Math.max(...links.map(l => l.sf)) : 7;

    // Routing tables from every non-failed node
    const routes = {};
    active.forEach(nd => { routes[nd.id] = _bellmanFord(active, links, nd.id); });

    simState = { nodes, active, links, routes, networkSF, areaM, intPct };

    _simPopulateSelects();
    _simDraw(null);
    _simShowResults();
}

// ── Populate from/to selects ──────────────────────────────────────────────────
function _simPopulateSelects() {
    if (!simState) return;
    const active = simState.active;
    ['simSrc', 'simDst'].forEach((elId, idx) => {
        const sel = document.getElementById(elId);
        const prev = sel.value;
        sel.innerHTML = '';
        active.forEach(nd => {
            const opt = document.createElement('option');
            opt.value = nd.id; opt.textContent = `N${nd.id}`;
            if (idx === 0 && nd.id === 1) opt.selected = true;
            if (idx === 1 && nd.id === active[active.length - 1].id && !prev) opt.selected = true;
            sel.appendChild(opt);
        });
        if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    });
}

// ── D3 draw ───────────────────────────────────────────────────────────────────
function _simDraw(highlightPath) {
    if (!simState || !simSvgRoot) return;
    const { nodes, links, networkSF, areaM } = simState;

    const svgEl = document.getElementById('simSvg');
    const W = svgEl ? (svgEl.clientWidth  || 800) : 800;
    const H = svgEl ? (svgEl.clientHeight || 480) : 480;
    const PAD = 48;
    const scale = Math.min((W - 2 * PAD) / areaM, (H - 2 * PAD) / areaM);
    const ox = (W - areaM * scale) / 2;
    const oy = (H - areaM * scale) / 2;
    const px = m => ox + m * scale;
    const py = m => oy + m * scale;

    // Area border
    simSvgRoot.selectAll('.sim-area-rect, .sim-net-sf, .sim-scalebar, .sim-legend-g').remove();
    simSvgRoot.insert('rect', ':first-child').attr('class', 'sim-area-rect')
        .attr('x', ox).attr('y', oy)
        .attr('width', areaM * scale).attr('height', areaM * scale)
        .attr('fill', 'none').attr('stroke', '#D0D7DE').attr('stroke-dasharray', '6,4');

    // Network SF label
    simSvgRoot.append('text').attr('class', 'sim-net-sf')
        .attr('x', ox + 6).attr('y', oy - 8)
        .attr('font-family', "'JetBrains Mono', monospace").attr('font-size', '11px')
        .attr('fill', sfColor(networkSF))
        .text(`network_sf: SF${networkSF}  (${SIM_SF_AIRTIME[networkSF]}ms/hop)`);

    // Scale bar (bottom-right)
    const barM = Math.round(areaM / 4 / 100) * 100 || 100;
    const barPx = barM * scale;
    const bx = ox + areaM * scale - barPx - 4, by = oy + areaM * scale + 14;
    const sbg = simSvgRoot.append('g').attr('class', 'sim-scalebar');
    sbg.append('line').attr('x1', bx).attr('y1', by).attr('x2', bx + barPx).attr('y2', by)
        .attr('stroke', '#8C959F').attr('stroke-width', 1.5);
    sbg.append('line').attr('x1', bx).attr('y1', by - 3).attr('x2', bx).attr('y2', by + 3)
        .attr('stroke', '#8C959F').attr('stroke-width', 1.5);
    sbg.append('line').attr('x1', bx + barPx).attr('y1', by - 3).attr('x2', bx + barPx).attr('y2', by + 3)
        .attr('stroke', '#8C959F').attr('stroke-width', 1.5);
    sbg.append('text').attr('x', bx + barPx / 2).attr('y', by + 11)
        .attr('font-family', "'JetBrains Mono', monospace").attr('font-size', '9px')
        .attr('fill', '#8C959F').attr('text-anchor', 'middle').text(`${barM}m`);

    // SF color legend (top-right)
    const lgx = ox + areaM * scale - 4, lgy = oy + 6;
    const lgG = simSvgRoot.append('g').attr('class', 'sim-legend-g');
    [7, 8, 9, 10, 11, 12].forEach((sf, i) => {
        lgG.append('circle').attr('cx', lgx - 10).attr('cy', lgy + i * 13 + 4).attr('r', 4)
            .attr('fill', sfColor(sf));
        lgG.append('text').attr('x', lgx - 18).attr('y', lgy + i * 13 + 8)
            .attr('font-family', "'JetBrains Mono', monospace").attr('font-size', '9px')
            .attr('fill', '#8C959F').attr('text-anchor', 'end').text(`SF${sf}`);
    });

    // Highlighted path set
    const hlSet = new Set();
    if (highlightPath) {
        for (let i = 0; i < highlightPath.length - 1; i++) {
            const a = Math.min(highlightPath[i], highlightPath[i+1]);
            const b = Math.max(highlightPath[i], highlightPath[i+1]);
            hlSet.add(`${a}-${b}`);
        }
    }

    // ── Links ──────────────────────────────────────────────────────────────────
    const linksG  = simSvgRoot.select('.sim-links');
    const linkSel = linksG.selectAll('g.sim-link').data(links, d => `${d.src}-${d.dst}`);

    const linkEnter = linkSel.enter().append('g').attr('class', 'sim-link');
    linkEnter.append('line');
    linkEnter.append('text')
        .attr('font-family', "'JetBrains Mono', monospace").attr('font-size', '9px')
        .attr('text-anchor', 'middle').attr('pointer-events', 'none');

    const linkMerge = linkEnter.merge(linkSel);
    linkMerge.each(function(d) {
        const na = nodes.find(n => n.id === d.src);
        const nb = nodes.find(n => n.id === d.dst);
        if (!na || !nb) return;
        const key = `${Math.min(d.src, d.dst)}-${Math.max(d.src, d.dst)}`;
        const hl = hlSet.has(key);
        const col = sfColor(d.sf);
        d3.select(this).select('line')
            .attr('x1', px(na.mx)).attr('y1', py(na.my))
            .attr('x2', px(nb.mx)).attr('y2', py(nb.my))
            .attr('stroke', col)
            .attr('stroke-width', hl ? 3 : 1.5)
            .attr('stroke-opacity', hl ? 1 : 0.25);
        const mx = (px(na.mx) + px(nb.mx)) / 2;
        const my = (py(na.my) + py(nb.my)) / 2;
        d3.select(this).select('text')
            .attr('x', mx).attr('y', my - 5)
            .attr('fill', hl ? col : '#8C959F')
            .attr('opacity', hl ? 1 : 0.6)
            .text(hl ? `SF${d.sf} · ${d.rssi}dBm · ${d.distM}m` : `SF${d.sf}`);
    });
    linkSel.exit().remove();

    // ── Nodes ──────────────────────────────────────────────────────────────────
    const nodesG  = simSvgRoot.select('.sim-nodes');
    const nodeSel = nodesG.selectAll('g.sim-node').data(nodes, d => d.id);

    const nodeEnter = nodeSel.enter().append('g').attr('class', 'sim-node').style('cursor', 'pointer')
        .on('click', (event, d) => {
            if (d.failed) return;
            const src = document.getElementById('simSrc');
            const dst = document.getElementById('simDst');
            if (event.shiftKey) { if (dst) dst.value = d.id; }
            else                { if (src) src.value = d.id; }
        });
    nodeEnter.append('circle').attr('class', 'sim-nc');
    nodeEnter.append('text').attr('class', 'sim-nl')
        .attr('font-family', "'JetBrains Mono', monospace").attr('font-weight', '700')
        .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle').attr('pointer-events', 'none');
    nodeEnter.append('text').attr('class', 'sim-ns')
        .attr('font-family', "'JetBrains Mono', monospace").attr('font-size', '9px')
        .attr('text-anchor', 'middle').attr('fill', '#8C959F').attr('pointer-events', 'none');

    const nodeMerge = nodeEnter.merge(nodeSel);
    nodeMerge.each(function(d) {
        const isGw = d.id === 1;
        const hl   = highlightPath && highlightPath.includes(d.id);
        const x = px(d.mx), y = py(d.my);
        const r = isGw ? 22 : 17;
        d3.select(this).attr('transform', `translate(${x},${y})`);
        d3.select(this).select('circle.sim-nc')
            .attr('r', r)
            .attr('fill', d.failed ? '#F6F8FA' : (hl ? '#1F2328' : (isGw ? '#1F2328' : '#FFFFFF')))
            .attr('stroke', d.failed ? '#D0D7DE' : (hl ? sfColor(networkSF) : (isGw ? '#1F2328' : '#D0D7DE')))
            .attr('stroke-width', hl ? 3 : 2)
            .attr('opacity', d.failed ? 0.35 : 1);
        d3.select(this).select('text.sim-nl')
            .attr('font-size', isGw ? '12px' : '11px')
            .attr('fill', d.failed ? '#8C959F' : (hl || isGw ? '#FFFFFF' : '#1F2328'))
            .attr('opacity', d.failed ? 0.4 : 1)
            .text(`N${d.id}`);
        const sub = d.failed ? 'failed' : (isGw ? 'gateway' : '');
        d3.select(this).select('text.sim-ns')
            .attr('dy', r + 12).attr('opacity', d.failed ? 0.4 : 1).text(sub);
    });
    nodeSel.exit().remove();
}

// ── Results table ─────────────────────────────────────────────────────────────
function _simShowResults() {
    if (!simState) return;
    const { nodes, active, links, routes, networkSF } = simState;

    const r1 = routes[1];
    let reachable = 0;
    if (r1) active.forEach(n => { if (n.id !== 1 && isFinite(r1.dist[n.id])) reachable++; });
    const maxRange = links.length > 0 ? Math.max(...links.map(l => l.distM)) : 0;
    const avgSF    = links.length > 0
        ? Math.round(links.reduce((s, l) => s + l.sf, 0) / links.length * 10) / 10
        : '—';

    const el = document.getElementById('simResults');
    if (!el) return;

    let html = `<div class="sim-stats-row">
        <span class="sim-stat"><span class="sim-stat-label">network_sf</span><span class="sim-stat-val" style="color:${sfColor(networkSF)}">SF${networkSF} · ${SIM_SF_AIRTIME[networkSF]}ms/hop</span></span>
        <span class="sim-stat"><span class="sim-stat-label">reachable</span><span class="sim-stat-val">${reachable}/${active.length - 1} nodes</span></span>
        <span class="sim-stat"><span class="sim-stat-label">links</span><span class="sim-stat-val">${links.length}</span></span>
        <span class="sim-stat"><span class="sim-stat-label">max_range</span><span class="sim-stat-val">${maxRange}m</span></span>
        <span class="sim-stat"><span class="sim-stat-label">avg_sf</span><span class="sim-stat-val">${avgSF}</span></span>
    </div>`;

    if (r1 && active.length > 1) {
        html += `<div class="sim-table-wrap"><table class="sim-table">
        <thead><tr>
            <th>dst</th><th>path</th><th>hops</th>
            <th>mesh_airtime</th><th>flood_SF${networkSF}</th><th>direct_SF12</th><th>saving_vs_direct</th>
        </tr></thead><tbody>`;

        active.filter(n => n.id !== 1).forEach(n => {
            const path = r1.getPath(n.id);
            const cost = r1.dist[n.id];
            if (!path) {
                html += `<tr><td>N${n.id}</td><td colspan="6" style="color:var(--err)">unreachable</td></tr>`;
                return;
            }
            const hops = path.length - 1;
            const floodCost = hops * SIM_SF_AIRTIME[networkSF];

            // Direct SF12 — check if link exists at all
            const dl = links.find(l => (l.src===1&&l.dst===n.id)||(l.src===n.id&&l.dst===1));
            const directCost = dl ? SIM_SF_AIRTIME[12] : null;

            const saving = directCost !== null
                ? Math.round((1 - cost / directCost) * 100)
                : null;
            const savingStr = saving !== null
                ? `<span style="color:${saving >= 0 ? 'var(--ok)' : 'var(--err)'}">${saving >= 0 ? '+' : ''}${saving}%</span>`
                : '—';

            html += `<tr>
                <td><b>N${n.id}</b></td>
                <td class="sim-td-path">${path.map(id => `N${id}`).join('→')}</td>
                <td>${hops}</td>
                <td style="color:${sfColor(networkSF)}">${isFinite(cost) ? cost + 'ms' : '—'}</td>
                <td style="color:var(--text-muted)">${floodCost}ms</td>
                <td style="color:var(--text-muted)">${directCost ? directCost + 'ms' : '—'}</td>
                <td>${savingStr}</td>
            </tr>`;
        });
        html += '</tbody></table></div>';
    }
    el.innerHTML = html;
}

// ── Packet simulation ─────────────────────────────────────────────────────────
function simSendPacket() {
    if (!simState) { simGenerate(); return; }
    const src  = parseInt(document.getElementById('simSrc').value);
    const dst  = parseInt(document.getElementById('simDst').value);
    const mode = document.getElementById('simMode').value;
    const { routes, links, networkSF, intPct } = simState;
    const resultEl = document.getElementById('simPacketResult');

    if (src === dst) { resultEl.textContent = 'src = dst'; return; }

    function hopAirtime(a, b, forceSF) {
        const link = links.find(l => (l.src===a&&l.dst===b)||(l.src===b&&l.dst===a));
        const sf   = forceSF || (link ? link.sf : networkSF);
        const base = SIM_SF_AIRTIME[sf] || SIM_SF_AIRTIME[networkSF];
        // E[retransmits] = 1/(1-p) with interference probability p
        return intPct > 0 ? Math.round(base / (1 - intPct)) : base;
    }

    function pathSummary(path, label, forceSF) {
        if (!path) return `<span style="color:var(--err)">${label}: unreachable</span>`;
        let total = 0;
        for (let i = 0; i < path.length - 1; i++) total += hopAirtime(path[i], path[i+1], forceSF);
        const hops = path.length - 1;
        return `<b>${label}</b>: ${path.map(id=>`N${id}`).join('→')} · ${hops}hop · <b>${total}ms</b>`;
    }

    const r = routes[src];
    const routedPath = r ? r.getPath(dst) : null;
    const dl = links.find(l => (l.src===src&&l.dst===dst)||(l.src===dst&&l.dst===src));

    if (mode === 'routed') {
        if (!routedPath) { resultEl.innerHTML = `<span style="color:var(--err)">no route N${src}→N${dst}</span>`; return; }
        _simDraw(routedPath);
        resultEl.innerHTML = pathSummary(routedPath, 'routed_mesh', null)
            + (intPct > 0 ? ` <span style="color:var(--warn)">(+${Math.round(intPct*100)}% interference)</span>` : '');

    } else if (mode === 'direct') {
        if (!dl) { resultEl.innerHTML = `<span style="color:var(--err)">N${src}↔N${dst} out of range</span>`; return; }
        _simDraw([src, dst]);
        resultEl.innerHTML = pathSummary([src, dst], 'direct_SF12', 12);

    } else if (mode === 'flood') {
        if (!routedPath) { resultEl.innerHTML = `<span style="color:var(--err)">unreachable</span>`; return; }
        _simDraw(routedPath);
        let total = 0;
        for (let i = 0; i < routedPath.length - 1; i++) total += hopAirtime(routedPath[i], routedPath[i+1], networkSF);
        resultEl.innerHTML = pathSummary(routedPath, `flood_SF${networkSF}`, networkSF);

    } else { // compare_all
        const lines = [];
        if (routedPath) lines.push(pathSummary(routedPath, 'routed_mesh', null));
        else lines.push('<span style="color:var(--err)">routed_mesh: unreachable</span>');
        if (dl) lines.push(pathSummary([src, dst], 'direct_SF12', 12));
        else lines.push('<span style="color:var(--text-muted)">direct_SF12: out of range</span>');
        if (routedPath) lines.push(pathSummary(routedPath, `flood_SF${networkSF}`, networkSF));
        _simDraw(routedPath);
        resultEl.innerHTML = lines.join('<br>');
    }
}

// ── Init SVG ──────────────────────────────────────────────────────────────────
function simInit() {
    const svgEl = document.getElementById('simSvg');
    if (!svgEl) return;
    const svg = d3.select('#simSvg');
    const w = svgEl.clientWidth || 800, h = svgEl.clientHeight || 480;
    svg.attr('width', w).attr('height', h);

    const defs = svg.append('defs');
    const pat  = defs.append('pattern').attr('id', 'sim-grid').attr('width', 24).attr('height', 24)
        .attr('patternUnits', 'userSpaceOnUse');
    pat.append('circle').attr('cx', 2).attr('cy', 2).attr('r', 1).attr('fill', '#D0D7DE');
    svg.append('rect').attr('width', '100%').attr('height', '100%').attr('fill', 'url(#sim-grid)');

    simSvgRoot = svg.append('g');
    simSvgRoot.append('g').attr('class', 'sim-links');
    simSvgRoot.append('g').attr('class', 'sim-nodes');
}

// =============================================
// INITIALIZATION
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    meshInit();
    simInit();
    _refreshDriveStatus('nrf');
    _refreshDriveStatus('esp32');

    window.addEventListener('resize', () => {
        if (loraGraphData.length > 0) drawLoraRssiChart();
        meshResize();
        if (currentTab === 'sim' && simState) _simDraw(null);
    });

    // Reconnect when tab becomes visible again (browser may have dropped BLE in background)
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && device && !device.gatt.connected && !_userDisconnected && !_reconnectTimer) {
            log('tab visible — reconnecting…');
            _attemptReconnect();
        }
    });
});
