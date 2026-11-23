/* Canvas graph view. Data: data/graph.json (see scripts/build_graph.py). No dependencies. */
(function () {
  'use strict';
  var RHG = window.RHGraph = {};
  var wrap, cv, ctx, W = 0, H = 0, DPR = 1, statusEl, tipEl, panelEl, searchEl, resEl;
  var G = null, loading = false;
  // node columns
  var NN, NAME, PAR, LV, TH, WGT, WTOT, MD, DS, KM, OWN, X, Y, RAD, KIDS, TIN, TOUT, FULL;
  var E, MAIN, THEORIES, SHA, MAXR = 1;
  // view state
  var cam = { x: 0, y: 0, k: 1 };
  var expanded, vis = [], visSet, rep, visSorted = [], groups = [], halos = [];
  var VE = { a: [], b: [], w: [] };                // aggregated edges between visible nodes, sorted by weight desc
  var sel = -1, hov = -1, selEdges = [], hovEdges = [], inFocus = null;
  var mode = 'origin', edgeN = 2500, showLabels = true;
  var grid = null, dirty = true, anim = null, theme = null;
  var KINDC = ['theorem/lemma', 'def/abbrev', 'structure/class', 'instance'];
  var KINDCOL = ['#c2570c', '#2a5bd7', '#8a4fd1', '#1f7a4d'];

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function fmt(x) { return x >= 1e6 ? (x / 1e6).toFixed(1) + 'M' : x >= 1e4 ? (x / 1e3).toFixed(0) + 'k' : x >= 1e3 ? (x / 1e3).toFixed(1) + 'k' : String(x); }

  // ------------------------------------------------------------------ load
  RHG.show = function () {
    if (!wrap) setup();
    if (!G && !loading) load(); else { resize(); }
  };
  function load() {
    loading = true; status('Loading graph…');
    fetch('data/graph.json').then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(init).catch(function (e) { status('Could not load data/graph.json (' + e.message + '). Serve the folder over http.'); loading = false; });
  }
  function status(t) { statusEl.hidden = !t; statusEl.textContent = t || ''; }

  function init(g) {
    G = g; var n = g.n, m = g.meta;
    NN = m.nodes; MAIN = m.main; THEORIES = m.theories; SHA = m.sha;
    NAME = n.name; PAR = Int32Array.from(n.p); LV = n.lv; TH = n.th; WGT = n.w; WTOT = n.wt; MD = n.md; DS = n.ds;
    KM = n.k; OWN = n.own; X = n.x; Y = n.y; RAD = n.r; MAXR = Math.max.apply(null, RAD);
    E = Int32Array.from(g.e);
    KIDS = new Array(NN); for (var i = 0; i < NN; i++) KIDS[i] = [];
    var roots = [];
    for (i = 0; i < NN; i++) { if (PAR[i] >= 0) KIDS[PAR[i]].push(i); else roots.push(i); }
    for (i = 0; i < NN; i++) KIDS[i].sort(function (a, b) { return NAME[a] < NAME[b] ? -1 : 1; });
    // full dotted names + euler tour (subtree test)
    FULL = new Array(NN);
    for (i = 0; i < NN; i++) FULL[i] = PAR[i] < 0 ? NAME[i] : FULL[PAR[i]] + '.' + NAME[i];  // parents precede children in id order
    TIN = new Int32Array(NN); TOUT = new Int32Array(NN);
    var t = 0, st = [];
    roots.forEach(function (r) {
      st.push([r, 0]);
      while (st.length) {
        var f = st[st.length - 1], u = f[0];
        if (f[1] === 0) TIN[u] = t++;
        if (f[1] < KIDS[u].length) { st.push([KIDS[u][f[1]++], 0]); } else { TOUT[u] = t; st.pop(); }
      }
    });
    ROOTS = roots;
    expanded = new Uint8Array(NN);
    roots.forEach(function (r) { if (r !== MAIN && KIDS[r].length) expanded[r] = 1; });
    $('gstat').textContent = fmt(m.reach) + ' reachable declarations · ' + fmt(NN) + ' clusters · ' + fmt(m.edge_pairs) + ' edge pairs';
    status('');
    rebuild(); fitAll(); resize();
  }
  var ROOTS = [];

  // ------------------------------------------------------------------ frontier + edges
  function rebuild() {
    vis = []; visSet = new Uint8Array(NN);
    (function walk(list) {
      for (var q = 0; q < list.length; q++) {
        var i = list[q];
        if (expanded[i] && KIDS[i].length) walk(KIDS[i]); else { vis.push(i); visSet[i] = 1; }
      }
    })(ROOTS);
    rep = new Int32Array(NN).fill(-1);
    for (var i = 0; i < NN; i++) rep[i] = visSet[i] ? i : (PAR[i] >= 0 ? rep[PAR[i]] : -1);
    var mp = new Map();
    for (var t = 0; t < E.length; t += 3) {
      var a = rep[E[t]], b = rep[E[t + 1]];
      if (a < 0 || b < 0 || a === b) continue;
      var key = a * NN + b;
      mp.set(key, (mp.get(key) || 0) + E[t + 2]);
    }
    var ks = Array.from(mp.keys()), ws = ks.map(function (k) { return mp.get(k); });
    var ord = ks.map(function (_, j) { return j; }).sort(function (p, q) { return ws[q] - ws[p]; });
    VE = { a: new Int32Array(ord.length), b: new Int32Array(ord.length), w: new Float64Array(ord.length) };
    ord.forEach(function (j, r) { var k = ks[j]; VE.a[r] = Math.floor(k / NN); VE.b[r] = k % NN; VE.w[r] = ws[j]; });
    visSorted = vis.slice().sort(function (p, q) { return RAD[q] - RAD[p]; });
    // halos around expanded clusters (context for "what did this node open into")
    halos = [];
    for (i = 0; i < NN; i++) {
      if (!expanded[i] || LV[i] < 2 || !KIDS[i].length) continue;
      var sx = 0, sy = 0, c = 0;
      for (var q = 0; q < vis.length; q++) { var v = vis[q]; if (TIN[v] >= TIN[i] && TIN[v] < TOUT[i]) { sx += X[v]; sy += Y[v]; c++; } }
      if (!c) continue;
      var cx = sx / c, cy = sy / c, rr = 0;
      for (q = 0; q < vis.length; q++) { v = vis[q]; if (TIN[v] >= TIN[i] && TIN[v] < TOUT[i]) rr = Math.max(rr, Math.hypot(X[v] - cx, Y[v] - cy) + RAD[v]); }
      halos.push({ id: i, x: cx, y: cy, r: rr + 4 });
    }
    buildGrid(); recolor(); setSel(sel, true); dirty = true; schedule();
  }

  function buildGrid() {
    grid = new Map(); var CS = 100;
    grid.cs = CS;
    vis.forEach(function (i) { var key = Math.floor(X[i] / CS) * 100003 + Math.floor(Y[i] / CS); var a = grid.get(key); if (a) a.push(i); else grid.set(key, [i]); });
  }
  function pick(px, py) {
    var wx = (px - W / 2) / cam.k + cam.x, wy = (py - H / 2) / cam.k + cam.y, CS = grid.cs, best = -1, bd = 1e18;
    var reach = (srad0() + 6) / cam.k;
    var x0 = Math.floor((wx - reach) / CS), x1 = Math.floor((wx + reach) / CS), y0 = Math.floor((wy - reach) / CS), y1 = Math.floor((wy + reach) / CS);
    for (var cx = x0; cx <= x1; cx++) for (var cy = y0; cy <= y1; cy++) {
      var a = grid.get(cx * 100003 + cy); if (!a) continue;
      for (var q = 0; q < a.length; q++) {
        var i = a[q], d = Math.hypot((X[i] - wx) * cam.k, (Y[i] - wy) * cam.k), lim = srad(i) + 2;
        if (d <= lim && d - srad(i) * 0.2 < bd) { bd = d - srad(i) * 0.2; best = i; }
      }
    }
    return best;
  }
  function srad0() { return Math.max(MAXR * cam.k, 1.8 + 0.25 * MAXR); }
  // edges touching a node (or, if it is expanded, anything inside its subtree)
  function neighborEdges(id) {
    if (id < 0) return { list: [], focus: null };
    var focus = new Uint8Array(NN);
    for (var q = 0; q < vis.length; q++) { var v = vis[q]; if (TIN[v] >= TIN[id] && TIN[v] < TOUT[id]) focus[v] = 1; }
    var list = [];
    for (var j = 0; j < VE.w.length; j++) {
      var fa = focus[VE.a[j]], fb = focus[VE.b[j]];
      if (fa !== fb) list.push(j);
    }
    return { list: list, focus: focus };
  }

  // ------------------------------------------------------------------ colour
  function readTheme() {
    var cs = getComputedStyle(document.documentElement);
    var dark = document.documentElement.getAttribute('data-theme') ? document.documentElement.getAttribute('data-theme') === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    theme = { dark: dark, bg: cs.getPropertyValue('--bg').trim() || '#fff', ink: cs.getPropertyValue('--ink').trim() || '#000', mute: cs.getPropertyValue('--mute').trim() || '#888', line: cs.getPropertyValue('--line').trim() || '#ddd', accent: cs.getPropertyValue('--accent').trim() || '#2a5bd7' };
  }
  var THEORY_HUES = [24, 205, 285, 150, 340, 55, 175, 100];
  function lightOf(md) {  // near Main = strong, far = quiet
    var t = Math.min(1, Math.max(0, (md - 1) / 40));
    return theme.dark ? 72 - 30 * t : 40 + 32 * t;
  }
  function fillOf(i) {
    if (i === MAIN) return theme.dark ? '#ffd84d' : '#e0a800';
    var l = lightOf(MD[i]);
    if (mode === 'theory') return 'hsl(' + THEORY_HUES[TH[i] % THEORY_HUES.length] + ',62%,' + (theme.dark ? l : l - 4) + '%)';
    return 'hsl(24,' + (theme.dark ? 78 : 82) + '%,' + l + '%)';
  }
  var fillCache;
  function recolor() {
    readTheme(); fillCache = new Array(NN);
    var gm = new Map();
    visSorted.forEach(function (i) { var f = fillCache[i] = fillOf(i); var a = gm.get(f); if (a) a.push(i); else gm.set(f, [i]); });
    groups = Array.from(gm.entries());
    renderLegend();
  }

  // ------------------------------------------------------------------ drawing
  function schedule() { if (!anim && !raf) raf = requestAnimationFrame(frame); }
  var raf = 0;
  function frame(ts) {
    raf = 0;
    if (anim) {
      var t = Math.min(1, (ts - anim.t0) / anim.dur), e = 1 - Math.pow(1 - t, 3);
      cam.x = anim.x0 + (anim.x1 - anim.x0) * e; cam.y = anim.y0 + (anim.y1 - anim.y0) * e; cam.k = Math.exp(Math.log(anim.k0) + (Math.log(anim.k1) - Math.log(anim.k0)) * e);
      dirty = true;
      if (t >= 1) { anim = null; settle(); } else raf = requestAnimationFrame(frame);
    }
    if (dirty) { draw(); dirty = false; }
  }
  function srad(i) { return Math.max(RAD[i] * cam.k, 1.8 + 0.25 * RAD[i]); }  // dots stay visible when zoomed out
  function sx(x) { return (x - cam.x) * cam.k + W / 2; }
  function sy(y) { return (y - cam.y) * cam.k + H / 2; }

  function draw() {
    if (!G) return;
    if (!theme) readTheme();
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.fillStyle = theme.bg; ctx.fillRect(0, 0, W, H);
    var k = cam.k;
    // halos of expanded clusters
    ctx.setLineDash([4, 4]); ctx.strokeStyle = theme.mute; ctx.lineWidth = 1; ctx.globalAlpha = 0.55;
    halos.forEach(function (h) {
      var r = h.r * k; if (r < 6) return;
      var x = sx(h.x), y = sy(h.y); if (x + r < 0 || x - r > W || y + r < 0 || y - r > H) return;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.stroke();
    });
    ctx.setLineDash([]); ctx.globalAlpha = 1;
    // background edges: strongest N, in three weight classes
    var n = Math.min(edgeN, VE.w.length), cls = [[], [], []];
    for (var j = 0; j < n; j++) {
      var a = VE.a[j], b = VE.b[j];
      var ax = sx(X[a]), ay = sy(Y[a]), bx = sx(X[b]), by = sy(Y[b]);
      if ((ax < 0 && bx < 0) || (ax > W && bx > W) || (ay < 0 && by < 0) || (ay > H && by > H)) continue;
      cls[VE.w[j] > 300 ? 2 : VE.w[j] > 30 ? 1 : 0].push(j);
    }
    var ea = [0.13, 0.22, 0.38], ew = [0.8, 1, 1.5];
    ctx.strokeStyle = theme.ink;
    for (var c = 0; c < 3; c++) {
      if (!cls[c].length) continue;
      ctx.globalAlpha = (selEdges.length || hovEdges.length) ? ea[c] * 0.45 : ea[c]; ctx.lineWidth = ew[c]; ctx.beginPath();
      cls[c].forEach(function (j) { ctx.moveTo(sx(X[VE.a[j]]), sy(Y[VE.a[j]])); ctx.lineTo(sx(X[VE.b[j]]), sy(Y[VE.b[j]])); });
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // neighbourhood edges (hover, then selection on top)
    drawHi(hovEdges, 0.5, 1.2); drawHi(selEdges, 0.95, 1.8);
    // nodes
    ctx.strokeStyle = theme.bg; ctx.lineWidth = 1;
    groups.forEach(function (g) {
      ctx.fillStyle = g[0]; ctx.beginPath();
      var big = [];
      g[1].forEach(function (i) {
        var x = sx(X[i]), y = sy(Y[i]), r = srad(i);
        if (x + r < 0 || x - r > W || y + r < 0 || y - r > H) return;
        if (r < 2.2) { ctx.rect(x - r, y - r, 2 * r, 2 * r); } else { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 6.2832); big.push(i); }
      });
      ctx.fill();
      if (big.length) { ctx.beginPath(); big.forEach(function (i) { var x = sx(X[i]), y = sy(Y[i]), r = srad(i); ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 6.2832); }); ctx.stroke(); }
    });
    // Main halo
    if (visSet[MAIN]) { ctx.strokeStyle = theme.accent; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx(X[MAIN]), sy(Y[MAIN]), srad(MAIN) + 3, 0, 6.2832); ctx.stroke(); }
    // focus rings
    ring(sel, theme.accent, 2.5); if (hov !== sel) ring(hov, theme.ink, 1.5);
    if (showLabels) drawLabels();
    drawTheoryLabels();
  }
  function ring(i, col, lw) {
    if (i < 0 || !visSet[i]) return;
    ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.beginPath(); ctx.arc(sx(X[i]), sy(Y[i]), srad(i) + 3, 0, 6.2832); ctx.stroke();
  }
  function drawHi(list, alpha, lw) {
    if (!list.length) return;
    ctx.strokeStyle = theme.accent; ctx.fillStyle = theme.accent; ctx.globalAlpha = alpha; ctx.lineWidth = lw; ctx.beginPath();
    var heads = [];
    var cnt = Math.min(list.length, 400);
    for (var q = 0; q < cnt; q++) {
      var j = list[q], a = VE.a[j], b = VE.b[j];
      var x1 = sx(X[a]), y1 = sy(Y[a]), x2 = sx(X[b]), y2 = sy(Y[b]);
      ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
      var L = Math.hypot(x2 - x1, y2 - y1); if (L > 14) { var ux = (x2 - x1) / L, uy = (y2 - y1) / L, rb = srad(b); heads.push([x2 - ux * (rb + 1), y2 - uy * (rb + 1), ux, uy]); }
    }
    ctx.stroke();
    heads.forEach(function (h) { ctx.beginPath(); ctx.moveTo(h[0], h[1]); ctx.lineTo(h[0] - h[2] * 7 - h[3] * 3.5, h[1] - h[3] * 7 + h[2] * 3.5); ctx.lineTo(h[0] - h[2] * 7 + h[3] * 3.5, h[1] - h[3] * 7 - h[2] * 3.5); ctx.closePath(); ctx.fill(); });
    ctx.globalAlpha = 1;
  }
  function drawLabels() {
    ctx.font = '11.5px system-ui,sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
    var placed = [], count = 0;
    function put(i, force) {
      var x = sx(X[i]), y = sy(Y[i]), r = srad(i);
      if (x < -50 || x > W + 50 || y < -20 || y > H + 20) return;
      if (!force && r < 9) return;
      var t = i === MAIN ? 'Main' : NAME[i], tw = ctx.measureText(t).width;
      var bx = x - tw / 2 - 2, by = y + Math.max(r, 3) + 3 - 7, bw = tw + 4, bh = 14;
      if (!force) { for (var q = 0; q < placed.length; q++) { var p = placed[q]; if (bx < p[0] + p[2] && bx + bw > p[0] && by < p[1] + p[3] && by + bh > p[1]) return; } }
      placed.push([bx, by, bw, bh]); count++;
      ctx.lineWidth = 3; ctx.strokeStyle = theme.bg; ctx.strokeText(t, x, by + 7); ctx.fillStyle = theme.ink; ctx.fillText(t, x, by + 7);
    }
    if (sel >= 0) put(sel, true);
    if (hov >= 0 && hov !== sel) put(hov, true);
    for (var q = 0; q < visSorted.length && count < 220; q++) put(visSorted[q], false);
  }
  function drawTheoryLabels() {
    var al = Math.min(1, Math.max(0, (0.9 - cam.k) / 0.5)); if (al <= 0) return;
    ctx.save(); ctx.globalAlpha = 0.85 * al; ctx.font = '700 15px system-ui,sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ROOTS.forEach(function (i) {
      if (i === MAIN) return;
      var x = sx(X[i]), y = sy(Y[i]); if (x < -80 || x > W + 80 || y < -20 || y > H + 20) return;
      var w = ctx.measureText(NAME[i]).width;
      ctx.fillStyle = theme.bg; ctx.globalAlpha = 0.7 * al; ctx.fillRect(x - w / 2 - 4, y - 11, w + 8, 22);
      ctx.globalAlpha = 0.9 * al; ctx.fillStyle = theme.mute; ctx.fillText(NAME[i], x, y);
    });
    ctx.restore();
  }

  // ------------------------------------------------------------------ camera / expansion
  function fitAll() {
    var rs = vis.map(function (i) { return Math.hypot(X[i], Y[i]) + RAD[i]; }).sort(function (a, b) { return a - b; });
    var R = (rs.length ? rs[Math.floor(rs.length * 0.97)] : 1500) * 1.1;
    cam.x = 0; cam.y = 0; cam.k = Math.min(W || 800, H || 600) / (2 * R); dirty = true;
  }
  function flyTo(x, y, k, dur) {
    anim = { t0: performance.now(), dur: dur || 450, x0: cam.x, y0: cam.y, k0: cam.k, x1: x, y1: y, k1: k }; schedule();
  }
  function flyToNode(i) {
    var r = Math.max(RAD[i], 6), k = Math.min(Math.max(Math.min(W, H) / (r * 8), cam.k), 40);
    flyTo(X[i], Y[i], k);
  }
  function fitBox(ids) {
    var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    ids.forEach(function (i) { x0 = Math.min(x0, X[i] - RAD[i]); x1 = Math.max(x1, X[i] + RAD[i]); y0 = Math.min(y0, Y[i] - RAD[i]); y1 = Math.max(y1, Y[i] + RAD[i]); });
    var k = Math.min(W / ((x1 - x0) * 1.3 + 1), H / ((y1 - y0) * 1.3 + 1), 40);
    flyTo((x0 + x1) / 2, (y0 + y1) / 2, Math.max(k, cam.k));
  }
  function expand(i, fly) {
    if (!KIDS[i].length || expanded[i]) return;
    expanded[i] = 1; rebuild();
    if (fly) fitBox(KIDS[i].filter(function (c) { return visSet[c]; }).concat(KIDS[i].filter(function (c) { return !visSet[c]; })));
  }
  function collapse(i) {
    for (var j = 0; j < NN; j++) if (TIN[j] >= TIN[i] && TIN[j] < TOUT[i] && expanded[j]) expanded[j] = 0;
    rebuild();
  }
  function ensureVisible(i) {
    var chain = []; for (var j = PAR[i]; j >= 0; j = PAR[j]) chain.push(j);
    chain.forEach(function (a) { expanded[a] = 1; });
    rebuild();
  }
  // semantic zoom: open clusters that grew big on screen, close ones that shrank to a speck
  var settleT = 0;
  function settle() { clearTimeout(settleT); settleT = setTimeout(autoLOD, 120); }
  function autoLOD() {
    if (!G) return;
    var changed = false, opened = 0;
    for (var q = 0; q < vis.length && opened < 40; q++) {
      var i = vis[q]; if (!KIDS[i].length || i === MAIN) continue;
      var x = sx(X[i]), y = sy(Y[i]), r = RAD[i] * cam.k;
      if (r >= 26 && x > -r && x < W + r && y > -r && y < H + r && vis.length < 14000) { expanded[i] = 1; changed = true; opened++; }
    }
    for (var h = 0; h < halos.length; h++) {
      var ha = halos[h];
      if (ha.r * cam.k < 18 && !(sel >= 0 && TIN[sel] >= TIN[ha.id] && TIN[sel] < TOUT[ha.id])) { expanded[ha.id] = 0; changed = true; for (var j = 0; j < NN; j++) if (TIN[j] > TIN[ha.id] && TIN[j] < TOUT[ha.id]) expanded[j] = 0; }
    }
    if (changed) { rebuild(); settle(); }
  }

  // ------------------------------------------------------------------ selection + panel
  function setSel(i, keepPanel) {
    sel = i;
    if (i >= 0) { var r = neighborEdges(i); selEdges = r.list; inFocus = r.focus; } else { selEdges = []; inFocus = null; }
    if (!keepPanel || i >= 0) renderPanel(); else if (i < 0) panelEl.hidden = true;
    dirty = true; schedule();
  }
  function kmix(i) {
    var t = KM[4 * i] + KM[4 * i + 1] + KM[4 * i + 2] + KM[4 * i + 3] || 1, s = '<div class="kmix">';
    for (var c = 0; c < 4; c++) s += '<i style="width:' + (100 * KM[4 * i + c] / t) + '%;background:' + KINDCOL[c] + '" title="' + KINDC[c] + ': ' + KM[4 * i + c] + '"></i>';
    s += '</div><div class="sub2">' + KINDC.map(function (n, c) { return n + ' ' + fmt(KM[4 * i + c]); }).join(' · ') + '</div>';
    return s;
  }
  function renderPanel() {
    var i = sel; if (i < 0) { panelEl.hidden = true; return; }
    panelEl.hidden = false;
    var crumbs = [], j = i; while (j >= 0) { crumbs.unshift(j); j = PAR[j]; }
    var h = '<button class="x" id="gx" title="Close">×</button>';
    h += '<div class="crumbs sub2">' + crumbs.map(function (c) { return c === i ? esc(NAME[c]) : '<a class="lnk" data-go="' + c + '">' + esc(NAME[c]) + '</a>'; }).join(' › ') + '</div>';
    h += '<h2>' + (i === MAIN ? 'Main (the five RH theorems)' : esc(FULL[i])) + '</h2>';
    h += '<div class="sub2">' + fmt(WGT[i]) + ' declarations reachable from Main · ' + fmt(WTOT[i]) + ' in these modules · proof depth ' + (MD[i] < 0 ? '–' : MD[i] + ' (mean ' + DS[i] + ')') + '</div>';
    h += kmix(i);
    h += '<div id="gkeys"></div><div class="btns">';
    if (KIDS[i].length && !expanded[i]) h += '<button id="gexp">Expand (' + KIDS[i].length + ')</button>';
    if (expanded[i] || (PAR[i] >= 0 && expanded[PAR[i]] && LV[i] > 1)) h += '<button id="gcol">Collapse</button>';
    h += '<button id="gfly">Zoom to</button></div>';
    if (selEdges.length) {
      var uses = [], usedBy = [];
      selEdges.forEach(function (j) { if (inFocus[VE.a[j]]) uses.push(j); else usedBy.push(j); });
      h += listNb('Uses (depends on)', uses, 'b') + listNb('Used by', usedBy, 'a');
    } else h += '<div class="sub2" style="margin-top:8px">No edges to other visible clusters.</div>';
    panelEl.innerHTML = h;
    loadKeys(i);
  }
  // ---- key declarations: docstring (if the source has one) + statement fetched on demand from GitHub at the pinned commit
  var GH = 'Deicyde/riemann-hypothesis', shardCache = {}, srcCache = {};
  function shard(i) {
    var key = i === MAIN ? 'main' : String(TH[i]);
    if (!shardCache[key]) shardCache[key] = fetch('data/k/' + key + '.json').then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
    return shardCache[key];
  }
  function loadKeys(i) {
    var box = $('gkeys'); if (!box) return;
    box.innerHTML = '<div class="sub2">Loading key declarations…</div>';
    shard(i).then(function (sh) {
      if (sel !== i) return;
      var rows = sh.n[String(i)]; box = $('gkeys'); if (!box) return;
      if (!rows || !rows.length) { box.innerHTML = ''; return; }
      box.innerHTML = '<h3>Key declarations · most used</h3>' + rows.map(function (r, q) {
        var mod = sh.m[r[1]];
        return '<div class="kd" data-q="' + q + '"><div class="kn"><b>' + esc(r[0]) + '</b> <span class="sub2">' + esc(r[5]) + (r[3] ? ' · used by ' + fmt(r[3]) : '') + '</span></div>' +
          (r[4] ? '<div class="kdoc">' + esc(r[4]) + '</div>' : '') +
          '<div class="sub2">' + esc(mod) + ':' + r[2] + ' · <a class="lnk kst" data-q="' + q + '">statement</a> · <a class="lnk" target="_blank" rel="noopener noreferrer" href="' + ghUrl(mod, r[2]) + '">GitHub ↗</a></div><pre class="ksrc" hidden></pre></div>';
      }).join('');
      box.onclick = function (e) {
        var t = e.target; if (!t.classList || !t.classList.contains('kst')) return;
        var kd = t.closest('.kd'), pre = kd.querySelector('.ksrc'), r = rows[+t.dataset.q];
        if (!pre.hidden) { pre.hidden = true; return; }
        pre.hidden = false; pre.textContent = 'Loading source…';
        fetchSource(sh.m[r[1]]).then(function (txt) { pre.textContent = statement(txt, r[2]); }).catch(function () { pre.textContent = 'Could not fetch the source from GitHub (offline, or the file is missing at this commit).'; });
      };
    }).catch(function () { var b = $('gkeys'); if (b) b.innerHTML = ''; });
  }
  function modPath(mod) { return 'src/' + mod.split('.').join('/') + '.lean'; }
  function ghUrl(mod, line) { return 'https://github.com/' + GH + '/blob/' + SHA + '/' + modPath(mod) + '#L' + line; }
  function fetchSource(mod) {
    if (!srcCache[mod]) srcCache[mod] = fetch('https://raw.githubusercontent.com/' + GH + '/' + SHA + '/' + modPath(mod)).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); });
    return srcCache[mod];
  }
  // from the declaration's first line to the end of its statement (first line with ':=' / 'where', blank line or 14 lines)
  function statement(txt, line) {
    var L = txt.split('\n'), out = [], a = Math.max(0, line - 1);
    for (var j = a; j < L.length && out.length < 14; j++) {
      if (j > a && !L[j].trim()) break;
      out.push(L[j]);
      if (/(:=|\bwhere\b)/.test(L[j])) break;
    }
    return out.join('\n');
  }
  function listNb(title, arr, side) {
    if (!arr.length) return '';
    var m = new Map();
    arr.forEach(function (j) { var o = side === 'b' ? VE.b[j] : VE.a[j]; m.set(o, (m.get(o) || 0) + VE.w[j]); });
    var rows = Array.from(m.entries()).sort(function (p, q) { return q[1] - p[1]; }).slice(0, 12);
    return '<h3>' + title + ' · ' + m.size + '</h3><ul class="dep">' + rows.map(function (r) { return '<li><a class="lnk" data-go="' + r[0] + '">' + esc(FULL[r[0]]) + '</a><span class="c">' + fmt(r[1]) + '</span></li>'; }).join('') + '</ul>';
  }

  // ------------------------------------------------------------------ search
  var resSel = -1, resIds = [];
  function search(q) {
    q = q.trim().toLowerCase(); resIds = []; resSel = -1;
    if (q.length < 2) { resEl.hidden = true; return; }
    var a = [], b = [];
    for (var i = 0; i < NN; i++) {
      var f = FULL[i].toLowerCase(); var p = f.indexOf(q); if (p < 0) continue;
      (NAME[i].toLowerCase().indexOf(q) === 0 ? a : b).push(i);
    }
    var by = function (x, y) { return WGT[y] - WGT[x]; };
    a.sort(by); b.sort(by);
    resIds = a.concat(b).slice(0, 14);
    resEl.innerHTML = resIds.map(function (i, r) { return '<div data-i="' + i + '"><span class="n">' + esc(NAME[i]) + ' <i>' + esc(PAR[i] >= 0 ? FULL[PAR[i]] : '') + '</i></span><span class="c">' + fmt(WGT[i]) + '</span></div>'; }).join('') || '<div><span class="n">No match</span></div>';
    resEl.hidden = false;
  }
  function goTo(i) {
    resEl.hidden = true; ensureVisible(i);
    var t = visSet[i] ? i : rep[i];
    setSel(t); flyToNode(t);
  }

  // ------------------------------------------------------------------ legend
  function renderLegend() {
    var el = $('glegend'); if (!el || !theme) return;
    var ramp = [1, 10, 20, 30, 40].map(function (d) { return mode === 'origin' ? 'hsl(24,' + (theme.dark ? 78 : 82) + '%,' + lightOf(d) + '%)' : 'hsl(24,0%,' + lightOf(d) + '%)'; });
    var th = mode === 'theory' ? '<div style="display:flex;flex-wrap:wrap;gap:2px 10px;margin-top:4px">' + THEORIES.map(function (t, i) { return '<span><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:hsl(' + THEORY_HUES[i % 8] + ',62%,' + (theme.dark ? 60 : 48) + '%)"></i> ' + esc(t) + '</span>'; }).join('') + '</div>' : '';
    el.innerHTML = '<b style="color:var(--ink)">Reading the map</b><br>Centre = what is claimed (Main). Clusters that use each other sit close. Size = declarations.<div class="ramp" style="background:linear-gradient(90deg,' + ramp.join(',') + ')"></div><div class="rl"><span>close to Main</span><span>deep</span></div>' + th;
  }

  // ------------------------------------------------------------------ setup / events
  function resize() {
    if (!wrap) return;
    var r = wrap.getBoundingClientRect(); if (!r.width) return;
    var first = !W;
    DPR = Math.min(window.devicePixelRatio || 1, 2); W = Math.floor(r.width); H = Math.floor(r.height);
    cv.width = W * DPR; cv.height = H * DPR;
    if (G && first) fitAll();
    dirty = true; schedule();
  }
  function setup() {
    wrap = $('gwrap'); cv = $('gcv'); ctx = cv.getContext('2d'); statusEl = $('gstatus'); tipEl = $('gtip'); panelEl = $('gpanel'); searchEl = $('gsearch'); resEl = $('gres');
    if (window.ResizeObserver) new ResizeObserver(resize).observe(wrap);
    window.addEventListener('resize', resize);
    // pointer handling: one pointer pans, two pinch
    var ptrs = new Map(), moved = 0, down = null, last = null;
    cv.addEventListener('pointerdown', function (e) {
      cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.offsetX, e.offsetY]);
      if (ptrs.size === 1) { down = [e.offsetX, e.offsetY, performance.now()]; moved = 0; cv.classList.add('drag'); }
      anim = null;
    });
    cv.addEventListener('pointermove', function (e) {
      if (!G) return;
      var p = ptrs.get(e.pointerId);
      if (!p) { hover(e.offsetX, e.offsetY, e); return; }
      if (ptrs.size === 1) {
        var dx = e.offsetX - p[0], dy = e.offsetY - p[1]; moved += Math.abs(dx) + Math.abs(dy);
        cam.x -= dx / cam.k; cam.y -= dy / cam.k; hideTip(); dirty = true; schedule();
      } else if (ptrs.size === 2) {
        var o = null; ptrs.forEach(function (v, id) { if (id !== e.pointerId) o = v; });
        var d0 = Math.hypot(p[0] - o[0], p[1] - o[1]), d1 = Math.hypot(e.offsetX - o[0], e.offsetY - o[1]);
        if (d0 > 0) zoomAt((e.offsetX + o[0]) / 2, (e.offsetY + o[1]) / 2, d1 / d0);
        moved += 10;
      }
      ptrs.set(e.pointerId, [e.offsetX, e.offsetY]);
    });
    function up(e) {
      if (!ptrs.has(e.pointerId)) return;
      ptrs.delete(e.pointerId); cv.classList.remove('drag');
      if (ptrs.size === 0 && down && moved < 5 && performance.now() - down[2] < 500 && G) { var i = pick(down[0], down[1]); setSel(i); }
      if (ptrs.size === 0) settle();
    }
    cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
    cv.addEventListener('pointerleave', function () { hover(-1, -1); });
    cv.addEventListener('wheel', function (e) { e.preventDefault(); zoomAt(e.offsetX, e.offsetY, Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015))); settle(); }, { passive: false });
    cv.addEventListener('dblclick', function (e) { if (!G) return; var i = pick(e.offsetX, e.offsetY); if (i >= 0 && KIDS[i].length) { setSel(i); expand(i, true); setSel(i); } else zoomAt(e.offsetX, e.offsetY, 2); });
    // toolbar
    searchEl.addEventListener('input', function () { if (G) search(searchEl.value); });
    searchEl.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); resSel = Math.max(0, Math.min(resIds.length - 1, resSel + (e.key === 'ArrowDown' ? 1 : -1))); Array.prototype.forEach.call(resEl.children, function (c, j) { c.classList.toggle('on', j === resSel); }); }
      else if (e.key === 'Enter' && resIds.length) goTo(resIds[Math.max(resSel, 0)]);
      else if (e.key === 'Escape') { resEl.hidden = true; searchEl.blur(); }
    });
    resEl.addEventListener('click', function (e) { var d = e.target.closest('[data-i]'); if (d) goTo(+d.dataset.i); });
    document.addEventListener('click', function (e) { if (!e.target.closest('.gsearch')) resEl.hidden = true; });
    $('greset').addEventListener('click', function () { setSel(-1); fitAll(); flyTo(0, 0, cam.k, 1); });
    $('gcollapse').addEventListener('click', function () { expanded.fill(0); ROOTS.forEach(function (r) { if (r !== MAIN && KIDS[r].length) expanded[r] = 1; }); rebuild(); setSel(-1); fitAll(); var k0 = cam.k; flyTo(0, 0, k0, 500); });
    $('gmode').addEventListener('change', function (e) { mode = e.target.value; recolor(); dirty = true; schedule(); });
    $('gedges').addEventListener('input', function (e) { edgeN = Math.round(Math.pow(10, +e.target.value)); dirty = true; schedule(); });
    $('gabtn').addEventListener('click', function () { var a = $('gabout'); a.hidden = !a.hidden; });
    panelEl.addEventListener('click', function (e) {
      var t = e.target;
      if (t.id === 'gx') setSel(-1);
      else if (t.id === 'gexp') { expand(sel, true); setSel(sel); }
      else if (t.id === 'gcol') { var s = sel; var tgt = expanded[s] ? s : PAR[s]; collapse(tgt); setSel(tgt); flyToNode(tgt); }
      else if (t.id === 'gfly') flyToNode(visSet[sel] ? sel : rep[sel] >= 0 ? rep[sel] : sel);
      else if (t.dataset && t.dataset.go) goTo(+t.dataset.go);
    });
    window.addEventListener('keydown', function (e) {
      if (!wrap || wrap.offsetParent === null) return;
      if (e.key === '/' && document.activeElement !== searchEl) { e.preventDefault(); searchEl.focus(); searchEl.select(); }
      else if (e.key === 'Escape' && document.activeElement !== searchEl) setSel(-1);
    });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () { if (G) { recolor(); dirty = true; schedule(); } });
    new MutationObserver(function () { if (G) { recolor(); dirty = true; schedule(); } }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    resize();
  }
  function zoomAt(px, py, f) {
    var nk = Math.min(Math.max(cam.k * f, 0.05), 60); f = nk / cam.k;
    var wx = (px - W / 2) / cam.k + cam.x, wy = (py - H / 2) / cam.k + cam.y;
    cam.k = nk; cam.x = wx - (px - W / 2) / cam.k; cam.y = wy - (py - H / 2) / cam.k; dirty = true; schedule();
  }
  function hover(px, py, e) {
    if (px < 0) { if (hov >= 0) { hov = -1; hovEdges = []; dirty = true; schedule(); } hideTip(); return; }
    var i = pick(px, py);
    if (i !== hov) {
      hov = i; hovEdges = (i >= 0 && i !== sel) ? neighborEdges(i).list : []; dirty = true; schedule();
    }
    if (i >= 0) {
      tipEl.hidden = false;
      tipEl.innerHTML = '<b>' + esc(i === MAIN ? 'Main' : FULL[i]) + '</b><br>' + fmt(WGT[i]) + ' decls · depth ' + (MD[i] < 0 ? '–' : MD[i]) + (KIDS[i].length ? ' · double-click to open' : '');
      var tx = Math.min(px + 14, W - tipEl.offsetWidth - 8), ty = Math.min(py + 14, H - tipEl.offsetHeight - 8);
      tipEl.style.left = Math.max(4, tx) + 'px'; tipEl.style.top = Math.max(4, ty) + 'px';
    } else hideTip();
  }
  function hideTip() { tipEl.hidden = true; }

  RHG._debug = function () { return { vis: vis.length, edges: VE.w.length, expanded: Array.prototype.reduce.call(expanded, function (a, b) { return a + b; }, 0), cam: cam, sel: sel, NN: NN, W: W, H: H }; };
  RHG._api = { expand: function (i) { expand(i, false); }, goTo: function (i) { goTo(i); }, find: function (full) { return FULL.indexOf(full); }, name: function (i) { return FULL[i]; }, draw: function () { draw(); }, setCam: function (x, y, k) { cam.x = x; cam.y = y; cam.k = k; dirty = true; schedule(); autoLOD(); }, ids: function () { return { vis: vis.slice() }; } };
})();
