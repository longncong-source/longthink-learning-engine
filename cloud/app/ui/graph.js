/* ══════════ Force-directed 3D graph engine (canvas, zero deps) ══════════
 * True 3D: nodes live in x/y/z on a moon-base sphere, perspective-projected
 * each frame with Y-rotation (auto-spin + drag) and X-tilt. Painter's
 * algorithm (back-to-front), depth shading, per-project colors via n._pcol.
 * Public API kept compatible with app.js: setData, setVisibleFilter,
 * isVisible, focusNode, fitView, reheat, nodeById, nodes, links, scale,
 * selected, _dirty, neighbors, radiusOf.
 */
"use strict";

class ForceGraph {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {{onSelect?:(node|null)=>void, onHover?:(node|null)=>void}} [handlers]
   */
  constructor(canvas, handlers = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.handlers = handlers;

    this.nodes = [];
    this.links = [];
    this.nodeById = new Map();
    this.adjacency = new Map();

    this.alpha = 0;
    this.scale = 1;
    this.panX = 0;
    this.panY = 0;

    this.hovered = null;
    this.selected = null;
    this.dragNode = null;
    this.rotating = false;
    this.panning = false;
    this._lastPointer = null;
    this._dirty = true;

    this.visibleFilter = null; // (node)=>bool
    this.sphereR = 340; // moon base radius (world units)
    this.sphereMode = true;

    // 3D camera state
    this.rotY = 0.6; // slow auto-spin around Y
    this.rotX = 0.32; // fixed tilt + drag
    this.focal = 1150; // perspective focal length (world units)

    // neural-network life
    this._t = 0; // animation clock (seconds)
    this._stars = [];
    for (let i = 0; i < 110; i++) {
      this._stars.push({
        x: Math.random(), y: Math.random(),
        r: 0.4 + Math.random() * 1.1,
        ph: Math.random() * Math.PI * 2,
        sp: 0.4 + Math.random() * 1.4,
      });
    }

    this._bind();
    this._resize();
    new ResizeObserver(() => this._resize()).observe(canvas.parentElement);
    requestAnimationFrame(() => this._frame());
  }

  /* ── data ── */
  setData(nodes, links) {
    const prev = this.nodeById;
    const N = nodes.length;
    const R = this.sphereR;
    // fibonacci sphere -> phân bố đều trên quả cầu 3D thật
    const golden = Math.PI * (3 - Math.sqrt(5));
    this.nodes = nodes.map((n, i) => {
      const old = prev.get(n.id);
      if (old) return { ...n, x: old.x, y: old.y, z: old.z ?? 0, vx: 0, vy: 0, vz: 0, fixed: old.fixed };
      const y = 1 - (i / Math.max(1, N - 1)) * 2;
      const radius = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = golden * i;
      const isCore = Math.random() < 0.15;
      const rFac = isCore ? (0.18 + Math.random() * 0.55) : (0.82 + Math.random() * 0.18);
      return {
        ...n,
        x: Math.cos(theta) * radius * R * rFac,
        y: y * R * rFac,
        z: Math.sin(theta) * radius * R * rFac,
        vx: 0, vy: 0, vz: 0,
        fixed: false,
      };
    });
    const ids = new Set(nodes.map((n) => n.id));
    this.links = links.filter((l) => {
      const s = typeof l.source === "string" ? l.source : l.source.id;
      const t = typeof l.target === "string" ? l.target : l.target.id;
      return ids.has(s) && ids.has(t);
    });
    // sibling synapse — nối memory cùng project/dữ liệu thành mạng neuron
    // (mỗi memory nối tối đa 2 node cùng nhóm, lò xo yếu, render mờ)
    {
      const groups = new Map();
      for (const n of this.nodes) {
        if (n.kind !== "memory") continue;
        const g = n.project_id ? `p:${n.project_id}` : "none";
        if (!groups.has(g)) groups.set(g, []);
        groups.get(g).push(n.id);
      }
      for (const arr of groups.values()) {
        arr.sort();
        for (let i = 0; i < arr.length; i++) {
          for (let k = 1; k <= 2; k++) {
            const j = i + k;
            if (j >= arr.length) break;
            this.links.push({ source: arr[i], target: arr[j], kind: "sibling" });
          }
        }
      }
    }
    this._index();
    this.reheat(0.85);
    if (!prev.size) setTimeout(() => this.fitView(110), 620);
  }

