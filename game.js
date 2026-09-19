/* Path Patrol — a compact, canvas-based homage to early feature-phone territory games. */
(() => {
  'use strict';

  const GRID_W = 120;
  const GRID_H = 72;
  const WALL = 1;
  const FIELD = 0;
  const BORDER = 2;
  const STORAGE_KEY = 'color-divide-records-v1';
  const $ = (id) => document.getElementById(id);
  const canvas = $('gameCanvas');
  const ctx = canvas.getContext('2d', { alpha: false });

  const ui = {
    start: $('startButton'), startOverlay: $('startOverlay'), pause: $('pauseButton'), pauseOverlay: $('pauseOverlay'), resume: $('resumeButton'),
    restart: $('restartButton'), sound: $('soundButton'), flight: $('flightButton'), drive: $('driveButton'),
    level: $('levelLabel'), lives: $('lives'), target: $('targetLabel'), area: $('areaLabel'), progress: $('progressFill'), targetMarker: $('targetMarker'),
    runners: $('runnerLabel'), toast: $('toast'), bestClear: $('bestClear'), bestLevel: $('bestLevel'), runs: $('runsPlayed'), wins: $('levelsWon'), resetStats: $('resetStatsButton')
  };

  const palettes = [
    ['#147a79', '#20a998', '#75f0cd'], ['#174f90', '#287bd0', '#7bc5ff'], ['#742e75', '#b24aa4', '#ffb5e9'],
    ['#865126', '#d88435', '#ffd681'], ['#784234', '#bd584b', '#ffad8c'], ['#315c48', '#52a173', '#b9f1bd']
  ];
  const drivePalettes = [
    ['#526d62', '#7f9c7d', '#d9d88d'], ['#546979', '#8299a1', '#d8c799'], ['#735d67', '#a67e80', '#e0bc91'],
    ['#6d604e', '#9d895a', '#e3c978'], ['#4e6471', '#71969a', '#cad6a1'], ['#625967', '#927b91', '#e2c4ba']
  ];
  const sprites = { flight: new Image(), drive: new Image() };
  sprites.flight.src = 'assets/plane.svg';
  sprites.drive.src = 'assets/car.svg';
  const state = {
    grid: new Uint8Array(GRID_W * GRID_H), balls: [], cut: null, level: 1, target: 65, lives: 3,
    cleared: 0, initialPlayable: 0, running: false, paused: false, lastTime: 0, obstacles: [], routes: [], aim: null,
    sound: true, hasStarted: false, flash: 0, palette: palettes[0], theme: 'flight', status: 'start'
  };
  let stats = readStats();
  state.theme = stats.theme === 'drive' ? 'drive' : 'flight';
  let toastTimer = 0;
  let audioContext;

  function readStats() {
    try { return { bestClear: 0, bestLevel: 0, runs: 0, wins: 0, theme: 'flight', ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') }; }
    catch { return { bestClear: 0, bestLevel: 0, runs: 0, wins: 0, theme: 'flight' }; }
  }
  function saveStats() { localStorage.setItem(STORAGE_KEY, JSON.stringify(stats)); updateStats(); }
  function updateStats() {
    ui.bestClear.textContent = `${stats.bestClear.toFixed(1)}%`;
    ui.bestLevel.textContent = stats.bestLevel ? String(stats.bestLevel).padStart(2, '0') : '—';
    ui.runs.textContent = String(stats.runs);
    ui.wins.textContent = String(stats.wins);
  }

  function index(x, y) { return y * GRID_W + x; }
  function inGrid(x, y) { return x >= 0 && x < GRID_W && y >= 0 && y < GRID_H; }
  function solid(x, y) { return !inGrid(x, y) || state.grid[index(x, y)] !== FIELD; }
  function setSolid(x, y, value = WALL) { if (inGrid(x, y)) state.grid[index(x, y)] = value; }
  function levelInfo(level) {
    return {
      balls: Math.min(6, 1 + Math.floor((level - 1) / 2)),
      speed: 14 + (level - 1) * 2.25,
      target: Math.min(70, 65 + Math.floor((level - 1) / 2) * 2),
      obstacles: Math.min(5, Math.floor((level - 1) / 2))
    };
  }
  function random(min, max) { return min + Math.random() * (max - min); }
  function paletteFor(level) { const collection = state.theme === 'drive' ? drivePalettes : palettes; return collection[(level - 1) % collection.length]; }

  function startLevel(level, newRun = false) {
    const info = levelInfo(level);
    state.level = level; state.target = info.target; state.lives = newRun ? 3 : state.lives;
    state.grid.fill(FIELD); state.balls = []; state.cut = null; state.routes = []; state.obstacles = []; state.aim = null;
    state.cleared = 0; state.palette = paletteFor(level); state.flash = 0;
    for (let y = 0; y < GRID_H; y++) for (let x = 0; x < GRID_W; x++) {
      if (x < 2 || y < 2 || x >= GRID_W - 2 || y >= GRID_H - 2) setSolid(x, y, BORDER);
    }
    placeObstacles(info.obstacles);
    state.initialPlayable = countFields();
    placeBalls(info.balls, info.speed);
    state.running = true; state.paused = false; state.status = 'playing'; state.lastTime = performance.now();
    ui.pause.textContent = 'Pause'; ui.pause.append(key('P'));
    ui.pauseOverlay.classList.add('hidden'); ui.startOverlay.classList.add('hidden');
    updateHud(); toast(`Level ${String(level).padStart(2, '0')} · clear ${state.target}%`, 1400);
  }

  function placeObstacles(quantity) {
    for (let attempt = 0, made = 0; made < quantity && attempt < 100; attempt++) {
      const w = Math.floor(random(4, 9)); const h = Math.floor(random(3, 6));
      const x = Math.floor(random(14, GRID_W - w - 14)); const y = Math.floor(random(12, GRID_H - h - 12));
      let clear = true;
      for (let yy = y - 3; yy < y + h + 3 && clear; yy++) for (let xx = x - 3; xx < x + w + 3; xx++) if (solid(xx, yy)) { clear = false; break; }
      if (!clear) continue;
      for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) setSolid(xx, yy, BORDER);
      state.obstacles.push({ x, y, w, h });
      made++;
    }
  }
  function placeBalls(quantity, speed) {
    for (let i = 0; i < quantity; i++) {
      let x, y, safe = false;
      for (let tries = 0; tries < 300 && !safe; tries++) {
        x = random(5, GRID_W - 5); y = random(5, GRID_H - 5); safe = !circleHitsWall(x, y, 2.2) && state.balls.every(b => Math.hypot(b.x - x, b.y - y) > 8);
      }
      const angle = random(0.22, Math.PI * 2 - .22);
      state.balls.push({ x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed, r: 1.35, hue: i % 2 ? '#ffb86c' : '#ff765f', trail: [] });
    }
  }
  function countFields() { let n = 0; for (const cell of state.grid) if (cell === FIELD) n++; return n; }

  function circleHitsWall(cx, cy, radius) {
    const minX = Math.floor(cx - radius), maxX = Math.ceil(cx + radius);
    const minY = Math.floor(cy - radius), maxY = Math.ceil(cy + radius);
    for (let y = minY; y <= maxY; y++) for (let x = minX; x <= maxX; x++) {
      if (!solid(x, y)) continue;
      const closeX = Math.max(x, Math.min(cx, x + 1)); const closeY = Math.max(y, Math.min(cy, y + 1));
      if ((cx - closeX) ** 2 + (cy - closeY) ** 2 < radius ** 2) return true;
    }
    return false;
  }

  function update(dt) {
    if (!state.running || state.paused) return;
    state.flash = Math.max(0, state.flash - dt);
    if (state.cut) updateCut(dt);
    for (const ball of state.balls) moveBall(ball, dt);
  }

  function moveBall(ball, dt) {
    const distance = Math.hypot(ball.vx, ball.vy) * dt;
    const steps = Math.max(1, Math.ceil(distance / .38)); const step = dt / steps;
    for (let i = 0; i < steps; i++) {
      const nx = ball.x + ball.vx * step;
      if (circleHitsWall(nx, ball.y, ball.r)) ball.vx *= -1; else ball.x = nx;
      const ny = ball.y + ball.vy * step;
      if (circleHitsWall(ball.x, ny, ball.r)) ball.vy *= -1; else ball.y = ny;
      if (state.cut && cutTouchesBall(state.cut, ball)) { failCut(); return; }
    }
    ball.trail.unshift({ x: ball.x, y: ball.y }); if (ball.trail.length > 9) ball.trail.pop();
  }

  function makeCut(from, to) {
    if (!state.running || state.paused || state.cut || state.status !== 'playing') return;
    const x = Math.floor(from.x) + .5, y = Math.floor(from.y) + .5;
    const vx = to.x - from.x, vy = to.y - from.y, length = Math.hypot(vx, vy);
    if (!inGrid(Math.floor(x), Math.floor(y)) || solid(Math.floor(x), Math.floor(y))) { toast('Start inside the colour field', 1000); return; }
    if (length < 2.5) { toast('Drag farther to set a route', 900); return; }
    const dx = vx / length, dy = vy / length;
    const line = getCutLimits(x, y, dx, dy);
    if (!line || line.negativeMax < 1 || line.positiveMax < 1) { toast('No route through this point', 1000); return; }
    state.cut = { x, y, dx, dy, negative: 0, positive: 0, ...line, speed: 39 };
    chirp(440, .045, 'triangle');
  }
  function getCutLimits(x, y, dx, dy) {
    return { negativeMax: rayToWall(x, y, -dx, -dy), positiveMax: rayToWall(x, y, dx, dy) };
  }
  function rayToWall(x, y, dx, dy) {
    const step = .16;
    for (let distance = step; distance < 180; distance += step) {
      if (solid(Math.floor(x + dx * distance), Math.floor(y + dy * distance))) return Math.max(.55, distance - step * .25);
    }
    return 0;
  }
  function updateCut(dt) {
    const c = state.cut;
    c.negative = Math.min(c.negativeMax, c.negative + c.speed * dt);
    c.positive = Math.min(c.positiveMax, c.positive + c.speed * dt);
    if (c.negative >= c.negativeMax && c.positive >= c.positiveMax) completeCut();
  }
  function cutTouchesBall(c, ball) {
    const x1 = c.x - c.dx * c.negative, y1 = c.y - c.dy * c.negative;
    const x2 = c.x + c.dx * c.positive, y2 = c.y + c.dy * c.positive;
    return distanceToSegment(ball.x, ball.y, x1, y1, x2, y2) < ball.r + .66;
  }
  function completeCut() {
    const c = state.cut; state.cut = null;
    rasterizeCut(c); state.routes.push({ ...c });
    const before = countFields(); captureBallFreeAreas();
    const now = countFields(); const removed = before - now; state.cleared = ((state.initialPlayable - now) / state.initialPlayable) * 100;
    stats.bestClear = Math.max(stats.bestClear, state.cleared); saveStats(); updateHud(); chirp(780, .09, 'sine');
    toast(`${removed} cells cleared · ${state.cleared.toFixed(1)}%`, 1100);
    if (state.cleared >= state.target) setTimeout(finishLevel, 550);
  }
  function distanceToSegment(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1, lengthSq = dx * dx + dy * dy;
    if (!lengthSq) return Math.hypot(px - x1, py - y1);
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lengthSq));
    return Math.hypot(px - (x1 + dx * t), py - (y1 + dy * t));
  }
  function rasterizeCut(c) {
    for (let distance = -c.negative; distance <= c.positive; distance += .18) stampSolid(c.x + c.dx * distance, c.y + c.dy * distance);
    stampSolid(c.x - c.dx * c.negative, c.y - c.dy * c.negative);
    stampSolid(c.x + c.dx * c.positive, c.y + c.dy * c.positive);
  }
  function stampSolid(x, y) {
    for (let yy = Math.floor(y - .76); yy <= Math.ceil(y + .76); yy++) for (let xx = Math.floor(x - .76); xx <= Math.ceil(x + .76); xx++) {
      if (Math.hypot(xx + .5 - x, yy + .5 - y) <= .78) setSolid(xx, yy);
    }
  }
  function captureBallFreeAreas() {
    const reachable = new Uint8Array(GRID_W * GRID_H); const queue = [];
    for (const b of state.balls) {
      const x = Math.floor(b.x), y = Math.floor(b.y), i = index(x, y);
      if (state.grid[i] === FIELD && !reachable[i]) { reachable[i] = 1; queue.push(i); }
    }
    for (let head = 0; head < queue.length; head++) {
      const current = queue[head], x = current % GRID_W, y = Math.floor(current / GRID_W);
      for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) {
        const nx = x + dx, ny = y + dy, ni = index(nx, ny);
        if (inGrid(nx, ny) && state.grid[ni] === FIELD && !reachable[ni]) { reachable[ni] = 1; queue.push(ni); }
      }
    }
    for (let i = 0; i < state.grid.length; i++) if (state.grid[i] === FIELD && !reachable[i]) state.grid[i] = WALL;
  }
  function failCut() {
    if (!state.cut) return;
    state.cut = null; state.lives--; state.flash = .34; chirp(110, .16, 'sawtooth'); updateHud();
    if (state.lives > 0) toast('Cut intercepted — try again', 1200);
    else { state.running = false; state.status = 'over'; saveStats(); showEnd(false); }
  }
  function finishLevel() {
    if (!state.running || state.status !== 'playing') return;
    state.running = false; state.status = 'won'; stats.wins++; stats.bestLevel = Math.max(stats.bestLevel, state.level); saveStats(); chirp(660, .11, 'sine');
    setTimeout(() => startLevel(state.level + 1), 700);
  }
  function showEnd(won) {
    const title = won ? 'Field secured.' : 'Run interrupted.';
    ui.startOverlay.innerHTML = `<div class="start-symbol" aria-hidden="true"><span></span><span></span></div><span class="eyebrow">${won ? 'Level complete' : 'No lives left'}</span><h1>${title}</h1><p>Highest cleared area: ${stats.bestClear.toFixed(1)}%. Start fresh and find a cleaner line.</p><button type="button" class="primary-button" id="againButton">New run <span>→</span></button><small>Local records are kept on this device.</small>`;
    ui.startOverlay.classList.remove('hidden'); $('againButton').addEventListener('click', () => startNewRun());
  }
  function startNewRun() {
    stats.runs++; saveStats(); state.hasStarted = true; startLevel(1, true);
  }
  function updateHud() {
    ui.level.textContent = String(state.level).padStart(2, '0'); ui.target.textContent = `${state.target}%`;
    ui.area.textContent = `${state.cleared.toFixed(1)}%`; ui.progress.style.width = `${Math.min(100, state.cleared)}%`;
    const patrol = state.theme === 'flight' ? 'PLANE' : 'CAR';
    ui.targetMarker.style.left = `${state.target}%`; ui.runners.textContent = `${state.balls.length} ${patrol}${state.balls.length === 1 ? '' : 'S'}`;
    ui.lives.innerHTML = Array.from({ length: 3 }, (_, i) => `<i class="life ${i >= state.lives ? 'lost' : ''}"></i>`).join('');
  }
  function key(label) { const node = document.createElement('kbd'); node.textContent = label; return node; }
  function setTheme(value) {
    state.theme = value === 'drive' ? 'drive' : 'flight'; stats.theme = state.theme; state.palette = paletteFor(state.level); saveStats(); updateHud();
    syncThemeUi();
    toast(state.theme === 'flight' ? 'Flight visuals enabled' : 'Drive visuals enabled', 900);
  }
  function syncThemeUi() {
    ui.flight.classList.toggle('active', state.theme === 'flight'); ui.drive.classList.toggle('active', state.theme === 'drive');
    ui.flight.setAttribute('aria-pressed', String(state.theme === 'flight')); ui.drive.setAttribute('aria-pressed', String(state.theme === 'drive'));
  }
  function toast(message, duration = 1200) { clearTimeout(toastTimer); ui.toast.textContent = message; ui.toast.classList.add('visible'); toastTimer = setTimeout(() => ui.toast.classList.remove('visible'), duration); }

  function draw() {
    const sx = canvas.width / GRID_W, sy = canvas.height / GRID_H;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = '#0b1422'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.save(); ctx.scale(sx, sy);
    const p = state.palette;
    ctx.fillStyle = p[0]; ctx.fillRect(0, 0, GRID_W, GRID_H);
    const grad = ctx.createLinearGradient(0, 0, GRID_W, GRID_H); grad.addColorStop(0, 'rgba(255,255,255,.08)'); grad.addColorStop(.55, 'rgba(255,255,255,0)'); grad.addColorStop(1, 'rgba(0,0,0,.17)'); ctx.fillStyle = grad; ctx.fillRect(0,0,GRID_W,GRID_H);
    drawThemeTexture();
    // Claimed cells use a clustered path so the field has no visible grid.
    ctx.fillStyle = '#0b1422';
    for (let y = 0; y < GRID_H; y++) for (let x = 0; x < GRID_W; x++) if (state.grid[index(x,y)] !== FIELD) ctx.fillRect(x, y, 1.03, 1.03);
    // Subtle inner outline of claimed territory.
    ctx.fillStyle = 'rgba(114,244,209,.22)';
    for (let y = 1; y < GRID_H - 1; y++) for (let x = 1; x < GRID_W - 1; x++) if (state.grid[index(x,y)] === FIELD && (solid(x-1,y) || solid(x+1,y) || solid(x,y-1) || solid(x,y+1))) ctx.fillRect(x, y, 1, 1);
    drawRoutes(); drawObstacles(); if (state.aim) drawAim(state.aim); if (state.cut) drawCut(state.cut); drawBalls();
    if (state.flash) { ctx.fillStyle = `rgba(255,92,77,${state.flash * .5})`; ctx.fillRect(0, 0, GRID_W, GRID_H); }
    ctx.restore();
  }
  function drawThemeTexture() {
    ctx.save();
    if (state.theme === 'flight') {
      ctx.fillStyle = 'rgba(230,255,247,.08)';
      for (let i = 0; i < 7; i++) { const x = (i * 23 + 9) % 112 + 3, y = (i * 17 + 11) % 64 + 3; ctx.fillRect(x, y, 7, .38); ctx.fillRect(x + 1.4, y - .4, 3.6, .35); }
    } else {
      ctx.strokeStyle = 'rgba(246,230,180,.075)'; ctx.lineWidth = .12;
      for (let x = 8; x < GRID_W; x += 12) { ctx.beginPath(); ctx.moveTo(x, 2); ctx.lineTo(x, GRID_H - 2); ctx.stroke(); }
      for (let y = 8; y < GRID_H; y += 12) { ctx.beginPath(); ctx.moveTo(2, y); ctx.lineTo(GRID_W - 2, y); ctx.stroke(); }
    }
    ctx.restore();
  }
  function drawObstacles() {
    for (const obstacle of state.obstacles) state.theme === 'flight' ? drawMountain(obstacle) : drawCityBlock(obstacle);
  }
  function drawMountain({ x, y, w, h }) {
    ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
    ctx.fillStyle = '#102232'; ctx.fillRect(x, y, w, h);
    const peakA = x + Math.max(1.3, w * .28), peakB = x + Math.min(w - 1.3, w * .7);
    ctx.fillStyle = '#315263'; ctx.beginPath(); ctx.moveTo(x, y + h); ctx.lineTo(peakA, y + .55); ctx.lineTo(x + w * .58, y + h); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#234252'; ctx.beginPath(); ctx.moveTo(x + w * .25, y + h); ctx.lineTo(peakB, y + h * .12); ctx.lineTo(x + w, y + h); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#a9d5cc'; ctx.fillRect(peakA - .48, y + .62, .96, .24); ctx.fillRect(peakA - .23, y + .86, .46, .28); ctx.fillRect(peakB - .43, y + h * .14, .86, .22);
    ctx.fillStyle = 'rgba(184,247,219,.38)'; for (let xx = x + .7; xx < x + w - .5; xx += 1.35) ctx.fillRect(xx, y + h - .65, .35, .16);
    ctx.restore();
  }
  function drawCityBlock({ x, y, w, h }) {
    ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
    ctx.fillStyle = '#152233'; ctx.fillRect(x, y, w, h);
    const widths = [Math.max(1.4, w * .29), Math.max(1.5, w * .34), Math.max(1.25, w * .22)]; let cursor = x + .35;
    widths.forEach((building, i) => {
      const top = y + (i === 1 ? .35 : 1.15);
      ctx.fillStyle = i === 1 ? '#304154' : '#26384b'; ctx.fillRect(cursor, top, building, y + h - top);
      ctx.fillStyle = '#e7c86d';
      for (let wy = top + .6; wy < y + h - .35; wy += .78) for (let wx = cursor + .35; wx < cursor + building - .18; wx += .65) if ((Math.floor(wx * 5 + wy * 3) % 3) !== 0) ctx.fillRect(wx, wy, .17, .24);
      cursor += building + .22;
    });
    ctx.fillStyle = '#0d1725'; ctx.fillRect(x, y + h - .42, w, .42); ctx.restore();
  }
  function drawRoutes() { for (const route of state.routes) drawRoute(route, false); }
  function routeEndpoints(c) { return { x1: c.x - c.dx * c.negative, y1: c.y - c.dy * c.negative, x2: c.x + c.dx * c.positive, y2: c.y + c.dy * c.positive }; }
  function drawRoute(c, active) {
    const { x1, y1, x2, y2 } = routeEndpoints(c); const flight = state.theme === 'flight';
    ctx.save(); ctx.lineCap = 'butt'; ctx.lineJoin = 'round';
    if (active) { ctx.shadowColor = flight ? '#a6ffe2' : '#ffe29b'; ctx.shadowBlur = 1.8; }
    ctx.lineWidth = 1.55; ctx.strokeStyle = flight ? '#2b3a46' : '#27303a'; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.lineWidth = 1.02; ctx.strokeStyle = flight ? '#687c82' : '#4d5962'; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.shadowBlur = 0; ctx.setLineDash([1.25, 1.1]); ctx.lineDashOffset = active ? performance.now() / -55 : 0; ctx.lineWidth = .15; ctx.strokeStyle = flight ? '#e9fff7' : '#ffd36e'; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.setLineDash([]); ctx.restore();
  }
  function drawAim({ from, to }) {
    if (Math.hypot(to.x - from.x, to.y - from.y) < .8) return;
    ctx.save(); ctx.strokeStyle = state.theme === 'flight' ? 'rgba(226,255,246,.82)' : 'rgba(255,222,142,.84)'; ctx.lineWidth = .22; ctx.setLineDash([.75,.65]); ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = '#ffffff'; ctx.fillRect(from.x-.28,from.y-.28,.56,.56); ctx.restore();
  }
  function drawCut(c) {
    drawRoute(c, true);
    const { x1, y1, x2, y2 } = routeEndpoints(c); ctx.save(); ctx.fillStyle = state.theme === 'flight' ? '#c4fff0' : '#ffe0a1'; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 1.3;
    ctx.fillRect(x1-.26,y1-.26,.52,.52); ctx.fillRect(x2-.26,y2-.26,.52,.52); ctx.restore();
  }
  function drawBalls() {
    const sprite = sprites[state.theme]; const trailColor = state.theme === 'flight' ? '190,247,231' : '255,202,108';
    for (const ball of state.balls) {
      for (let i = ball.trail.length - 1; i >= 0; i--) { const t = ball.trail[i], a = (ball.trail.length - i) / ball.trail.length * .17; ctx.fillStyle = `rgba(${trailColor},${a})`; ctx.fillRect(t.x-.2,t.y-.2,.4,.4); }
      ctx.save(); ctx.translate(ball.x, ball.y); ctx.rotate(Math.atan2(ball.vy, ball.vx)); ctx.shadowColor = state.theme === 'flight' ? '#ff9271' : '#9aefff'; ctx.shadowBlur = 1.4;
      if (sprite.complete && sprite.naturalWidth) ctx.drawImage(sprite, -2.25, -1.68, 4.5, 3.36);
      else { ctx.fillStyle = state.theme === 'flight' ? '#ff8d63' : '#5bd6e2'; ctx.fillRect(-1.55,-.48,3.1,.96); ctx.fillRect(-.25,-1.05,.7,2.1); }
      ctx.restore();
    }
  }
  function loop(time) { const dt = Math.min(.033, Math.max(0, (time - state.lastTime) / 1000)); state.lastTime = time; update(dt); draw(); requestAnimationFrame(loop); }

  function chirp(frequency, length, type) {
    if (!state.sound) return;
    try { audioContext ||= new AudioContext(); const osc = audioContext.createOscillator(), gain = audioContext.createGain(); osc.type = type; osc.frequency.value = frequency; gain.gain.setValueAtTime(.045, audioContext.currentTime); gain.gain.exponentialRampToValueAtTime(.001, audioContext.currentTime + length); osc.connect(gain).connect(audioContext.destination); osc.start(); osc.stop(audioContext.currentTime + length); } catch { /* Sound is optional. */ }
  }
  function canvasPoint(event) { const rect = canvas.getBoundingClientRect(); return { x: (event.clientX - rect.left) / rect.width * GRID_W, y: (event.clientY - rect.top) / rect.height * GRID_H }; }
  function togglePause() { if (!state.running) return; state.paused = !state.paused; ui.pauseOverlay.classList.toggle('hidden', !state.paused); ui.pause.textContent = state.paused ? 'Resume' : 'Pause'; ui.pause.append(key('P')); if (!state.paused) state.lastTime = performance.now(); }

  canvas.addEventListener('pointerdown', (event) => {
    if (!state.running || state.paused || state.cut) return;
    event.preventDefault(); const from = canvasPoint(event);
    state.aim = { from, to: from }; canvas.setPointerCapture?.(event.pointerId);
  });
  canvas.addEventListener('pointermove', (event) => { if (state.aim) state.aim.to = canvasPoint(event); });
  canvas.addEventListener('pointerup', (event) => {
    if (!state.aim) return;
    const from = state.aim.from; state.aim = null; canvas.releasePointerCapture?.(event.pointerId); makeCut(from, canvasPoint(event));
  });
  canvas.addEventListener('pointercancel', () => { state.aim = null; });
  ui.start.addEventListener('click', startNewRun); ui.pause.addEventListener('click', togglePause); ui.resume.addEventListener('click', togglePause);
  ui.restart.addEventListener('click', () => { if (state.running || state.hasStarted) { startLevel(state.level, false); toast('Level restarted', 900); } });
  ui.flight.addEventListener('click', () => setTheme('flight')); ui.drive.addEventListener('click', () => setTheme('drive'));
  ui.sound.addEventListener('click', () => { state.sound = !state.sound; ui.sound.setAttribute('aria-pressed', String(state.sound)); ui.sound.style.color = state.sound ? '' : '#52636a'; });
  ui.resetStats.addEventListener('click', () => { if (confirm('Reset all local records for Path Patrol?')) { stats = { bestClear: 0, bestLevel: 0, runs: 0, wins: 0 }; saveStats(); toast('Local records reset', 1000); } });
  document.addEventListener('keydown', (event) => {
    if (event.key.toLowerCase() === 'p') togglePause();
    if (event.key.toLowerCase() === 'f') setTheme('flight'); if (event.key.toLowerCase() === 'd') setTheme('drive');
    if (event.key === 'Escape' && state.running && !state.paused) togglePause();
  });
  syncThemeUi(); updateStats(); updateHud(); requestAnimationFrame(loop);
})();
