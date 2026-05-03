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
    if (box) {
        const time = new Date().toLocaleTimeString('en-US', { hour12: false });
        const line = document.createElement('div');
        line.className = 'monitor-line' + (isErr ? ' monitor-err' : '');
        line.textContent = `[${time}] ${msg}`;
        box.appendChild(line);
        box.scrollTop = box.scrollHeight;
        while (box.children.length > 200) box.removeChild(box.firstChild);
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

    if (id === 'mesh') setTimeout(meshResize, 50);
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
            id: 0, hops: 0, rssi: 0, snr: 0, msgCount: 0,
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
    if (!writeChar) return;
    const data = new TextEncoder().encode(cmd);
    try {
        if (writeChar.properties.writeWithoutResponse) await writeChar.writeValueWithoutResponse(data);
        else await writeChar.writeValue(data);
    } catch (e) { log('Tx Error: ' + e); }
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
    const nodeId  = parseInt(nid);
    const rssiVal = parseFloat(rssi);
    const snrVal  = parseFloat(snr);

    // Ensure node exists (direct neighbor = 1 hop)
    const svgEl = document.getElementById('meshSvg');
    const cx = svgEl ? (svgEl.clientWidth  || 600) / 2 : 300;
    const cy = svgEl ? (svgEl.clientHeight || 400) / 2 : 200;
    if (!meshNodes.has(nodeId)) {
        const angle = Math.random() * Math.PI * 2;
        meshNodes.set(nodeId, {
            id: nodeId, hops: 1, rssi: rssiVal, snr: snrVal, msgCount: 0,
            x: cx + Math.cos(angle) * 140, y: cy + Math.sin(angle) * 140,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
        document.getElementById('meshNodeCount').innerText =
            [...meshNodes.keys()].filter(k => k !== meshMyId).length;
        updateMeshDstSelect();
    } else {
        const n = meshNodes.get(nodeId);
        n.rssi = rssiVal; n.snr = snrVal; n.lastSeen = Date.now();
    }

    // Always create/update the direct link
    const lkA = Math.min(nodeId, meshMyId), lkB = Math.max(nodeId, meshMyId);
    meshLinks.set(`${lkA}-${lkB}`, { rssi: rssiVal, snr: snrVal, hops: 0, lastActive: Date.now() });

    updateMeshNodeList();
    meshD3Update();
    addMeshLog(`neighbor N${nid}: rssi=${rssi} snr=${snr}`, 'rt');
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
        .text(d => d.id === 0 ? '?' : `N${d.id}`);

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

    // Move gateway placeholder node to the real NODE_ID
    const svgEl = document.getElementById('meshSvg');
    const cx = svgEl ? svgEl.clientWidth  / 2 : 300;
    const cy = svgEl ? svgEl.clientHeight / 2 : 200;
    const oldNode = meshNodes.get(meshMyId);
    meshNodes.delete(meshMyId);
    meshMyId = nodeId;
    if (oldNode) {
        oldNode.id = meshMyId;
        oldNode.fx = cx; oldNode.fy = cy;
        meshNodes.set(meshMyId, oldNode);
    } else {
        meshNodes.set(meshMyId, {
            id: meshMyId, hops: 0, rssi: 0, snr: 0, msgCount: 0,
            x: cx, y: cy, fx: cx, fy: cy,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
    }
    document.getElementById('meshMyNodeId').innerText = `N${meshMyId}`;
    log(`Gateway NODE_ID = ${meshMyId}`);
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
        _serialTabSetUI(true);
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
            buf = lines.pop();
            lines.forEach(line => {
                const t = line.trim();
                if (!t) return;

                // Classify for mesh log colour
                const type = t.startsWith('TX') ? 'tx'
                           : t.startsWith('RX')  ? 'rx'
                           : 'rt';
                addMeshLog(`[esp32] ${t}`, type);

                // Raw terminal in serial tab
                const rawBox = document.getElementById('serialRawLog');
                if (rawBox) {
                    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
                    const line = document.createElement('div');
                    line.className = 'monitor-line' + (t.startsWith('RX') ? '' : t.startsWith('TX') ? ' monitor-tx' : '');
                    line.textContent = `[${time}] ${t}`;
                    rawBox.appendChild(line);
                    rawBox.scrollTop = rawBox.scrollHeight;
                    while (rawBox.children.length > 300) rawBox.removeChild(rawBox.firstChild);
                }

                // Parse DELIVER → incoming chat bubble (src/dst routing)
                const dlv = t.match(/DELIVER src=(\d+) dst=(\d+):\s*'?(.*?)'?\s*$/);
                if (dlv) {
                    const _src = parseInt(dlv[1]), _dst = parseInt(dlv[2]);
                    addSerialChatBubble(dlv[3], 'in', _dst === 0 ? 0 : _src);
                }

                // Parse RX H / RX D → node discovery for dst selector
                const rxNode = t.match(/RX [HD]\s+src=N(\d+)/);
                if (rxNode) _serialTabNodeAdd(parseInt(rxNode[1]));

                // ── Serial → mesh viz ─────────────────────────────────────
                // Node identity: startup print OR periodic TX H (catches late-connect)
                const mId = t.match(/^Node (\d+)\s/) || t.match(/^TX H N(\d+)/);
                if (mId) _serialMeshSetId(parseInt(mId[1]));

                // RX H: direct neighbor
                const mH = t.match(/RX H\s+src=N(\d+)\s+rssi=(-?\d+)\s+snr=([-\d.]+)/);
                if (mH) _serialMeshNeighbor(parseInt(mH[1]), parseInt(mH[2]), parseFloat(mH[3]));

                // RX R [NEW]: route learned
                const mR = t.match(/RX R\s+orig=N(\d+) fwd=N\d+ mid=\d+ hops=\d+ -> nh=N(\d+) total=(\d+) \[NEW\]/);
                if (mR) _serialMeshRoute(parseInt(mR[1]), parseInt(mR[2]), parseInt(mR[3]));

                // RX D: data packet (update src node stats)
                const mD = t.match(/RX D\s+src=N(\d+) dst=N\d+ nh=N\d+ mid=\d+ ttl=(\d+) rssi=(-?\d+)/);
                if (mD) _serialMeshData(parseInt(mD[1]), parseInt(mD[2]), parseInt(mD[3]));
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
    _serialTabSetUI(false);
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
// SERIAL → MESH VIZ
// =============================================
let _serialMyId = null;

function _serialMeshSetId(id) {
    if (_serialMyId === id) return;
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
        x: cx, y: cy, fx: cx, fy: cy, vx: 0, vy: 0, lastSeen: Date.now() });
    meshD3Update();
    log(`serial node: N${id}`);
}

function _serialMeshNeighbor(nid, rssi, snr) {
    if (writeChar) return;
    meshAddOrUpdate(nid, 1, rssi, snr);
    if (_serialMyId) {
        const a = Math.min(nid, _serialMyId), b = Math.max(nid, _serialMyId);
        meshLinks.set(`${a}-${b}`, { rssi, snr, hops: 0, lastActive: Date.now() });
        meshD3Update();
    }
}

function _serialMeshRoute(orig, nh, totalHops) {
    if (writeChar) return;
    if (!meshNodes.has(orig)) meshAddOrUpdate(orig, totalHops, 0, 0);
    else { meshNodes.get(orig).hops = totalHops; meshNodes.get(orig).lastSeen = Date.now(); }
    if (_serialMyId && nh !== _serialMyId && !meshNodes.has(nh))
        meshAddOrUpdate(nh, Math.max(1, totalHops - 1), 0, 0);
    const a = Math.min(orig, nh), b = Math.max(orig, nh);
    meshLinks.set(`${a}-${b}`, { rssi: 0, snr: 0, hops: totalHops - 1, lastActive: Date.now() });
    updateMeshNodeList(); updateMeshDstSelect(); meshD3Update();
}

function _serialMeshData(src, ttl, rssi) {
    if (writeChar) return;
    const hops = TTL_DEFAULT - ttl;
    meshAddOrUpdate(src, hops > 0 ? hops : 1, rssi, 0);
    meshMsgCount++;
    document.getElementById('meshMsgCount').innerText = meshMsgCount;
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

async function serialTabToggle() {
    if (_serialPort) await disconnectSerial();
    else             await connectSerial();
}

async function serialTabSend() {
    const input = document.getElementById('serialMsgInput');
    if (!input || !input.value.trim()) return;
    if (!_serialWriter) { log('Serial not connected'); return; }

    const text = input.value.trim();
    const dst  = _serialActiveConv;
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
let _esp32Variant = 'standard';
let _flashNodeId  = 2;

function setFlashNodeId(n, btn) {
    _flashNodeId = n;
    btn.closest('#nodeIdCtrl').querySelectorAll('.var-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

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

    const nodeId   = _flashNodeId;
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
// INITIALIZATION

document.addEventListener('DOMContentLoaded', () => {
    meshInit();
    _refreshDriveStatus('nrf');
    _refreshDriveStatus('esp32');

    window.addEventListener('resize', () => {
        meshResize();
    });

    // Reconnect when tab becomes visible again (browser may have dropped BLE in background)
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && device && !device.gatt.connected && !_userDisconnected && !_reconnectTimer) {
            log('tab visible — reconnecting…');
            _attemptReconnect();
        }
    });
});
