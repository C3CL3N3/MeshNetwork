/* ═══════════════════════════════════════════════════════════
   LORA COMMAND SYSTEM — rover actions + parameterised commands
   ═══════════════════════════════════════════════════════════ */
const ACTION = {
  FORWARD:    'FORWARD',
  BACKWARD:   'BACKWARD',
  TURN_LEFT:  'TURN_LEFT',
  TURN_RIGHT: 'TURN_RIGHT',
  STOP:       'STOP',
  SPEED_UP:   'SPEED_UP',
  SPEED_DOWN: 'SPEED_DOWN',
  SET_HEADING:'SET_HEADING',
  SET_SPEED:  'SET_SPEED',
  FWD_MS:     'FWD_MS',
  BACK_MS:    'BACK_MS',
};

// Simple commands: payload maps directly to action
const SIMPLE_MAP = {
  "F": "FORWARD", "B": "BACKWARD", "L": "TURN_LEFT", "R": "TURN_RIGHT",
  "S": "STOP", "+": "SPEED_UP", "-": "SPEED_DOWN",
  "FWRD": "FORWARD", "BACK": "BACKWARD", "LEFT": "TURN_LEFT",
  "RGHT": "TURN_RIGHT", "STOP": "STOP",
  "FORWARD": "FORWARD", "BACKWARD": "BACKWARD",
  "TURN_LEFT": "TURN_LEFT", "TURN_RIGHT": "TURN_RIGHT"
};

// Parameterised command prefix → action + param parser
// Format: PREFIX:NUMBER  e.g. H:90  V:3.0  F:500  B:300
const PARAM_MAP = {
  "H:": { action: "SET_HEADING", parse: v => parseFloat(v) },
  "V:": { action: "SET_SPEED",   parse: v => parseFloat(v) },
  "F:": { action: "FWD_MS",      parse: v => Math.max(0, parseInt(v)) },
  "B:": { action: "BACK_MS",     parse: v => Math.max(0, parseInt(v)) },
  "HEADING:": { action: "SET_HEADING", parse: v => parseFloat(v) },
  "SPEED:":   { action: "SET_SPEED",   parse: v => parseFloat(v) },
  "FWD:":     { action: "FWD_MS",      parse: v => Math.max(0, parseInt(v)) },
  "BACK:":    { action: "BACK_MS",     parse: v => Math.max(0, parseInt(v)) },
};

function extractLoraPayload(raw) {
  let m = raw.match(/DELIVER.*'([^']*)'/i);
  if (m) return m[1].trim().toUpperCase();
  m = raw.match(/RX\s+D\s+.*'([^']*)'/i);
  if (m) return m[1].trim().toUpperCase();
  if (raw.trim().startsWith('D:')) {
    const parts = raw.trim().split(':');
    if (parts.length >= 7) return parts.slice(6).join(':').trim().toUpperCase();
  }
  return null;
}

function resolveLoraAction(raw) {
  const payload = extractLoraPayload(raw) || raw.trim().toUpperCase();
  // Simple command lookup
  if (SIMPLE_MAP[payload]) return { action: SIMPLE_MAP[payload] };
  // Parameterised command: H:90  V:3.0  F:500  B:300  HEADING:90  etc.
  for (const [prefix, def] of Object.entries(PARAM_MAP)) {
    if (payload.startsWith(prefix)) {
      const val = payload.slice(prefix.length);
      const param = def.parse(val);
      if (!isNaN(param)) return { action: def.action, param };
    }
  }
  return null;
}

/* ── Robot ─────────────────────────────────────────────────── */
const canvas = document.getElementById('canvas');
const ctx    = canvas.getContext('2d');
const W = canvas.width, H = canvas.height;

const BASE_SPEED  = 2.5;
const TURN_RATE   = 0.035;
const SPEED_STEP  = 0.5;
const SPEED_MIN   = 0.5;
const SPEED_MAX   = 6;
const TRAIL_MAX   = 400;

