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

        // cmd_rx  (…41…): we WRITE commands here
        // data_tx (…42…): we SUBSCRIBE for notifications here
        const UUIDS = {
            svc:    `${base}40-4150-b42d-22f30b0a0499`,
            write:  `${base}41-4150-b42d-22f30b0a0499`,
            notify: `${base}42-4150-b42d-22f30b0a0499`,
        };

        log(`Connecting Group ${gid}…`);

        device = await navigator.bluetooth.requestDevice({
            filters:          [{ services: [UUIDS.svc] }],
            optionalServices: [UUIDS.svc],
        });
        device.addEventListener('gattserverdisconnected', onDisconnect);

        server  = await device.gatt.connect();
        service = await server.getPrimaryService(UUIDS.svc);

        writeChar  = await service.getCharacteristic(UUIDS.write);
        notifyChar = await service.getCharacteristic(UUIDS.notify);
        await notifyChar.startNotifications();
        notifyChar.addEventListener('characteristicvaluechanged', handleControlData);

        document.getElementById('connStatus').innerText = "Connected";
        document.getElementById('statusDot').classList.add('active');
        document.getElementById('conBtn').disabled = true;
        document.getElementById('disBtn').disabled = false;

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

        const svg = document.getElementById('meshSvg');
        const w = svg ? svg.clientWidth  : 600;
        const h = svg ? svg.clientHeight : 400;
        meshNodes.set(meshMyId, {
            id: meshMyId, hops: 0, rssi: 0, snr: 0, msgCount: 0,
            x: w / 2, y: h / 2,
            vx: 0, vy: 0, lastSeen: Date.now()
        });
        meshD3Update();

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
    writeChar = null; notifyChar = null;
    log("Disconnected");
}