  _index() {
    this.nodeById = new Map(this.nodes.map((n) => [n.id, n]));
    this.adjacency = new Map(this.nodes.map((n) => [n.id, new Set()]));
    for (const l of this.links) {
      this.adjacency.get(l.source)?.add(l.target);
      this.adjacency.get(l.target)?.add(l.source);
    }
    for (const n of this.nodes) n.degree = this.adjacency.get(n.id)?.size || 0;
  }

  neighbors(id) { return this.adjacency.get(id) || new Set(); }

  reheat(a = 0.55) { this.alpha = Math.max(this.alpha, a); this._dirty = true; }

  setVisibleFilter(fn) { this.visibleFilter = fn; this._dirty = true; }
  isVisible(n) { return !this.visibleFilter || this.visibleFilter(n); }

  /* ── 3D projection ── */
  _project(n) {
    // rotate Y then tilt X
    const cy = Math.cos(this.rotY), sy = Math.sin(this.rotY);
    const x1 = n.x * cy - n.z * sy;
    const z1 = n.x * sy + n.z * cy;
    const cx = Math.cos(this.rotX), sx = Math.sin(this.rotX);
    const y2 = n.y * cx - z1 * sx;
    const z2 = n.y * sx + z1 * cx;
    const s = this.focal / Math.max(80, this.focal + z2);
    n._sx = x1 * s;
    n._sy = y2 * s;
    n._ss = s;
    n._depth = Math.max(0, Math.min(1, (z2 + this.sphereR * 1.3) / (this.sphereR * 2.6)));
    return n;
  }

  _projectAll() {
    for (const n of this.nodes) this._project(n);
  }

  /* ── layout ── */
  fitView(pad = 70) {
    const cw = this.canvas.width / devicePixelRatio, ch = this.canvas.height / devicePixelRatio;
    const R = this.sphereR * 1.3;
    this.scale = Math.min(Math.min((cw - pad * 2) / (R * 2), (ch - pad * 2) / (R * 2)), 2.2);
    this.scale = Math.max(0.12, this.scale);
    this.panX = cw / 2;
    this.panY = ch / 2;
    this._dirty = true;
  }

  focusNode(id, zoomTo = 1.4) {
    const n = this.nodeById.get(id);
    if (!n) return;
    this._project(n);
    const target = zoomTo;
    const cw = this.canvas.width / devicePixelRatio, ch = this.canvas.height / devicePixelRatio;
    const startS = this.scale, startX = this.panX, startY = this.panY;
    const endS = target;
    const endX = cw / 2 - n._sx * endS, endY = ch / 2 - n._sy * endS;
    const t0 = performance.now();
    const anim = (t) => {
      const p = Math.min(1, (t - t0) / 380);
      const e = 1 - Math.pow(1 - p, 3);
      this.scale = startS + (endS - startS) * e;
      this.panX = startX + (endX - startX) * e;
      this.panY = startY + (endY - startY) * e;
      this._dirty = true;
      if (p < 1) requestAnimationFrame(anim);
    };
    requestAnimationFrame(anim);
    this.selected = n;
  }