const rover = {
  x: W / 2, y: H / 2,
  angle: -Math.PI / 2,
  speed: BASE_SPEED,
  state: ACTION.STOP,
  trail: [],
  wfl: 0, wfr: 0, wbl: 0, wbr: 0,
};

function roverReset() {
  rover.x = W / 2; rover.y = H / 2;
  rover.angle = -Math.PI / 2;
  rover.speed = BASE_SPEED;
  rover.state = ACTION.STOP;
  rover.trail = [];
  rover.wfl = rover.wfr = rover.wbl = rover.wbr = 0;
}

let _timedActionEnd = 0;
let _timedActionState = null;

function applyAction(action, param) {
  if (!action) return;
  clearTimeout(loraTimer);
  rover.state = action;
  if (action === ACTION.SPEED_UP)   rover.speed = Math.min(rover.speed + SPEED_STEP, SPEED_MAX);
  if (action === ACTION.SPEED_DOWN) rover.speed = Math.max(rover.speed - SPEED_STEP, SPEED_MIN);
  if (action === ACTION.SET_HEADING && param != null) {
    // Control/dashboard bearings use compass convention:
    // 0=N, 90=E, 180=S, 270=W.
    // The canvas physics uses radians where 0=E and -90deg=N.
    rover.angle = (param - 90) * Math.PI / 180;
  }
  if (action === ACTION.SET_SPEED   && param != null) rover.speed = Math.max(SPEED_MIN, Math.min(SPEED_MAX, param));
  if (action === ACTION.FWD_MS  && param > 0) { _timedActionEnd = Date.now() + param; _timedActionState = ACTION.FORWARD;  rover.state = ACTION.FORWARD; console.log('FWD_MS start, end=', _timedActionEnd, 'state=', rover.state); }
  if (action === ACTION.BACK_MS && param > 0) { _timedActionEnd = Date.now() + param; _timedActionState = ACTION.BACKWARD; rover.state = ACTION.BACKWARD; console.log('BACK_MS start, end=', _timedActionEnd, 'state=', rover.state); }
}

function releaseAction(action) {
  if (rover.state === action) rover.state = ACTION.STOP;
}

const HOLD = new Set([ACTION.FORWARD, ACTION.BACKWARD, ACTION.TURN_LEFT, ACTION.TURN_RIGHT]);

function update() {
  // Timed movement auto-stop
  if (_timedActionEnd && Date.now() >= _timedActionEnd) {
    _timedActionEnd = 0; _timedActionState = null;
    rover.state = ACTION.STOP;
  }
  let moved = false;
  switch (rover.state) {
    case ACTION.FORWARD:
      rover.x += Math.cos(rover.angle) * rover.speed;
      rover.y += Math.sin(rover.angle) * rover.speed;
      moved = true; break;
    case ACTION.BACKWARD:
      rover.x -= Math.cos(rover.angle) * rover.speed;
      rover.y -= Math.sin(rover.angle) * rover.speed;
      moved = true; break;
    case ACTION.TURN_LEFT:  rover.angle -= TURN_RATE; break;
    case ACTION.TURN_RIGHT: rover.angle += TURN_RATE; break;
  }

  if (rover.x < 0) rover.x = W; if (rover.x > W) rover.x = 0;
  if (rover.y < 0) rover.y = H; if (rover.y > H) rover.y = 0;

  const s = (rover.speed / BASE_SPEED) * 0.08;
  if (moved) {
    const d = rover.state === ACTION.BACKWARD ? -s : s;
    rover.wfl += d; rover.wfr += d; rover.wbl += d; rover.wbr += d;
  }
  if (rover.state === ACTION.TURN_LEFT)  { rover.wfl -= 0.05; rover.wbl -= 0.05; rover.wfr += 0.05; rover.wbr += 0.05; }
  if (rover.state === ACTION.TURN_RIGHT) { rover.wfl += 0.05; rover.wbl += 0.05; rover.wfr -= 0.05; rover.wbr -= 0.05; }

  if (moved) {
    rover.trail.push({ x: rover.x, y: rover.y });
    if (rover.trail.length > TRAIL_MAX) rover.trail.shift();
  }
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawWheel(x, y, spin) {
  const WW = 8, WH = 15;
  ctx.save();
  ctx.translate(x, y);
  roundRect(-WW/2, -WH/2, WW, WH, 2);
  ctx.fillStyle = '#1a1a2e'; ctx.fill();
  ctx.strokeStyle = '#444'; ctx.lineWidth = 1; ctx.stroke();
  ctx.strokeStyle = '#2a2a4e'; ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const ty = -WH/2 + (((i / 5) + spin) % 1) * WH;
    ctx.beginPath(); ctx.moveTo(-WW/2 + 1, ty); ctx.lineTo(WW/2 - 1, ty); ctx.stroke();
  }
  ctx.restore();
}