async function send(cmd) {
    if (!writeChar) return;
    const data = new TextEncoder().encode(cmd);
    try {
        if (writeChar.properties.writeWithoutResponse) await writeChar.writeValueWithoutResponse(data);
        else await writeChar.writeValue(data);
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

    if (msg.startsWith("MESH_RX:"))      { handleMeshRx(msg.substring(8)); return; }
    if (msg.startsWith("MESH_TX:"))      { handleMeshTx(msg.substring(8)); return; }
    if (msg.startsWith("MESH_INFO:"))    { handleMeshInfo(msg.substring(10)); return; }
    if (msg.startsWith("MESH_PING:"))    { log("♥ heartbeat " + msg.substring(10)); return; }
    if (msg.startsWith("MESH_ERR:"))     { log("Node error: " + msg.substring(9)); return; }
    if (msg.startsWith("MESH_PARROT:"))  { log("✓ BLE parrot OK → \"" + msg.substring(12) + "\""); return; }

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

// D3 state
let meshSim          = null;
let meshSvgRoot      = null;
let meshZoomTransform = d3.zoomIdentity;
let selectedDst      = 0;
let _serialPort      = null;
let _serialWriter    = null;
let _particleId      = 0;

function rssiColor(rssi) {
    if (rssi > -70) return '#30d158';
    if (rssi > -90) return '#ff9f0a';
    return '#ff453a';
}

function meshInit() {
    const svgEl = document.getElementById('meshSvg');
    if (!svgEl) return;

    const svg = d3.select('#meshSvg');
    const w   = svgEl.clientWidth  || 600;
    const h   = svgEl.clientHeight || 400;

    svg.attr('width', w).attr('height', h);

    // Defs: glow filters + dot pattern
    const defs = svg.append('defs');

    // Node glow filter
    const nodeGlow = defs.append('filter').attr('id', 'node-glow').attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
    nodeGlow.append('feGaussianBlur').attr('stdDeviation', '6').attr('result', 'coloredBlur');
    const nodeMerge = nodeGlow.append('feMerge');
    nodeMerge.append('feMergeNode').attr('in', 'coloredBlur');
    nodeMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Packet glow filter
    const pktGlow = defs.append('filter').attr('id', 'pkt-glow').attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
    pktGlow.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'coloredBlur');
    const pktMerge = pktGlow.append('feMerge');
    pktMerge.append('feMergeNode').attr('in', 'coloredBlur');
    pktMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Dot pattern
    const pattern = defs.append('pattern')
        .attr('id', 'mesh-bg-dots')
        .attr('width', 32).attr('height', 32)
        .attr('patternUnits', 'userSpaceOnUse');
    pattern.append('circle').attr('cx', 1).attr('cy', 1).attr('r', 1).attr('fill', 'rgba(255,255,255,0.04)');

    // Background rect
    svg.append('rect').attr('width', '100%').attr('height', '100%').attr('fill', 'url(#mesh-bg-dots)');

    // Zoom
    const zoom = d3.zoom()
        .scaleExtent([0.2, 4])
        .on('zoom', (event) => {
            meshZoomTransform = event.transform;
            if (meshSvgRoot) meshSvgRoot.attr('transform', event.transform);
        });
    svg.call(zoom);

    // Root group
    meshSvgRoot = svg.append('g');
    meshSvgRoot.append('g').attr('class', 'mesh-rings');
    meshSvgRoot.append('g').attr('class', 'mesh-links');
    meshSvgRoot.append('g').attr('class', 'mesh-particles');
    meshSvgRoot.append('g').attr('class', 'mesh-nodes');

    // Force simulation
    meshSim = d3.forceSimulation()
        .force('link', d3.forceLink().id(d => d.id).distance(170).strength(0.4))
        .force('charge', d3.forceManyBody().strength(-600))
        .force('center', d3.forceCenter(w / 2, h / 2))
        .force('collision', d3.forceCollide(42))
        .alphaDecay(0.025)
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

    // Build links array for D3
    const linksArr = [];
    meshLinks.forEach((link, key) => {
        const [aId, bId] = key.split('-').map(Number);
        linksArr.push({ source: aId, target: bId, rssi: link.rssi, lastActive: link.lastActive });
    });

    // Orbital rings
    const ringsG = meshSvgRoot.select('.mesh-rings');
    const ringRadii = [120, 200, 280];
    const ringsSel = ringsG.selectAll('circle.orbit-ring').data(ringRadii);
    ringsSel.enter().append('circle').attr('class', 'orbit-ring')
        .merge(ringsSel)
        .attr('cx', cx).attr('cy', cy)
        .attr('r', d => d)
        .attr('fill', 'none')
        .attr('stroke', (d, i) => `rgba(255,255,255,${0.04 - i * 0.01})`)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3,8');
    ringsSel.exit().remove();

    // Links
    const linksG  = meshSvgRoot.select('.mesh-links');
    const linkSel = linksG.selectAll('g.link-group').data(linksArr, d => `${d.source}-${d.target}`);

    const linkEnter = linkSel.enter().append('g').attr('class', 'link-group mesh-link');
    linkEnter.append('line');
    linkEnter.append('text')
        .attr('font-family', "'Inter', sans-serif")
        .attr('font-size', '10px')
        .attr('fill', 'rgba(255,255,255,0.5)')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle');

    const linkMerge = linkEnter.merge(linkSel);
    linkMerge.select('line')
        .attr('stroke', d => rssiColor(d.rssi || -100))
        .attr('stroke-width', d => (d.hops === 0 ? 2 : 1.5))
        .attr('stroke-opacity', d => (d.hops === 0 ? 0.7 : 0.35))
        .attr('stroke-dasharray', d => (d.hops === 0 ? null : '6,4'));
    linkMerge.select('text')
        .text(d => d.hops === 0 ? `${d.rssi} dBm` : `${d.hops}hop · ${d.rssi} dBm`);

    linkSel.exit().remove();

    // Nodes
    const nodesG   = meshSvgRoot.select('.mesh-nodes');
    const nodeSel  = nodesG.selectAll('g.mesh-node').data(nodesArr, d => d.id);

    const nodeEnter = nodeSel.enter().append('g').attr('class', 'mesh-node');

    // Glow circle (main)
    nodeEnter.append('circle').attr('class', 'node-circle');
    // Selection ring
    nodeEnter.append('circle').attr('class', 'selection-ring')
        .attr('fill', 'none')
        .attr('stroke', 'white')
        .attr('stroke-width', 2.5);
    // Label text
    nodeEnter.append('text').attr('class', 'node-label')
        .attr('font-family', "'Inter', sans-serif")
        .attr('font-weight', 'bold')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', 'white');
    // Sublabel
    nodeEnter.append('text').attr('class', 'node-sublabel')
        .attr('font-family', "'Inter', sans-serif")
        .attr('font-size', '10px')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', 'rgba(255,255,255,0.55)');

    // Drag behavior
    const drag = d3.drag()
        .on('start', (event, d) => {
            if (!event.active) meshSim.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => {
            d.fx = event.x; d.fy = event.y;
        })
        .on('end', (event, d) => {
            if (!event.active) meshSim.alphaTarget(0);
            // Release fx/fy unless it's the gateway
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

    // Merge enter + update
    const nodeMerge = nodeEnter.merge(nodeSel);

    nodeMerge.select('circle.node-circle')
        .attr('r', d => d.id === meshMyId ? 28 : 20)
        .attr('fill', d => d.id === meshMyId ? '#007aff' : rssiColor(d.rssi || -80))
        .attr('filter', 'url(#node-glow)');

    nodeMerge.select('circle.selection-ring')
        .attr('r', d => d.id === meshMyId ? 36 : 28)
        .attr('opacity', d => d.id === selectedDst ? 0.9 : 0);

    nodeMerge.select('text.node-label')
        .attr('font-size', d => d.id === meshMyId ? '14px' : '12px')
        .text(d => `N${d.id}`);

    nodeMerge.select('text.node-sublabel')
        .attr('dy', d => (d.id === meshMyId ? 28 : 20) + 14)
        .text(d => d.id === meshMyId ? 'YOU' : (d.hops === 0 ? 'direct' : `${d.hops}h`));

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
            .attr('r', 6)
            .attr('filter', 'url(#pkt-glow)');

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

function updateMeshDstSelect() {
    const sel = document.getElementById('meshDstSelect');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="0">→ All</option>';
    meshNodes.forEach(n => {
        if (n.id === meshMyId) return;
        const opt = document.createElement('option');
        opt.value = String(n.id);
        opt.textContent = `→ N${n.id}`;
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
    // data = "NODE_ID:<n>" — nRF tells us its actual mesh NODE_ID on BLE connect
    const match = data.match(/^NODE_ID:(\d+)$/);
    if (!match) return;
    const nodeId = parseInt(match[1]);
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
    document.getElementById('meshMyNodeId').innerText = `Node ${meshMyId}`;
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

    meshLinks.set(`${src}-${meshMyId}`, { rssi, snr, hops, lastActive: Date.now() });

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

// =============================================
// SERIAL (ESP32)
// =============================================
async function connectSerial() {
    if (!navigator.serial) { log('Web Serial requires Chrome 89+'); return; }
    try {
        _serialPort = await navigator.serial.requestPort();
        await _serialPort.open({ baudRate: 115200 });
        const enc = new TextEncoderStream();
        enc.readable.pipeTo(_serialPort.writable);
        _serialWriter = enc.writable.getWriter();
        document.getElementById('serialSendRow').style.display = 'flex';
        document.getElementById('serialBtn').textContent = 'Disconnect Serial';
        document.getElementById('serialBtn').onclick = disconnectSerial;
        log('ESP32 serial connected');
    } catch (e) {
        if (e.name !== 'NotFoundError') log('Serial error: ' + e.message);
    }
}

async function disconnectSerial() {
    try {
        if (_serialWriter) { await _serialWriter.close(); _serialWriter = null; }
        if (_serialPort)   { await _serialPort.close();  _serialPort   = null; }
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
// FIRMWARE FLASH
// =============================================
async function flashDevice(board) {
    if (!window.showDirectoryPicker) {
        log('Flash requires Chrome 86+ with File System Access API.');
        return;
    }

    const nodeId   = parseInt(document.getElementById('flashNodeId').value) || 1;
    const label    = board === 'nrf' ? 'nRF52840' : 'ESP32-S3';
    const srcFile  = board === 'nrf' ? 'code_nrf.py' : 'code_esp32.py';
    const btns     = document.querySelectorAll('.btn-flash');
    btns.forEach(b => b.classList.add('flashing'));

    try {
        // Fetch bundled source code (same repo, one level up)
        log(`[Flash ${label}] Loading firmware (Node ID = ${nodeId})…`);
        const resp = await fetch(srcFile);
        if (!resp.ok) throw new Error(`Could not load ${srcFile} (${resp.status})`);
        let content = await resp.text();

        // Inject the chosen NODE_ID
        content = content.replace(/^NODE_ID\s*=\s*\d+/m, `NODE_ID   = ${nodeId}`);

        // Pick the destination CIRCUITPY drive root
        log(`[Flash ${label}] Select the CIRCUITPY drive…`);
        const destDir = await window.showDirectoryPicker({
            id: 'circuitpy-' + board,
            mode: 'readwrite',
        });

        // Write as code.py
        const destHandle = await destDir.getFileHandle('code.py', { create: true });
        const writable   = await destHandle.createWritable();
        await writable.write(content);
        await writable.close();

        log(`✓ ${label} (Node ${nodeId}) → ${destDir.name}/code.py  (board will restart)`);
    } catch (e) {
        if (e.name !== 'AbortError') log(`Flash error: ${e.message}`);
    } finally {
        btns.forEach(b => b.classList.remove('flashing'));
    }
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
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    meshInit();

    window.addEventListener('resize', () => {
        if (loraGraphData.length > 0) drawLoraRssiChart();
        meshResize();
    });
});
