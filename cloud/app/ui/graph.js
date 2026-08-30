/* ══════════ Force-directed graph engine (canvas, zero deps) ══════════ */
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
    this.panning = false;
    this._lastPointer = null;
    this._dirty = true;

    this.visibleFilter = null; // (node)=>bool
    this.sphereR = 340; // moon base radius (world units)
    this.sphereMode = true;

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
    // fibonacci sphere projection -> phân bố đều trên quả cầu (moon base)
    const golden = Math.PI * (3 - Math.sqrt(5));
    this.nodes = nodes.map((n, i) => {
      const old = prev.get(n.id);
      if (old) return { ...n, x: old.x, y: old.y, vx: 0, vy: 0, fixed: old.fixed, _theta: old._theta, _phi: old._phi };
      // phân phối đều trên sphere (y = 1 - 2i/N)
      const y = 1 - (i / Math.max(1, N - 1)) * 2;
      const radius = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = golden * i;
      const x = Math.cos(theta) * radius;
      const z = Math.sin(theta) * radius;
      // orthographic projection: y -> y, x -> x (z dùng cho độ sâu / alpha)
      const px = x * R * (0.72 + Math.random() * 0.28);
      const py = y * R * (0.72 + Math.random() * 0.28);
      // project nodes: 85% trên vỏ sphere, 15% lõi
      const isCore = Math.random() < 0.15;
      const rFac = isCore ? (0.18 + Math.random() * 0.55) : (0.82 + Math.random() * 0.18);
      return {
        ...n,
        x: px * rFac,
        y: py * rFac,
        vx: 0,
        vy: 0,
        fixed: false,
        _theta: theta,
        _phi: Math.acos(y),
        _z: z,
      };
    });
    const ids = new Set(nodes.map((n) => n.id));
    this.links = links.filter((l) => {
      const s = typeof l.source === "string" ? l.source : l.source.id;
      const t = typeof l.target === "string" ? l.target : l.target.id;
      return ids.has(s) && ids.has(t);
    });
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

  /* ── layout ── */
  fitView(pad = 70) {
    const vis = this.nodes.filter((n) => this.isVisible(n));
    if (!vis.length) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of vis) {
      x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y);
      x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y);
    }
    const w = Math.max(x1 - x0, 60), h = Math.max(y1 - y0, 60);
    const cw = this.canvas.width / devicePixelRatio, ch = this.canvas.height / devicePixelRatio;
    this.scale = Math.min(Math.min((cw - pad * 2) / w, (ch - pad * 2) / h), 2.2);
    this.panX = cw / 2 - ((x0 + x1) / 2) * this.scale;
    this.panY = ch / 2 - ((y0 + y1) / 2) * this.scale;
    this._dirty = true;
  }

  focusNode(id, zoomTo = 1.4) {
    const n = this.nodeById.get(id);
    if (!n) return;
    const target = zoomTo;
    const cw = this.canvas.width / devicePixelRatio, ch = this.canvas.height / devicePixelRatio;
    // animate pan/scale quickly
    const startS = this.scale, startX = this.panX, startY = this.panY;
    const endS = target;
    const endX = cw / 2 - n.x * endS, endY = ch / 2 - n.y * endS;
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

    // repulsion nhẹ hơn để giữ hình cầu (cutoff lớn hơn)
    for (let i = 0; i < vis.length; i++) {
      const A = vis[i];
      for (let j = i + 1; j < vis.length; j++) {
        const B = vis[j];
        let dx = B.x - A.x, dy = B.y - A.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; dy = Math.random() - 0.5; }
        if (d2 > 220000) continue;
        const f = (kRep * a) / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        A.vx -= fx; A.vy -= fy;
        B.vx += fx; B.vy += fy;
      }
    }
    // springs
    for (const l of this.links) {
      const s = this.nodeById.get(typeof l.source === "string" ? l.source : l.source.id);
      const t = this.nodeById.get(typeof l.target === "string" ? l.target : l.target.id);
      if (!s || !t || !this.isVisible(s) || !this.isVisible(t)) continue;
      const targetLen = l.kind === "chunk_of" ? 36 : l.kind === "has_document" ? 88 : 72;
      const dx = t.x - s.x, dy = t.y - s.y;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
      const f = (kSpring * a * (d - targetLen));
      const fx = (dx / d) * f, fy = (dy / d) * f;
      s.vx += fx; s.vy += fy;
      t.vx -= fx; t.vy -= fy;
    }
    // sphere constraint — kéo về vỏ cầu moon base + slow rotation
    const rot = 0.00055 * a;
    for (const n of vis) {
      if (n.fixed && n !== this.dragNode) { n.vx = n.vy = 0; continue; }
      const d = Math.sqrt(n.x * n.x + n.y * n.y) || 1;
      // giữ trong cầu
      if (d > R * 1.02) {
        const pull = (d - R * 0.98) * 0.035 * a;
        n.vx -= (n.x / d) * pull;
        n.vy -= (n.y / d) * pull;
      } else if (this.sphereMode) {
        n.vx += -n.x * gravity * a * 0.45;
        n.vy += -n.y * gravity * a * 0.45;
      } else {
        n.vx += -n.x * gravity * a;
        n.vy += -n.y * gravity * a;
      }
      // xoay nhẹ quanh tâm (orbit)
      if (this.sphereMode && a > 0.02 && !n.fixed) {
        const ang = Math.atan2(n.y, n.x) + rot;
        const rad = d;
        const nx = Math.cos(ang) * rad;
        const ny = Math.sin(ang) * rad;
        n.vx += (nx - n.x) * 0.08;
        n.vy += (ny - n.y) * 0.08;
      }
      n.x += Math.max(-22, Math.min(22, n.vx)) * damping;
      n.y += Math.max(-22, Math.min(22, n.vy)) * damping;
      n.vx *= damping; n.vy *= damping;
    }
    if (this.dragNode) {
      this.dragNode.x = this.dragNode.fx;
      this.dragNode.y = this.dragNode.fy;
    }
    this.alpha = Math.max(this.alpha - 0.007, 0);
  }

  /* ── render ── */
  _frame() {
    if (this.alpha > 0.004) { this._step(); this._dirty = true; }
    if (this._dirty) { this.render(); this._dirty = false; }
    requestAnimationFrame(() => this._frame());
  }

  render() {
    const ctx = this.ctx, dpr = devicePixelRatio;
    const cw = this.canvas.width / dpr, ch = this.canvas.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    const focusId = this.hovered?.id || this.selected?.id || null;
    const near = focusId ? this.neighbors(focusId) : null;

    // ——— MOON BASE SPHERE ——— (nền quả cầu như ảnh mẫu)
    const R = this.sphereR;
    // outer halo — làm rõ hơn
    const halo = ctx.createRadialGradient(0, 0, R * 0.62, 0, 0, R * 1.62);
    halo.addColorStop(0, "rgba(56,189,248,0.00)");
    halo.addColorStop(0.62, "rgba(56,189,248,0.08)");
    halo.addColorStop(0.78, "rgba(56,189,248,0.16)");
    halo.addColorStop(0.88, "rgba(56,189,248,0.22)");
    halo.addColorStop(0.94, "rgba(56,189,248,0.10)");
    halo.addColorStop(1, "rgba(2,15,31,0.0)");
    ctx.fillStyle = halo;
    ctx.beginPath(); ctx.arc(0, 0, R * 1.62, 0, Math.PI * 2); ctx.fill();
    // main sphere body — lõi xanh thu nhỏ 0.5x
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
    // subtle latitude/longitude grid (moon base)
    ctx.strokeStyle = "rgba(56,189,248,0.06)"; ctx.lineWidth = 0.6;
    for (let k = 1; k <= 4; k++) {
      ctx.beginPath(); ctx.arc(0, 0, R * (k / 5), 0, Math.PI * 2); ctx.stroke();
    }
    ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(56,189,248,0.18)"; ctx.lineWidth = 1.1; ctx.stroke();
    // terminator highlight (sun rim)
    ctx.strokeStyle = "rgba(255,255,255,0.09)"; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.arc(0, 0, R, Math.PI * 0.62, Math.PI * 1.38); ctx.stroke();

    // links — ultra-thin cyan web như ảnh (rất mờ)
    for (const l of this.links) {
      const s = this.nodeById.get(l.source), t = this.nodeById.get(l.target);
      if (!s || !t || !this.isVisible(s) || !this.isVisible(t)) continue;
      const isFocusEdge = focusId && (l.source === focusId || l.target === focusId);
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
      const curve = l.kind === "chunk_of" ? 7 : 0;
      ctx.quadraticCurveTo(mx + curve, my - curve, t.x, t.y);
      if (focusId && !isFocusEdge) {
        ctx.strokeStyle = "rgba(56,90,110,0.08)";
        ctx.lineWidth = 0.35;
      } else if (l.kind === "chunk_of") {
        ctx.strokeStyle = isFocusEdge ? "rgba(251,146,60,0.55)" : "rgba(56,189,248,0.13)";
        ctx.lineWidth = isFocusEdge ? 0.9 : 0.32;
      } else if (l.kind === "has_document") {
        ctx.strokeStyle = isFocusEdge ? "rgba(167,139,250,0.65)" : "rgba(56,189,248,0.16)";
        ctx.lineWidth = isFocusEdge ? 1.0 : 0.38;
      } else {
        ctx.strokeStyle = isFocusEdge ? "rgba(165,243,252,0.62)" : "rgba(56,189,248,0.11)";
        ctx.lineWidth = isFocusEdge ? 0.85 : 0.30;
      }
      ctx.stroke();
    }

    // nodes
    const showLabels = this.scale >= 0.62;
    for (const n of this.nodes) {
      if (!this.isVisible(n)) continue;
      const dimmed = focusId && n.id !== focusId && !near.has(n.id);
      const r = this.radiusOf(n);
      ctx.globalAlpha = dimmed ? 0.16 : 1;
      this._drawShape(ctx, n, r);

      if (showLabels || n.kind === "project" || n === this.hovered || n === this.selected) {
        if (!(dimmed && n.kind !== "project")) {
          ctx.font = `${n.kind === "project" ? 600 : 400} ${n.kind === "project" ? 12 : 10.5}px Inter, Segoe UI, sans-serif`;
          ctx.textAlign = "center";
          const label = n.label.length > 26 ? n.label.slice(0, 25) + "…" : n.label;
          ctx.fillStyle = dimmed ? "rgba(139,143,156,0.35)" : n === this.selected ? "#fff" : "#c8cad1";
          ctx.shadowColor = "rgba(0,0,0,0.9)";
          ctx.shadowBlur = 4;
          ctx.fillText(label, n.x, n.y + r + 13);
          ctx.shadowBlur = 0;
        }
      }
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }

  radiusOf(n) {
    // moon base: tiny dots như ảnh — project hubs to hơn, còn lại li ti
    if (n.kind === "project") return 5.5 + Math.min(4, n.degree * 0.55);
    if (n.kind === "document") return 3.8 + Math.min(2.5, n.degree * 0.42);
    const base = 1.6 + (n.importance || 0.5) * 1.9;
    return base + Math.min(1.8, n.degree * 0.22);
  }

  _drawShape(ctx, n, r) {
    // MOON BASE — tiny luminous dots on sphere (như ảnh mẫu)
    ctx.save();
    if (n.kind === "project") {
      const R = r * 1.15;
      const col = "#a78bfa";
      ctx.shadowColor = col; ctx.shadowBlur = 14;
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(n.x, n.y, R, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0;
      // inner bright core
      ctx.fillStyle = "#ffffff"; ctx.globalAlpha = 0.92;
      ctx.beginPath(); ctx.arc(n.x - R * 0.18, n.y - R * 0.18, R * 0.32, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.arc(n.x, n.y, R, 0, Math.PI * 2); ctx.stroke();
      // hub ring
      ctx.strokeStyle = "rgba(167,139,250,0.28)"; ctx.lineWidth = 3.5;
      ctx.beginPath(); ctx.arc(n.x, n.y, R + 3, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
      if (n === this.hovered || n === this.selected) {
        ctx.beginPath(); ctx.arc(n.x, n.y, R + 6, 0, Math.PI * 2);
        ctx.strokeStyle = n === this.selected ? "#ffffffee" : col;
        ctx.lineWidth = n === this.selected ? 1.8 : 1.2; ctx.stroke();
      }
      return;
    }
    if (n.kind === "document") {
      const R = r * 1.1;
      const col = "#fb923c";
      ctx.shadowColor = col + "aa"; ctx.shadowBlur = 10;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(n.x, n.y - R);
      ctx.lineTo(n.x + R, n.y);
      ctx.lineTo(n.x, n.y + R);
      ctx.lineTo(n.x - R, n.y);
      ctx.closePath(); ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(255,255,255,0.78)"; ctx.lineWidth = 0.9; ctx.stroke();
      ctx.restore();
      if (n === this.hovered || n === this.selected) {
        ctx.beginPath(); ctx.arc(n.x, n.y, R + 5, 0, Math.PI * 2);
        ctx.strokeStyle = n === this.selected ? "#ffffffee" : col;
        ctx.lineWidth = 1.2; ctx.stroke();
      }
      return;
    }
    // memory — dot nhỏ màu theo type (đúng legend: semantic xanh, episodic xanh lá, decision hồng...)
    const col = window.FSB_COLORS ? window.FSB_COLORS(n) : "#60a5fa";
    // depth shading: nodes ở rìa tối hơn (dựa trên khoảng cách tới tâm)
    const dist = Math.sqrt(n.x * n.x + n.y * n.y) / this.sphereR;
    const dim = 0.88 + 0.12 * (1 - Math.min(1, dist));
    ctx.shadowColor = col; ctx.shadowBlur = 6;
    ctx.globalAlpha = 0.92 * dim + 0.08;
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2); ctx.fill();
    // specular highlight nhỏ
    ctx.shadowBlur = 0; ctx.globalAlpha = 0.95 * dim;
    ctx.fillStyle = "#ffffff";
    ctx.beginPath(); ctx.arc(n.x - r * 0.28, n.y - r * 0.28, r * 0.28, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.restore();
    if (n === this.hovered || n === this.selected) {
      ctx.beginPath(); ctx.arc(n.x, n.y, r + 3.2, 0, Math.PI * 2);
      ctx.strokeStyle = n === this.selected ? "#ffffffee" : col;
      ctx.lineWidth = n === this.selected ? 1.4 : 1.0; ctx.stroke();
    }
  }

  /* ── interaction ── */
  _toWorld(evt) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: (evt.clientX - rect.left - this.panX) / this.scale,
      y: (evt.clientY - rect.top - this.panY) / this.scale,
    };
  }
  _pick(wx, wy) {
    let best = null, bestD = Infinity;
    for (const n of this.nodes) {
      if (!this.isVisible(n)) continue;
      const dx = n.x - wx, dy = n.y - wy;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d < Math.max(this.radiusOf(n) + 5, 12) && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  _bind() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      this._lastPointer = { x: e.clientX, y: e.clientY };
      const w = this._toWorld(e);
      const hit = this._pick(w.x, w.y);
      if (hit) {
        this.dragNode = hit;
        hit.fixed = true;
        hit.fx = hit.x; hit.fy = hit.y;
        this.reheat(0.35);
      } else {
        this.panning = true;
        c.classList.add("dragging");
      }
    });
    c.addEventListener("pointermove", (e) => {
      const w = this._toWorld(e);
      if (this.dragNode) {
        this.dragNode.fx = w.x; this.dragNode.fy = w.y;
        this.dragNode.x = w.x; this.dragNode.y = w.y;
        this.reheat(0.3);
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
      const hit = this._pick(w.x, w.y);
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
      if (this.panning) {
        const moved = Math.abs(e.clientX - this._lastPointer.x) + Math.abs(e.clientY - this._lastPointer.y);
        if (moved < 4) {
          // click trống = bỏ chọn
          this.selected = null;
          this.handlers.onSelect?.(null);
          this._dirty = true;
        }
        this.panning = false;
        c.classList.remove("dragging");
        return;
      }
      // click node = chọn
      const w = this._toWorld(e);
      const hit = this._pick(w.x, w.y);
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