  _step() {
    const vis = this.nodes.filter((n) => this.isVisible(n));
    const kRep = 900, kSpring = 0.022, gravity = 0.012, damping = 0.88;
    const a = this.alpha;
    const R = this.sphereR;

    // 3D repulsion (cutoff lớn hơn để giữ hình cầu)
    for (let i = 0; i < vis.length; i++) {
      const A = vis[i];
      for (let j = i + 1; j < vis.length; j++) {
        const B = vis[j];
        let dx = B.x - A.x, dy = B.y - A.y, dz = B.z - A.z;
        let d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; dy = Math.random() - 0.5; dz = Math.random() - 0.5; }
        if (d2 > 260000) continue;
        const f = (kRep * a) / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f, fz = (dz / d) * f;
        A.vx -= fx; A.vy -= fy; A.vz -= fz;
        B.vx += fx; B.vy += fy; B.vz += fz;
      }
    }
    // 3D springs
    for (const l of this.links) {
      const s = this.nodeById.get(typeof l.source === "string" ? l.source : l.source.id);
      const t = this.nodeById.get(typeof l.target === "string" ? l.target : l.target.id);
      if (!s || !t || !this.isVisible(s) || !this.isVisible(t)) continue;
      const targetLen = l.kind === "chunk_of" ? 36 : l.kind === "has_document" ? 88 : l.kind === "sibling" ? 120 : 72;
      const dx = t.x - s.x, dy = t.y - s.y, dz = t.z - s.z;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy + dz * dz), 0.01);
      const f = (kSpring * a * (d - targetLen));
      const fx = (dx / d) * f, fy = (dy / d) * f, fz = (dz / d) * f;
      s.vx += fx; s.vy += fy; s.vz += fz;
      t.vx -= fx; t.vy -= fy; t.vz -= fz;
    }
    // sphere constraint 3D — kéo về vỏ cầu
    for (const n of vis) {
      if (n.fixed && n !== this.dragNode) { n.vx = n.vy = n.vz = 0; continue; }
      const d = Math.sqrt(n.x * n.x + n.y * n.y + n.z * n.z) || 1;
      if (d > R * 1.02) {
        const pull = (d - R * 0.98) * 0.035 * a;
        n.vx -= (n.x / d) * pull;
        n.vy -= (n.y / d) * pull;
        n.vz -= (n.z / d) * pull;
      } else if (this.sphereMode) {
        n.vx += -n.x * gravity * a * 0.45;
        n.vy += -n.y * gravity * a * 0.45;
        n.vz += -n.z * gravity * a * 0.45;
      } else {
        n.vx += -n.x * gravity * a;
        n.vy += -n.y * gravity * a;
        n.vz += -n.z * gravity * a;
      }
      const cap = (v) => Math.max(-22, Math.min(22, v));
      n.x += cap(n.vx) * damping;
      n.y += cap(n.vy) * damping;
      n.z += cap(n.vz) * damping;
      n.vx *= damping; n.vy *= damping; n.vz *= damping;
    }
    if (this.dragNode) {
      this.dragNode.x = this.dragNode.fx;
      this.dragNode.y = this.dragNode.fy;
      this.dragNode.z = this.dragNode.fz ?? this.dragNode.z;
    }
    this.alpha = Math.max(this.alpha - 0.007, 0);
  }

  /* ── render ── */
  _frame() {
    if (this.alpha > 0.004) { this._step(); this._dirty = true; }
    // auto-spin quả cầu khi không chọn node (dừng khi focus để đọc)
    if (!this.selected && !this.dragNode && !this.rotating) {
      this.rotY += 0.0016;
      this._dirty = true;
    }
    // mạng neuron luôn sống: xung + thở cần vẽ mỗi frame
    if (this.nodes.length) {
      this._t += 1 / 60;
      this._dirty = true;
    }
    if (this._dirty) { this.render(); this._dirty = false; }
    requestAnimationFrame(() => this._frame());
  }

  render() {
    const ctx = this.ctx, dpr = devicePixelRatio;
    const cw = this.canvas.width / dpr, ch = this.canvas.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);

    // starfield nền — nhấp nháy nhẹ
    for (const st of this._stars) {
      const tw = 0.25 + 0.55 * (0.5 + 0.5 * Math.sin(this._t * st.sp + st.ph));
      ctx.globalAlpha = tw * 0.5;
      ctx.fillStyle = "#bae6fd";
      ctx.beginPath(); ctx.arc(st.x * cw, st.y * ch, st.r, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;

    this._projectAll();
    const vis = this.nodes.filter((n) => this.isVisible(n));
    // painter's algorithm: vẽ từ xa tới gần
    vis.sort((a, b) => a._depth - b._depth);

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    const focusId = this.hovered?.id || this.selected?.id || null;
    const near = focusId ? this.neighbors(focusId) : null;

    // ——— MOON BASE SPHERE 3D ———
    const R = this.sphereR;
    const halo = ctx.createRadialGradient(0, 0, R * 0.62, 0, 0, R * 1.62);
    halo.addColorStop(0, "rgba(56,189,248,0.00)");
    halo.addColorStop(0.62, "rgba(56,189,248,0.08)");
    halo.addColorStop(0.78, "rgba(56,189,248,0.16)");
    halo.addColorStop(0.88, "rgba(56,189,248,0.22)");
    halo.addColorStop(0.94, "rgba(56,189,248,0.10)");
    halo.addColorStop(1, "rgba(2,15,31,0.0)");
    ctx.fillStyle = halo;
    ctx.beginPath(); ctx.arc(0, 0, R * 1.62, 0, Math.PI * 2); ctx.fill();
    // main sphere body
    const sphereGrad = ctx.createRadialGradient(-R * 0.14, -R * 0.16, R * 0.11, 0, 0, R);
    sphereGrad.addColorStop(0, "#a5f3fc");
    sphereGrad.addColorStop(0.07, "#7dd3fc");
    sphereGrad.addColorStop(0.15, "#38bdf8");
    sphereGrad.addColorStop(0.26, "#0e7490");
    sphereGrad.addColorStop(0.52, "#0a2e4a");
    sphereGrad.addColorStop(0.76, "#071a2e");
    sphereGrad.addColorStop(1, "#020f1f");
    ctx.fillStyle = sphereGrad;
    ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2); ctx.fill();
    // 3D wireframe: vĩ tuyến + kinh tuyến xoay theo rotY
    ctx.strokeStyle = "rgba(56,189,248,0.07)"; ctx.lineWidth = 0.6;
    for (let k = 1; k <= 4; k++) {
      ctx.beginPath(); ctx.arc(0, 0, R * (k / 5), 0, Math.PI * 2); ctx.stroke();
    }
    for (let k = 0; k < 4; k++) {
      const a = this.rotY + (k * Math.PI) / 4;
      const rx = Math.abs(Math.cos(a)) * R;
      if (rx < 4) continue;
      ctx.strokeStyle = "rgba(56,189,248,0.08)";
      ctx.beginPath(); ctx.ellipse(0, 0, rx, R, 0, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(56,189,248,0.18)"; ctx.lineWidth = 1.1; ctx.stroke();
    ctx.strokeStyle = "rgba(255,255,255,0.09)"; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.arc(0, 0, R, Math.PI * 0.62, Math.PI * 1.38); ctx.stroke();

    // links — mờ dần theo độ sâu
    for (const l of this.links) {
      const s = this.nodeById.get(l.source), t = this.nodeById.get(l.target);
      if (!s || !t || !this.isVisible(s) || !this.isVisible(t)) continue;
      const depth = Math.min(s._depth, t._depth);
      const isFocusEdge = focusId && (l.source === focusId || l.target === focusId);
      const pcol = (l.kind === "belongs_to" || l.kind === "has_document")
        ? (this.nodeById.get(l.kind === "belongs_to" ? l.target : l.source)?._pcol || null)
        : null;
      ctx.beginPath();
      ctx.moveTo(s._sx, s._sy);
      const mx = (s._sx + t._sx) / 2, my = (s._sy + t._sy) / 2;
      const curve = l.kind === "chunk_of" ? 7 : 0;
      ctx.quadraticCurveTo(mx + curve, my - curve, t._sx, t._sy);
      const back = 0.25 + 0.75 * depth; // node xa -> mờ
      if (focusId && !isFocusEdge) {
        ctx.strokeStyle = "rgba(56,90,110,0.08)";
        ctx.lineWidth = 0.35;
      } else if (pcol && !isFocusEdge) {
        ctx.strokeStyle = pcol + Math.round(34 * back).toString(16).padStart(2, "0");
        ctx.lineWidth = 0.42;
      } else if (l.kind === "chunk_of") {
        ctx.strokeStyle = isFocusEdge ? "rgba(251,146,60,0.55)" : `rgba(56,189,248,${0.13 * back})`;
        ctx.lineWidth = isFocusEdge ? 0.9 : 0.32;
      } else if (l.kind === "has_document") {
        ctx.strokeStyle = isFocusEdge ? "rgba(167,139,250,0.65)" : `rgba(56,189,248,${0.16 * back})`;
        ctx.lineWidth = isFocusEdge ? 1.0 : 0.38;
      } else {
        ctx.strokeStyle = isFocusEdge ? "rgba(165,243,252,0.62)" : `rgba(56,189,248,${0.11 * back})`;
        ctx.lineWidth = isFocusEdge ? 0.85 : 0.30;
      }
      ctx.stroke();
    }

    // neural pulses — xung điện chạy dọc synapse (giới hạn để giữ fps)
    {
      const maxP = this.nodes.length > 800 ? 220 : 420;
      const step = Math.max(1, Math.floor(this.links.length / maxP));
      let pi = 0;
      for (let li = 0; li < this.links.length; li += step) {
        const l = this.links[li];
        const s = this.nodeById.get(l.source), t = this.nodeById.get(l.target);
        if (!s || !t || !this.isVisible(s) || !this.isVisible(t)) continue;
        if (focusId && l.source !== focusId && l.target !== focusId) continue;
        const speed = 0.12 + (pi % 5) * 0.03;
        const off = (this._t * speed + (pi * 0.61803)) % 1;
        const px = s._sx + (t._sx - s._sx) * off;
        const py = s._sy + (t._sy - s._sy) * off;
        const pcol = s._pcol || t._pcol || "#67e8f9";
        const pr = (1.1 + (s._depth + t._depth) * 0.9) * (0.8 + 0.4 * Math.sin(this._t * 6 + pi));
        ctx.save();
        ctx.globalAlpha = 0.35 + 0.55 * Math.min(s._depth, t._depth);
        ctx.shadowColor = pcol; ctx.shadowBlur = 9;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath(); ctx.arc(px, py, pr * 0.55, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
        ctx.fillStyle = pcol;
        ctx.beginPath(); ctx.arc(px, py, pr, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
        pi++;
      }
    }

    // nodes (đã sort xa -> gần) — neuron thở theo nhịp
    const showLabels = this.scale >= 0.62;
    for (const n of vis) {
      const dimmed = focusId && n.id !== focusId && !near.has(n.id);
      const breathe = 1 + 0.07 * Math.sin(this._t * 2.1 + (n._depth * 6.28) + n.x * 0.01);
      const r = this.radiusOf(n) * n._ss * breathe;
      ctx.globalAlpha = dimmed ? 0.16 : (0.38 + 0.62 * n._depth);
      this._drawShape(ctx, n, r);

      if (showLabels || n.kind === "project" || n === this.hovered || n === this.selected) {
        if (!(dimmed && n.kind !== "project")) {
          ctx.font = `${n.kind === "project" ? 600 : 400} ${n.kind === "project" ? 12 : 10.5}px Inter, Segoe UI, sans-serif`;
          ctx.textAlign = "center";
          const label = n.label.length > 26 ? n.label.slice(0, 25) + "…" : n.label;
          ctx.fillStyle = dimmed ? "rgba(139,143,156,0.35)" : n === this.selected ? "#fff" : "#c8cad1";
          ctx.shadowColor = "rgba(0,0,0,0.9)";
          ctx.shadowBlur = 4;
          ctx.fillText(label, n._sx, n._sy + r + 13);
          ctx.shadowBlur = 0;
        }
      }
      ctx.globalAlpha = 1;
    }
    // ripple quanh node đang chọn — tín hiệu lan tỏa
    if (this.selected && this.selected._sx !== undefined) {
      const sn = this.selected;
      for (let k = 0; k < 2; k++) {
        const ph = ((this._t * 0.7 + k * 0.5) % 1);
        ctx.save();
        ctx.globalAlpha = (1 - ph) * 0.5;
        ctx.strokeStyle = sn._pcol || "#ffffff";
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(sn._sx, sn._sy, (this.radiusOf(sn) * sn._ss + 6) + ph * 26, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }
    ctx.restore();
  }

  radiusOf(n) {
    if (n.kind === "project") return 5.5 + Math.min(4, n.degree * 0.55);
    if (n.kind === "document") return 3.8 + Math.min(2.5, n.degree * 0.42);
    const base = 1.6 + (n.importance || 0.5) * 1.9;
    return base + Math.min(1.8, n.degree * 0.22);
  }

  _drawShape(ctx, n, r) {
    const px = n._sx, py = n._sy;
    const pcol = n._pcol || null; // màu project (app.js gán)
    ctx.save();
    if (n.kind === "project") {
      const R = r * 1.15;
      const col = pcol || "#a78bfa";
      ctx.shadowColor = col; ctx.shadowBlur = 14;
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(px, py, R, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = "#ffffff"; ctx.globalAlpha = 0.92;
      ctx.beginPath(); ctx.arc(px - R * 0.18, py - R * 0.18, R * 0.32, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.arc(px, py, R, 0, Math.PI * 2); ctx.stroke();
      ctx.strokeStyle = col + "47"; ctx.lineWidth = 3.5;
      ctx.beginPath(); ctx.arc(px, py, R + 3, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
      if (n === this.hovered || n === this.selected) {
        ctx.beginPath(); ctx.arc(px, py, R + 6, 0, Math.PI * 2);
        ctx.strokeStyle = n === this.selected ? "#ffffffee" : col;
        ctx.lineWidth = n === this.selected ? 1.8 : 1.2; ctx.stroke();
      }
      return;
    }
    if (n.kind === "document") {
      const R = r * 1.1;
      const col = "#fb923c";
      // halo màu project — nhận biết project ngay trên sphere
      if (pcol) {
        ctx.strokeStyle = pcol + "66"; ctx.lineWidth = 2.4;
        ctx.beginPath(); ctx.arc(px, py, R + 2.6, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.shadowColor = col + "aa"; ctx.shadowBlur = 10;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(px, py - R);
      ctx.lineTo(px + R, py);
      ctx.lineTo(px, py + R);
      ctx.lineTo(px - R, py);
      ctx.closePath(); ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(255,255,255,0.78)"; ctx.lineWidth = 0.9; ctx.stroke();
      ctx.restore();
      if (n === this.hovered || n === this.selected) {
        ctx.beginPath(); ctx.arc(px, py, R + 5, 0, Math.PI * 2);
        ctx.strokeStyle = n === this.selected ? "#ffffffee" : col;
        ctx.lineWidth = 1.2; ctx.stroke();
      }
      return;
    }
    // memory — lõi màu theo type + vành project
    const col = window.FSB_COLORS ? window.FSB_COLORS(n) : "#60a5fa";
    if (pcol) {
      ctx.strokeStyle = pcol + "55"; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(px, py, r + 2.2, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.shadowColor = col; ctx.shadowBlur = 6;
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#ffffff";
    ctx.globalAlpha = 0.9;
    ctx.beginPath(); ctx.arc(px - r * 0.28, py - r * 0.28, r * 0.28, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.restore();
    if (n === this.hovered || n === this.selected) {
      ctx.beginPath(); ctx.arc(px, py, r + 3.2, 0, Math.PI * 2);
      ctx.strokeStyle = n === this.selected ? "#ffffffee" : col;
      ctx.lineWidth = n === this.selected ? 1.4 : 1.0; ctx.stroke();
    }
  }

  /* ── interaction ── */
  _toScreen(evt) {
    const rect = this.canvas.getBoundingClientRect();
    return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
  }
  _pick(sx, sy) {
    let best = null, bestD = Infinity;
    for (const n of this.nodes) {
      if (!this.isVisible(n) || n._sx === undefined) continue;
      const px = n._sx * this.scale + this.panX, py = n._sy * this.scale + this.panY;
      const dx = px - sx, dy = py - sy;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d < Math.max(this.radiusOf(n) * n._ss * this.scale + 5, 12) && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  _bind() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      this._lastPointer = { x: e.clientX, y: e.clientY };
      const s = this._toScreen(e);
      const hit = this._pick(s.x, s.y);
      if (hit) {
        this.dragNode = hit;
        hit.fixed = true;
        hit.fx = hit.x; hit.fy = hit.y; hit.fz = hit.z;
        this.reheat(0.35);
      } else if (e.shiftKey) {
        this.panning = true;
        c.classList.add("dragging");
      } else {
        this.rotating = true;
        c.classList.add("dragging");
      }
    });
    c.addEventListener("pointermove", (e) => {
      const s = this._toScreen(e);
      if (this.dragNode) {
        // kéo node trên mặt phẳng màn hình (giữ z)
        const dx = (e.clientX - this._lastPointer.x) / this.scale;
        const dy = (e.clientY - this._lastPointer.y) / this.scale;
        // đảo xoay Y để kéo đúng hướng nhìn
        const cy = Math.cos(-this.rotY), sy = Math.sin(-this.rotY);
        this.dragNode.fx = this.dragNode.x += (dx * cy) / (this.dragNode._ss || 1);
        this.dragNode.fy = this.dragNode.y += dy / (this.dragNode._ss || 1);
        this.dragNode.x = this.dragNode.fx;
        this.dragNode.y = this.dragNode.fy;
        this._lastPointer = { x: e.clientX, y: e.clientY };
        this.reheat(0.3);
        this._dirty = true;
        return;
      }
      if (this.rotating && this._lastPointer) {
        // kéo nền = xoay quả cầu 3D (Shift+kéo = pan)
        this.rotY += (e.clientX - this._lastPointer.x) * 0.005;
        this.rotX = Math.max(-1.2, Math.min(1.2, this.rotX + (e.clientY - this._lastPointer.y) * 0.005));
        this._lastPointer = { x: e.clientX, y: e.clientY };
        this._dirty = true;
        return;
      }
      if (this.panning && this._lastPointer) {
        this.panX += e.clientX - this._lastPointer.x;
        this.panY += e.clientY - this._lastPointer.y;
        this._lastPointer = { x: e.clientX, y: e.clientY };
        this._dirty = true;
        return;
      }
      const hit = this._pick(s.x, s.y);
      if (hit !== this.hovered) {
        this.hovered = hit;
        c.style.cursor = hit ? "pointer" : "grab";
        this.handlers.onHover?.(hit);
        this._dirty = true;
      }
    });
    c.addEventListener("pointerup", (e) => {
      if (this.dragNode) {
        if (!e.shiftKey) this.dragNode.fixed = false; // Shift = ghim node
        this.dragNode = null;
        this.reheat(0.18);
      }
      if (this.rotating || this.panning) {
        const moved = this._lastPointer
          ? Math.abs(e.clientX - this._lastPointer.x) + Math.abs(e.clientY - this._lastPointer.y)
          : 99;
        // click trống = bỏ chọn (spin tự chạy lại)
        if (moved < 400 && !this._pick(...(() => { const s = this._toScreen(e); return [s.x, s.y]; })())) {
          this.selected = null;
          this.handlers.onSelect?.(null);
          this._dirty = true;
        }
        this.rotating = false;
        this.panning = false;
        c.classList.remove("dragging");
        this._lastPointer = null;
        return;
      }
      // click node = chọn
      const s = this._toScreen(e);
      const hit = this._pick(s.x, s.y);
      this.selected = hit || null;
      this.handlers.onSelect?.(hit || null);
      this._dirty = true;
    });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const rect = c.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const factor = Math.exp(-e.deltaY * 0.0012);
      const ns = Math.max(0.12, Math.min(6, this.scale * factor));
      this.panX = mx - ((mx - this.panX) / this.scale) * ns;
      this.panY = my - ((my - this.panY) / this.scale) * ns;
      this.scale = ns;
      this._dirty = true;
    }, { passive: false });
    c.addEventListener("dblclick", () => this.fitView());
  }

  _resize() {
    const parent = this.canvas.parentElement;
    const dpr = devicePixelRatio || 1;
    this.canvas.width = parent.clientWidth * dpr;
    this.canvas.height = parent.clientHeight * dpr;
    this.canvas.style.width = parent.clientWidth + "px";
    this.canvas.style.height = parent.clientHeight + "px";
    this._dirty = true;
  }
}