function drawRover() {
  const BW = 38, BH = 30;
  const t = Date.now() / 500;

  roundRect(-BW/2, -BH/2, BW, BH, 5);
  ctx.fillStyle = '#1d3557'; ctx.fill();
  ctx.strokeStyle = '#457b9d'; ctx.lineWidth = 1.5; ctx.stroke();

  ctx.strokeStyle = '#2a5580'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(-BW/2 + 6, -BH/2 + 4); ctx.lineTo(BW/2 - 8, -BH/2 + 4); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(-BW/2 + 6,  BH/2 - 4); ctx.lineTo(BW/2 - 8,  BH/2 - 4); ctx.stroke();

  ctx.beginPath(); ctx.arc(BW/2 - 7, 0, 6, 0, Math.PI * 2);
  ctx.fillStyle = '#0a0a1a'; ctx.fill();
  ctx.strokeStyle = '#00e5ff'; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.beginPath(); ctx.arc(BW/2 - 7, 0, 3, 0, Math.PI * 2);
  ctx.fillStyle = '#00b4d8'; ctx.fill();

  ctx.strokeStyle = '#aaa'; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(-BW/2 + 5, -BH/2); ctx.lineTo(-BW/2 + 5, -BH/2 - 12); ctx.stroke();
  ctx.beginPath(); ctx.arc(-BW/2 + 5, -BH/2 - 13, 2.5, 0, Math.PI * 2);
  ctx.fillStyle = rover.state !== ACTION.STOP ? '#ff6b35' : '#555'; ctx.fill();

  if (rover.state !== ACTION.STOP) {
    const ax = -BW/2 + 5, ay = -BH/2 - 13;
    for (let r = 0; r < 3; r++) {
      const phase = ((t + r * 0.33) % 1);
      const radius = 8 + phase * 22;
      const alpha  = (1 - phase) * 0.6;
      ctx.beginPath(); ctx.arc(ax, ay, radius, -Math.PI * 0.8, -Math.PI * 0.2);
      ctx.strokeStyle = `rgba(255,107,53,${alpha.toFixed(2)})`;
      ctx.lineWidth = 1.5; ctx.stroke();
    }
  }

  ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(-4, 0); ctx.lineTo(BW/2 - 13, 0); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(BW/2 - 13, 0); ctx.lineTo(BW/2 - 19, -4);
  ctx.moveTo(BW/2 - 13, 0); ctx.lineTo(BW/2 - 19,  4);
  ctx.stroke();

  drawWheel(-BW/2,  -BH/2 - 1, rover.wfl);
  drawWheel( BW/2,  -BH/2 - 1, rover.wfr);
  drawWheel(-BW/2,   BH/2 - 7, rover.wbl);
  drawWheel( BW/2,   BH/2 - 7, rover.wbr);
}

function draw() {
  ctx.fillStyle = '#0d1117';
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = '#1e2733'; ctx.lineWidth = 1;
  for (let x = 0; x <= W; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 0; y <= H; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

  if (rover.trail.length > 1) {
    ctx.beginPath();
    ctx.moveTo(rover.trail[0].x, rover.trail[0].y);
    for (let i = 1; i < rover.trail.length; i++) ctx.lineTo(rover.trail[i].x, rover.trail[i].y);
    ctx.strokeStyle = 'rgba(0,180,130,0.3)'; ctx.lineWidth = 2; ctx.stroke();
  }

  ctx.save();
  ctx.translate(rover.x, rover.y);
  ctx.rotate(rover.angle);
  drawRover();
  ctx.restore();

  const barW = 120, barH = 8;
  const bx = W - barW - 12, by = H - 22;
  ctx.fillStyle = '#161b22';
  roundRect(bx, by, barW, barH, 4); ctx.fill();
  const fill = ((rover.speed - SPEED_MIN) / (SPEED_MAX - SPEED_MIN)) * barW;
  ctx.fillStyle = rover.speed > 4 ? '#f85149' : rover.speed > 2 ? '#d29922' : '#3fb950';
  roundRect(bx, by, fill, barH, 4); ctx.fill();
  ctx.fillStyle = '#8b949e'; ctx.font = '9px monospace';
  ctx.fillText(`SPD ${rover.speed.toFixed(1)}`, bx, by - 4);
}

/* ── Game loop ─────────────────────────────────────────────── */
function loop() {
  update();
  draw();
  updateHUD();
  requestAnimationFrame(loop);
}

function updateHUD() {
  document.getElementById('st-action').textContent = rover.state;
  document.getElementById('st-speed').textContent  = rover.speed.toFixed(1);
  document.getElementById('st-x').textContent      = Math.round(rover.x);
  document.getElementById('st-y').textContent      = Math.round(rover.y);
  const compassDeg = ((((rover.angle * 180 / Math.PI) + 90) % 360) + 360) % 360;
  document.getElementById('st-angle').textContent  = Math.round(compassDeg) + '°';
}

/* ── Keyboard ──────────────────────────────────────────────── */
const KB_ACTION = {
  KeyW: ACTION.FORWARD,    ArrowUp:    ACTION.FORWARD,
  KeyS: ACTION.BACKWARD,   ArrowDown:  ACTION.BACKWARD,
  KeyA: ACTION.TURN_LEFT,  ArrowLeft:  ACTION.TURN_LEFT,
  KeyD: ACTION.TURN_RIGHT, ArrowRight: ACTION.TURN_RIGHT,
  Space: ACTION.STOP,
  Equal: ACTION.SPEED_UP,      NumpadAdd:      ACTION.SPEED_UP,
  Minus: ACTION.SPEED_DOWN,    NumpadSubtract: ACTION.SPEED_DOWN,
};

const KB_EL = {
  KeyW: 'key-w',   ArrowUp:    'key-w',
  KeyS: 'key-s',   ArrowDown:  'key-s',
  KeyA: 'key-a',   ArrowLeft:  'key-a',
  KeyD: 'key-d',   ArrowRight: 'key-d',
  Space: 'key-space',
};

let loraActive = false, loraTimer = null;
let source = 'KB';

function setSource(s) { source = s; document.getElementById('st-source').textContent = s; }

[window, canvas].forEach(el => {
  el.addEventListener('keydown', e => {
    if (e.code === 'KeyR') { roverReset(); return; }
    const action = KB_ACTION[e.code];
    if (!action || e.repeat) return;
    e.preventDefault();
    if (loraActive) return;
    setSource('KB');
    applyAction(action);
    const elId = KB_EL[e.code];
    if (elId) document.getElementById(elId)?.classList.add('active');
  });

  el.addEventListener('keyup', e => {
    const action = KB_ACTION[e.code];
    if (!action) return;
    if (!loraActive && HOLD.has(action)) releaseAction(action);
    const elId = KB_EL[e.code];
    if (elId) document.getElementById(elId)?.classList.remove('active');
  });
});

canvas.addEventListener('click', () => canvas.focus());
canvas.focus();

/* ── LoRa / Serial ─────────────────────────────────────────── */
const logEl = document.getElementById('serial-log');
function serialLog(msg, color) {
  const line = document.createElement('div');
  line.textContent = msg;
  if (color) line.style.color = color;
  logEl.appendChild(line);
  if (logEl.children.length > 80) logEl.removeChild(logEl.firstChild);
  logEl.scrollTop = logEl.scrollHeight;
}

function handleLoraAction(result) {
  if (!result || !result.action) return;
  setSource('LORA');
  loraActive = true;
  applyAction(result.action, result.param);
  // Timed moves (FWD_MS, BACK_MS) have built-in stop — don't override
  if (result.action === ACTION.FWD_MS || result.action === ACTION.BACK_MS) {
    loraActive = false;  // keyboard returns after timed move completes
    return;
  }
  if (HOLD.has(result.action)) {
    loraTimer = setTimeout(() => {
      loraActive = false;
      applyAction(ACTION.STOP);
      setSource('KB');
    }, 1000);
  } else {
    loraActive = false;
  }
}

class LineTransformer {
  constructor() { this.buf = ''; }
  transform(chunk, ctrl) {
    this.buf += chunk;
    const lines = this.buf.split('\n');
    this.buf = lines.pop();
    lines.forEach(l => ctrl.enqueue(l));
  }
  flush(ctrl) { if (this.buf) ctrl.enqueue(this.buf); }
}

let serialPort = null, serialReader = null, serialActive = false;

async function serialConnect() {
  if (!('serial' in navigator)) { serialLog('Web Serial not supported (use Chrome/Edge)', '#f85149'); return; }
  try {
    serialPort = await navigator.serial.requestPort();
    await serialPort.open({ baudRate: 115200 });
    serialActive = true;
    serialLog('Connected at 115200 baud', '#3fb950');
    document.getElementById('btn-connect').disabled    = true;
    document.getElementById('btn-disconnect').disabled = false;

    const decoder = new TextDecoderStream();
    serialPort.readable.pipeTo(decoder.writable);
    const lineStream = decoder.readable.pipeThrough(new TransformStream(new LineTransformer()));
    serialReader = lineStream.getReader();

    while (serialActive) {
      const { value, done } = await serialReader.read();
      if (done) break;
      const raw = value.trim();
      if (!raw) continue;
      serialLog(`RX: ${raw}`, '#58a6ff');
      const result = resolveLoraAction(raw);
      if (result) {
        const label = result.param != null ? result.action + '(' + result.param + ')' : result.action;
        serialLog('→ ' + label, '#ff6b35');
        try { handleLoraAction(result); } catch(e) { serialLog('Error: ' + e.message, '#f85149'); }
      } else {
        serialLog(`→ unknown`, '#8b949e');
      }
    }
  } catch (e) {
    serialLog(`Error: ${e.message}`, '#f85149');
    document.getElementById('btn-connect').disabled    = false;
    document.getElementById('btn-disconnect').disabled = true;
  }
}

async function serialDisconnect() {
  serialActive = false;
  if (serialReader) { try { await serialReader.cancel(); } catch(_){} }
  if (serialPort)   { try { await serialPort.close();   } catch(_){} }
  loraActive = false; setSource('KB');
  serialLog('Disconnected', '#8b949e');
  document.getElementById('btn-connect').disabled    = false;
  document.getElementById('btn-disconnect').disabled = true;
}

document.getElementById('btn-connect').addEventListener('click', serialConnect);
document.getElementById('btn-disconnect').addEventListener('click', serialDisconnect);
document.getElementById('btn-reset').addEventListener('click', roverReset);

/* ── Start ─────────────────────────────────────────────────── */
loop();
