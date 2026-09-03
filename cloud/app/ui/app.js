/* ══════════ First⟷Second Brain Control Center — app logic ══════════ */
"use strict";

const TYPE_COLORS = {
  // legend khớp ảnh: semantic xanh dương, episodic xanh lá, decision hồng, lesson đỏ hồng, document cam, task cyan/xanh ngọc
  semantic: "#60a5fa", episodic: "#34d399", procedural: "#fbbf24",
  decision: "#f472b6", lesson: "#fb7185", project: "#c084fc",
  document: "#fb923c", task: "#22d3ee", preference: "#e879f9",
};
const TYPE_ORDER = ["document","lesson","decision","episodic","semantic","task","procedural","preference"];
// ONE VECTOR PLATFORM — mỗi domain 1 màu riêng trên graph 3D
const DOMAIN_COLORS = {
  project: "#c084fc", engineering: "#60a5fa", standard: "#2dd4bf", contract: "#fbbf24",
  method: "#fb7185", site: "#a3e635", document: "#fb923c", lesson: "#f472b6",
};
window.FSB_COLORS = (n) => {
  if (n.kind === "project") return n._pcol || "#a78bfa";
  const kt = n.knowledge_type;
  if (kt && DOMAIN_COLORS[kt]) return DOMAIN_COLORS[kt];
  if (n.kind === "document") return "#fb923c";
  return TYPE_COLORS[n.type] || "#94a3b8";
};

/* ─────────── per-project colors (3D graph) ─────────── */
const PROJECT_PALETTE = ["#a78bfa","#22d3ee","#fbbf24","#f472b6","#34d399","#fb923c","#60a5fa","#e879f9","#a3e635","#f87171","#2dd4bf","#facc15"];
const projectColorMap = new Map(); // "p:<uuid>" -> hex (giữ ổn định giữa các lần reload)
function assignProjectColors(nodes) {
  const order = [];
  for (const n of nodes) {
    if (n.kind === "project" && !order.includes(n.id)) order.push(n.id);
  }
  for (const n of nodes) {
    const pid = n.project_id ? `p:${n.project_id}` : null;
    if (pid && !order.includes(pid)) order.push(pid);
  }
  for (const pid of order) {
    if (!projectColorMap.has(pid)) {
      projectColorMap.set(pid, PROJECT_PALETTE[projectColorMap.size % PROJECT_PALETTE.length]);
    }
  }
  const names = {};
  for (const n of nodes) if (n.kind === "project") names[n.id] = n.label;
  for (const n of nodes) {
    const pid = n.kind === "project" ? n.id : (n.project_id ? `p:${n.project_id}` : null);
    n._pcol = pid ? (projectColorMap.get(pid) || null) : null;
    n._pname = pid ? (names[pid] || pid.slice(2, 10)) : null;
  }
}

const state = {
  apiKey: localStorage.getItem("fsb.apiKey") || "",
  graph: { nodes: [], links: [], stats: null },
  selected: null,
  filters: {
    kinds: new Set(["project", "memory", "document"]),
    types: new Set(Object.keys(TYPE_COLORS)),
    minImportance: 0,
    text: "",
  },
  lastAuditId: null,
  refreshing: false,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function toast(msg, isErr = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = msg;
  $("#toast-zone").appendChild(el);
  setTimeout(() => el.remove(), 3600);
}

async function api(path, options = {}) {
  const headers = { "X-API-Key": state.apiKey, ...(options.headers || {}) };
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) { showKeyModal(); throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json())?.error?.message || ""; } catch { /* ignore */ }
    throw new Error(`HTTP ${res.status} ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

/* ─────────── key modal ─────────── */
function showKeyModal() { $("#key-modal").classList.remove("hidden"); $("#key-input").focus(); }

$("#key-save").addEventListener("click", async () => {
  const key = $("#key-input").value.trim() || "dev-local-key";
  try {
    const res = await fetch("/health");
    if (!res.ok) throw new Error();
    const probe = await fetch("/v1/graph/status", { headers: { "X-API-Key": key } });
    if (!probe.ok) throw new Error();
    state.apiKey = key;
    localStorage.setItem("fsb.apiKey", key);
    $("#key-modal").classList.add("hidden");
    $("#key-error").classList.add("hidden");
    bootstrap();
  } catch {
    $("#key-error").classList.remove("hidden");
  }
});
$("#key-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#key-save").click(); });

/* ─────────── status pills / bridge + widget (spec 3.1-3.3) ─────────── */
let widgetState = { first: "idle", mid: "idle", second: "idle", network: "offline" };
function setWidgetState(which, state, text) {
  const el = document.getElementById(`widget-${which}`);
  if (!el) return;
  const icons = { idle: "○", processing: "⚡", routing: "⬢", querying: "◉", success: "✓", online: "●", offline: "○" };
  const cls = { idle: "muted", processing: "processing", routing: "routing", querying: "querying", success: "success", online: "online", offline: "offline" };
  el.className = `widget-val ${cls[state] || "muted"}`;
  el.innerHTML = `<i class="sicon">${icons[state] || "○"}</i> ${text}`;
  widgetState[which] = state;
  if (state === "success") setTimeout(()=> setWidgetState(which,"idle","Idle · Ready"), 1200);
}

function updateWidget({ isOnline, emb, s, mid }) {
  // isOnline here is now isNetworkOnline — true if API fetched, false only if fetch fails
  // AI online is separate: emb.provider !== 'hash'
  const isNetworkOnline = isOnline !== undefined ? isOnline : (typeof navigator !== 'undefined' ? navigator.onLine !== false : true);
  const isAIOnline = emb && emb.provider !== 'hash' && emb.reachable;
  const net = document.getElementById("widget-network");
  if (!net) return;
  // 1. Chế độ kết nối — theo Second Brain (yêu cầu: Second Brain bình thường=Online, sự cố=Offline)
  const netOnline = isNetworkOnline;
  net.className = `widget-val ${netOnline ? "online" : "offline"}`;
  net.innerHTML = `<i class="wdot"></i> ${netOnline ? "Online Mode" : "Offline Mode"}`;
  net.title = `Second Brain:${netOnline?'healthy':'offline'} · AI:${isAIOnline?'cloud':'local'} · ${emb.provider}:${emb.model} ${emb.dimension}d`;
  // ⚡ First Brain — Idle / Processing / Success
  const fbWrites = s?.counts?.first_brain_writes ?? 0;
  const firstState = isOnline ? "processing" : (fbWrites ? "processing" : "idle");
  const firstText = isOnline ? `Ingesting… · ${fbWrites} writes` : (fbWrites ? `Ingesting data…` : "Idle · Ready");
  // keep Success if recently triggered, else update
  if (widgetState.first !== "success") setWidgetState("first", firstState === "processing" && !isOnline && fbWrites===0 ? "idle" : firstState, firstText);
  // 🧩 Mid Brain — Idle / Routing
  const healthy = mid && mid.status === "healthy";
  setWidgetState("mid", healthy ? "routing" : "idle", healthy ? "Analyzing context…" : "Idle · Ready");
  // 📚 Second Brain — Idle / Querying
  const mem = s?.counts?.memories ?? 0;
  // second will be set to querying during search — default idle
  if (widgetState.second !== "querying") setWidgetState("second", mem ? "idle" : "idle", mem ? `Ready · ${mem} memories` : "Idle · Ready");
  document.getElementById("widget-second").title = `${s?.backend || "sqlite"} · ${s?.counts?.documents || 0} docs`;
}



// Hook: when audit shows new memory.write, flash First → Mid → Second flow
function triggerBrainFlow() {
  setWidgetState("first","processing","Ingesting data…");
  setTimeout(()=> setWidgetState("mid","routing","Structuring thoughts…"), 400);
  setTimeout(()=> setWidgetState("second","querying","Retrieving long-term…"), 900);
  setTimeout(()=> { setWidgetState("first","success","Success ✓"); setWidgetState("mid","idle","Idle · Ready"); setWidgetState("second","idle","Idle · Ready"); }, 1800);
}

async function loadMidBrainStatus() {
  try {
    const m = await api("/v1/mid-brain/health");
    const ok = m.status === "healthy";
    const comps = Object.keys(m.components || {}).length;
    const up = fmtDuration(m.uptime_seconds || 0);
    $("#mid-status").textContent = ok ? `${comps} comps · up ${up}` : `degraded`;
    $("#mid-status").title = ok ? `intelligence · ${Object.keys(m.components||{}).join(", ")}` : (m.last_error||"");
    $("#node-mid").className = `bridge-node mid ${ok ? "online" : "offline"}`;
    const pill = $("#pill-mid");
    pill.className = `pill ${ok ? "ok" : "warn"}`;
    pill.innerHTML = `<span class="dot ${ok ? "green" : "amber"}"></span><span>Mid ${ok ? "healthy" : "init"} v${esc(m.version || "")}</span>`;
    pill.title = Object.entries(m.components || {}).map(([k,v])=>`${k}:${v?"✓":"✗"}`).join(" · ");
    // widget also — network is online if we fetched health, AI is mid ok
    const s = { counts: { memories: 0, documents: 0 } };
    const emb = { provider: ok ? "mid" : "unknown", model: "", dimension: 0, reachable: ok };
    updateWidget({ isOnline: true, emb, s, mid: m });
    return m;
  } catch (e) {
    $("#mid-status").textContent = "intelligence · offline";
    $("#node-mid").className = "bridge-node mid offline";
    const pill = $("#pill-mid");
    pill.className = "pill err";
    pill.innerHTML = `<span class="dot red"></span><span>Mid offline</span>`;
    // network may still be online even if Mid fails
    const netOnline = typeof navigator !== 'undefined' ? navigator.onLine !== false : true;
    updateWidget({ isOnline: netOnline, emb: {provider:"hash",model:"",dimension:384,reachable:false}, s:{counts:{memories:0,documents:0}}, mid: null });
    return null;
  }
}

async function loadStatus() {
  try {
    const s = await api("/v1/graph/status");
    const apiPill = $("#pill-api");
    apiPill.innerHTML = `<span class="dot green"></span><span>API ${s.version} · up ${fmtDuration(s.uptime_seconds)}</span>`;
    apiPill.title = `API reachable`;
    const emb = s.embedding;
    const isAIOnline = emb.provider !== "hash" && emb.reachable;
    const isNetworkOnline = true; // fetch succeeded => local API reachable => online
    const mode = isAIOnline ? "ONLINE" : "OFFLINE";
    const modePill = $("#pill-mode");
    modePill.className = `pill ${isAIOnline ? "online" : "offline"}`;
    modePill.innerHTML = `<span class="dot ${isAIOnline ? "green" : "amber"}"></span><span>${mode} · ${esc(emb.provider)}</span>`;
    modePill.title = `AI:${isAIOnline?'cloud':'local'} · ${emb.provider}:${emb.model} ${emb.dimension}d · ${emb.reachable?"reachable":"hash fallback"}`;
    $("#pill-embed").innerHTML =
      `<span class="dot ${emb.reachable ? "green" : "red"}"></span>` +
      `<span>${emb.provider}:${esc(emb.model)} (${emb.dimension}d)</span>`;
    $("#sb-backend").textContent = `api · ${s.backend} · ${emb.provider}`;
    $("#node-second").className = `bridge-node cloud ${String(s.backend||"").startsWith("postgres")?"online":""}`;
    $("#pill-counts").textContent =
      `${s.counts.memories} memories · ${s.counts.documents} docs · ${s.counts.projects} projects`;

    const fb = s.counts.first_brain_writes;
    const fbOnline = isAIOnline;
    $("#fb-llm").textContent = `${fbOnline ? "ollama online" : "offline extractive"} · ${fb} writes`;
    document.getElementById("node-first").className = `bridge-node local ${fbOnline ? "online" : "offline"}`;
    renderStatsMini(s);
    fillProjectSelect().catch(() => {});
    fetchPlatform().catch(() => {});
    // Mid + widget — widget reflects Network (true), not AI
    loadMidBrainStatus().then(mid=>{
      updateWidget({ isOnline: isNetworkOnline, emb, s, mid });
    }).catch(()=>{ updateWidget({ isOnline: isNetworkOnline, emb, s, mid: null }); });
    return s;
  } catch (e) {
    // Mất kết nối thực — API không với tới
    $("#pill-api").innerHTML = `<span class="dot red"></span><span>API offline</span>`;
    $("#pill-api").title = `API unreachable: ${e.message}`;
    $("#pill-embed").innerHTML = `<span class="dot red"></span><span>offline</span>`;
    $("#sb-backend").textContent = `offline`;
    $("#pill-counts").textContent = `— memories · — docs`;
    document.getElementById("node-first").className = "bridge-node local offline";
    $("#fb-llm").textContent = `offline`;
    document.getElementById("node-second").className = "bridge-node cloud offline";
    const offEmb = {provider:"offline", model:"-", dimension:0, reachable:false};
    updateWidget({ isOnline: false, emb: offEmb, s: {counts:{memories:0, documents:0, first_brain_writes:0}, backend:"offline"}, mid: null });
    // keep Mid as offline too
    $("#mid-status").textContent = "offline";
    $("#node-mid").className = "bridge-node mid offline";
    const pill = document.getElementById("pill-mid");
    if(pill){ pill.className="pill err"; pill.innerHTML=`<span class="dot red"></span><span>Mid offline</span>`; }
    throw e;
  }
}

function fmtDuration(sec) {
    sec = Math.floor(sec);
    const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (d) return `${d}d${h}h`;
    if (h) return `${h}h${m}m`;
    return `${m}m${s}s`;
  }
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ONE VECTOR PLATFORM — 8 logical domains gộp vào mục Kiểu memory.
// Mirror backend mapping (services/knowledge_domains.py): kt thắng type.
const DOMAIN_GROUPS = [
  { key: "project", label: "PROJECT", types: ["project"] },
  { key: "engineering", label: "ENGINEERING", types: [] },
  { key: "standard", label: "STANDARD", types: [] },
  { key: "contract", label: "CONTRACT", types: [] },
  { key: "method", label: "METHOD", types: ["procedural"] },
  { key: "site", label: "SITE", types: [] },
  { key: "document", label: "DOCUMENT", types: ["document"] },
  { key: "lesson", label: "LESSON", types: ["lesson"] },
];

async function fetchPlatform() {
  if (state.platform) return state.platform;
  try {
    const p = await api("/v1/memory/knowledge-domains");
    state.platform = p;
    return p;
  } catch (e) {
    return null;
  }
}

function renderStatsMini(status) {
  const byType = status.counts.memories_by_type || {};
  const ordered = TYPE_ORDER.filter((k) => byType[k] !== undefined || k === "task");
  const base = (ordered.length ? ordered : ["document","lesson","decision","episodic","semantic","task"]);
  const rows2 = base
    .map((k) => `<div><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${TYPE_COLORS[k] || "var(--text)"};margin-right:6px;box-shadow:0 0 6px ${TYPE_COLORS[k]||"#fff"}66"></span>${k}<b style="color:${TYPE_COLORS[k] || "var(--text)"}">${byType[k] ?? 0}</b></div>`).join("");
  const extra = Object.keys(byType).filter((k) => !TYPE_ORDER.includes(k)).sort().map((k)=>`<div>${k}<b style="color:${TYPE_COLORS[k]||"var(--text)"}">${byType[k]}</b></div>`).join("");
  $("#stats-mini").innerHTML =
    `<label class="side-label">Tổng quan</label>
     <div>First Brain writes<b>${status.counts.first_brain_writes}</b></div>
     <div>Documents<b>${status.counts.documents}</b></div>
     <div>Projects<b>${status.counts.projects}</b></div>
     <div style="margin-top:6px">${rows2}${extra}</div>`;
}

/* ─────────── graph ─────────── */
let engine;

async function loadGraph() {
  const data = await api("/v1/graph?max_memories=1200");
  state.graph = data;
  engine.setData(data.nodes, data.links);
  buildTypeFilterChips(data.nodes);
  updateHud();
  applyFilters();
  $("#empty-hint").classList.toggle("hidden", data.nodes.length > 0);
}

function updateHud() {
  const vis = engine.nodes.filter((n) => engine.isVisible(n)).length;
  $("#hud").textContent = `${vis}/${engine.nodes.length} nodes · ${engine.links.length} links · zoom ${Math.round(engine.scale * 100)}%`;
}

function combinedFilter() {
  const f = state.filters;
  return (n) =>
    f.kinds.has(n.kind) &&
    (n.kind !== "memory" || f.types.has(n.type)) &&
    ((n.kind === "memory" ? n.importance ?? 0 : 1) >= f.minImportance) &&
    (!f.text || (n.label || "").toLowerCase().includes(f.text));
}

function applyFilters() {
  engine.setVisibleFilter(combinedFilter());
  updateHud();
}

$("#filter-text").addEventListener("input", (e) => { state.filters.text = e.target.value.toLowerCase().trim(); applyFilters(); });
$("#min-importance").addEventListener("input", (e) => {
  state.filters.minImportance = parseFloat(e.target.value);
  $("#min-imp-val").textContent = e.target.value;
  applyFilters();
});
$$("#kind-toggles .chip").forEach((chip) => chip.addEventListener("click", () => {
  const k = chip.dataset.kind;
  chip.classList.toggle("active");
  chip.classList.contains("active") ? state.filters.kinds.add(k) : state.filters.kinds.delete(k);
  applyFilters();
}));

function makeTypeChip(t, count) {
  const color = TYPE_COLORS[t] || "#888";
  const chip = document.createElement("div");
  chip.className = "type-chip" + (state.filters.types.has(t) ? "" : " off");
  chip.title = `${t} — ${count} memories (click để lọc)`;
  chip.innerHTML = `<span class="swatch" style="background:${color};box-shadow:0 0 6px ${color}66"></span>${t} <small style="color:${color}">${count}</small>`;
  chip.addEventListener("click", () => {
    state.filters.types.has(t) ? state.filters.types.delete(t) : state.filters.types.add(t);
    chip.classList.toggle("off");
    applyFilters();
  });
  return chip;
}

function toggleDomainTypes(types) {
  const allOn = types.every((t) => state.filters.types.has(t));
  for (const t of types) {
    allOn ? state.filters.types.delete(t) : state.filters.types.add(t);
  }
  buildTypeFilterChips(state.graph.nodes || []);
  applyFilters();
}

async function buildTypeFilterChips(nodes) {
  const stats = state.graph.stats?.memories_by_type || {};
  const present = new Set(nodes.filter((n) => n.kind === "memory").map((n) => n.type));
  const wrap = $("#type-filters");
  const platform = await fetchPlatform().catch(() => null);

  const flatTypes = () => {
    const types = TYPE_ORDER.filter((t) => present.has(t) || stats[t] !== undefined || t === "task");
    return types.length ? types : ["document","lesson","decision","episodic","semantic","task"];
  };

  wrap.innerHTML = "";
  if (!platform) {
    // offline fallback: chips phẳng như cũ
    for (const t of flatTypes()) wrap.appendChild(makeTypeChip(t, stats[t] ?? 0));
  } else {
    // Một nguồn số duy nhất (platform) — 8 dòng domain, không chips trùng.
    const byKey = Object.fromEntries((platform.domains || []).map((d) => [d.key, d]));
    const rows = DOMAIN_GROUPS.map((g) => ({ ...g, info: byKey[g.key] }));
    if (platform.unclassified && platform.unclassified.count > 0) {
      rows.push({ key: "__unclassified", label: "UNCLASSIFIED", types: [], info: platform.unclassified });
    }
    rows.forEach((g, gi) => {
      const info = g.info || { count: 0, memory_types: {}, status: "empty" };
      const total = info.count ?? 0;
      // types mà click domain sẽ bật/tắt trên graph
      const types = [...new Set([...g.types, ...Object.keys(info.memory_types || {})])];
      const last = gi === rows.length - 1;
      const off = types.length && types.every((t) => !state.filters.types.has(t));
      const row = document.createElement("div");
      row.className = "vp-row" + (total === 0 ? " vp-empty" : "") + (off ? " off" : "");
      const detail = Object.entries(info.memory_types || {}).map(([k, v]) => `${k}:${v}`).join(" ") || "chưa có dữ liệu";
      row.title = `${g.label} — ${total} memories [${detail}] (click để lọc graph)`;
      const col = DOMAIN_COLORS[g.key] || "#94a3b8";
      row.innerHTML = `<span class="swatch" style="background:${col};box-shadow:0 0 6px ${col}66"></span>`
        + `<span class="vp-label">${g.label}</span><b class="vp-count" style="color:${col}">${total.toLocaleString("en-US")}</b>`;
      if (last) row.classList.add("vp-last");
      if (types.length && total > 0) {
        row.style.cursor = "pointer";
        row.addEventListener("click", () => toggleDomainTypes(types));
      }
      wrap.appendChild(row);
    });
  }
  // legend project — màu riêng từng project trên graph 3D
  const projRows = [];
  const seenPid = new Set();
  for (const n of nodes) {
    const pid = n.kind === "project" ? n.id : (n.project_id ? `p:${n.project_id}` : null);
    if (!pid || seenPid.has(pid)) continue;
    seenPid.add(pid);
    const col = projectColorMap.get(pid);
    if (!col) continue;
    const memberCount = nodes.filter((m) => (m.kind === "project" ? m.id : (m.project_id ? `p:${m.project_id}` : null)) === pid).length;
    const nm = n.kind === "project" ? n.label : (n._pname || pid.slice(2, 10));
    projRows.push({ pid, col, nm, memberCount });
  }
  if (projRows.length) {
    const head = document.createElement("div");
    head.style.cssText = "margin-top:10px;font-size:10px;letter-spacing:.08em;color:var(--muted)";
    head.textContent = "PROJECT (màu riêng)";
    wrap.appendChild(head);
    for (const r of projRows) {
      const row = document.createElement("div");
      row.className = "type-chip";
      row.title = `${r.nm} — ${r.memberCount} nodes`;
      row.innerHTML = `<span class="swatch" style="background:${r.col};box-shadow:0 0 6px ${r.col}66"></span>${esc(r.nm.length > 18 ? r.nm.slice(0, 17) + "…" : r.nm)} <small style="color:${r.col}">${r.memberCount}</small>`;
      wrap.appendChild(row);
    }
  }
}

/* ─────────── detail panel ─────────── */
engine = new ForceGraph($("#graph"), {
  onSelect: (node) => { renderDetail(node); },
  onHover: (node) => renderTooltip(node),
});
// tự gán màu project mỗi khi engine nhận data (mọi đường: loadGraph, lọc project...)
{
  const _origSetData = engine.setData.bind(engine);
  engine.setData = (nodes, links) => { assignProjectColors(nodes); _origSetData(nodes, links); };
}

let lastPointerClient = { x: 0, y: 0 };
$("#graph").addEventListener("pointermove", (e) => { lastPointerClient = { x: e.clientX, y: e.clientY }; });

function renderTooltip(node) {
  const tt = $("#tooltip");
  if (!node) { tt.classList.add("hidden"); return; }
  const sub = node.kind === "memory"
    ? `${node.type} · importance ${(node.importance ?? 0).toFixed(2)} · ${node.origin || "?"}`
    : node.kind === "document"
      ? `${node.filename || ""}${node.pages ? ` · ${node.pages} trang` : ""}`
      : `project · ${node.status || ""}`;
  tt.innerHTML = `<div class="tt-title">${esc(node.label)}</div><div class="tt-sub">${esc(sub)}</div>`;
  const rect = $("#graph").getBoundingClientRect();
  tt.style.left = Math.min(lastPointerClient.x - rect.left + 14, rect.width - 330) + "px";
  tt.style.top = lastPointerClient.y - rect.top + 14 + "px";
  tt.classList.remove("hidden");
}

function renderDetail(node) {
  const body = $("#detail-body"), ph = $(".placeholder");
  if (!node) {
    body.classList.add("hidden");
    ph.classList.remove("hidden");
    return;
  }
  ph.classList.add("hidden");
  body.classList.remove("hidden");

  const color = window.FSB_COLORS(node);
  let html = `
    <div class="detail-head">
      <span class="detail-kind" style="color:${color};border-color:${color}">${node.kind}</span>
      ${node.type ? `<span class="detail-kind" style="color:${color}">${esc(node.type)}</span>` : ""}
    </div>
    <div class="detail-title">${esc(node.label)}</div>`;

  if (node.kind === "memory") {
    html += `
      <dl class="kv">
        <dt>importance</dt><dd><div class="bar"><i style="width:${(node.importance ?? 0) * 100}%"></i></div></dd>
        <dt>confidence</dt><dd>${(node.confidence ?? 0).toFixed(2)}</dd>
        <dt>nguồn</dt><dd>${esc(node.origin || "-")}</dd>
        <dt>tạo</dt><dd>${fmtDate(node.created_at)}</dd>
        <dt>cập nhật</dt><dd>${fmtDate(node.updated_at)}</dd>
        ${node.summary ? `<dt>tóm tắt</dt><dd>${esc(node.summary)}</dd>` : ""}
      </dl>
      <details><summary style="cursor:pointer;color:var(--muted);font-size:11px">NỘI DUNG</summary>
        <div class="detail-content" style="margin-top:6px">${esc(node.content || "")}</div>
      </details>`;
  } else if (node.kind === "document") {
    html += `
      <dl class="kv">
        <dt>file</dt><dd>${esc(node.filename || "-")}</dd>
        <dt>mime</dt><dd>${esc(node.mime_type || "-")}</dd>
        <dt>trang</dt><dd>${node.pages ?? "-"}</dd>
        <dt>tạo</dt><dd>${fmtDate(node.created_at)}</dd>
      </dl>`;
  } else {
    html += `
      <dl class="kv">
        <dt>status</dt><dd>${esc(node.status || "-")}</dd>
        <dt>mô tả</dt><dd>${esc(node.description || "-")}</dd>
        <dt>tạo</dt><dd>${fmtDate(node.created_at)}</dd>
      </dl>`;
  }

  html += `<div class="detail-actions">
    <button class="btn ghost small" id="d-focus">🎯 Focus</button>
    <button class="btn ghost small" id="d-similar">🔎 Tìm tương tự</button>
    ${node.kind === "document" ? `<button class="btn primary small" id="d-open">📄 Mở file</button>` : ""}
    ${node.kind === "memory" ? `<button class="btn danger small" id="d-delete">🗑 Xoá</button>` : ""}
  </div>`;

  body.innerHTML = html;
  $("#d-focus")?.addEventListener("click", () => engine.focusNode(node.id));
  $("#d-open")?.addEventListener("click", () => {
    const docId = (node.id || "").startsWith("d:") ? node.id.slice(2) : (node.document_id || null);
    if (docId) openDocument(docId); else toast("Node này không gắn file gốc", true);
  });
  $("#d-similar")?.addEventListener("click", () => {
    activateTab("search");
    $("#search-input").value = node.label;
    doSearch();
  });
  $("#d-delete")?.addEventListener("click", async () => {
    if (!confirm("Xoá memory này khỏi Second Brain?")) return;
    try {
      await api(`/v1/memory/${node.id.slice(2)}`, { method: "DELETE" });
      toast("Đã xoá memory");
      state.selected = null;
      renderDetail(null);
      await Promise.all([loadGraph(), loadStatus()]);
    } catch (e) { toast("Xoá thất bại: " + e.message, true); }
  });
}

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("vi-VN", { hour12: false }) : "-");

/* ─────────── document viewer (click → truy xuất file gốc) ─────────── */
let currentDocId = null;
async function openDocument(docId) {
  currentDocId = docId;
  const modal = $("#doc-modal");
  modal.classList.remove("hidden");
  $("#doc-title").textContent = "📄 Đang tải file…";
  $("#doc-meta").textContent = "";
  $("#doc-body").textContent = "⏳ đang truy xuất nội dung gốc…";
  $("#doc-status").textContent = "";
  $("#doc-find").value = "";
  try {
    const data = await api(`/v1/documents/${docId}/content?max_chunks=500`);
    const d = data.document;
    $("#doc-title").textContent = `📄 ${d.filename || d.title || docId.slice(0, 8)}`;
    const parts = [
      d.source ? `cây thư mục: ${d.source}` : null,
      d.mime_type || null,
      d.title ? `tiêu đề: ${d.title}` : null,
      `${data.chunk_count} đoạn`,
      d.created_at ? `nạp: ${fmtDate(d.created_at)}` : null,
    ].filter(Boolean);
    $("#doc-meta").textContent = parts.join(" · ");
    $("#doc-body").innerHTML = data.chunks.map((c, i) => {
      const page = c.metadata?.page ? ` — trang ${c.metadata.page}` : "";
      return `<div class="doc-chunk" data-i="${i}"><div class="doc-chunk-head">§${c.chunk_index + 1}${page}</div>${esc(c.content)}</div>`;
    }).join("") || "<em>File trống.</em>";
    $("#doc-status").textContent = `✅ ${data.chunk_count} đoạn · bấm 🎯 để xem node trên graph 3D`;
    $("#doc-status").className = "write-result ok";
  } catch (e) {
    $("#doc-title").textContent = "📄 Không mở được file";
    $("#doc-body").textContent = "";
    $("#doc-status").textContent = "❌ " + e.message;
    $("#doc-status").className = "write-result err";
  }
}
$("#doc-close")?.addEventListener("click", () => $("#doc-modal")?.classList.add("hidden"));
$("#doc-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "doc-modal") $("#doc-modal").classList.add("hidden");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#doc-modal")?.classList.add("hidden");
});
$("#doc-focus-graph")?.addEventListener("click", () => {
  if (!currentDocId) return;
  $("#doc-modal")?.classList.add("hidden");
  const node = engine.nodeById.get(`d:${currentDocId}`);
  if (node) {
    engine.focusNode(`d:${currentDocId}`, Math.max(engine.scale, 1.25));
    engine.selected = node; renderDetail(node); engine._dirty = true;
  } else {
    toast("Node file chưa có trên graph — Reload graph để thấy", true);
  }
});
$("#doc-find")?.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const q = e.target.value.trim().toLowerCase();
  if (!q) return;
  const chunks = $$("#doc-body .doc-chunk");
  const hit = chunks.find((el) => el.textContent.toLowerCase().includes(q));
  if (hit) {
    hit.scrollIntoView({ block: "center" });
    hit.style.background = "rgba(251,191,36,0.15)";
    setTimeout(() => (hit.style.background = ""), 1600);
  } else {
    toast("Không thấy trong file", true);
  }
});

/* ─────────── tabs ─────────── */
function activateTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-page").forEach((p) => p.classList.toggle("hidden", p.dataset.page !== name));
  if (name === "activity") loadAudit().catch(() => {});
  if (name === "metrics") loadMetrics().catch(() => {});
  if (name === "upload" && $("#up-project").options.length <= 1) fillUploadProjects();
  if (name === "projects") loadProjects();
  if (name === "comfy") checkComfyHealth();
  if (name === "files") { fillFileProjects(); doFileSearch(true); }
}

$$(".tab").forEach((t) => t.addEventListener("click", () => activateTab(t.dataset.tab)));

async function loadAudit() {
  const data = await api("/v1/admin/audit?limit=120");
  const tbody = $("#audit-table tbody");
  tbody.innerHTML = data.events.map((ev) => {
    const statusCls = ev.status >= 500 ? "status-bad" : ev.status >= 400 ? "status-warn" : "status-ok";
    const ts = ev.ts ? new Date(ev.ts).toLocaleTimeString("vi-VN", { hour12: false }) : "";
    return `<tr>
      <td>${ts}</td><td><b>${esc(ev.kind)}</b></td>
      <td>${esc(ev.method || "")}</td><td style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${esc(ev.path || "")}</td>
      <td class="${statusCls}">${ev.status ?? ""}</td><td>${ev.duration_ms ?? ""}</td>
      <td style="color:var(--muted)">${esc((ev.request_id || "").slice(0, 8))}</td>
    </tr>`;
  }).join("");

  // bridge pulse khi có write mới
  const lastWrite = data.events.find((e) => e.kind === "memory.write");
  if (lastWrite && state.lastAuditId && lastWrite.request_id !== state.lastAuditId) {
    $("#bridge").classList.add("pulse");
    setTimeout(() => $("#bridge").classList.remove("pulse"), 2500);
  }
  if (lastWrite) state.lastAuditId = lastWrite.request_id;
  $("#dock-status").textContent = `${data.events.length} sự kiện gần nhất`;
}

async function loadMetrics() {
  const res = await fetch("/v1/admin/metrics", { headers: { "X-API-Key": state.apiKey } });
  const text = await res.text();
  const counters = parsePrometheus(text);
  const sum = (name) => Object.entries(counters[name] || {}).reduce((a, [, v]) => a + v, 0);

  const codes = counters.fsb_http_requests_total || {};
  const writes = counters.fsb_memory_writes_total || {};
  const card = (name, value, detail) =>
    `<div class="metric-card"><div class="m-name">${name}</div><div class="m-value">${value}</div><div class="m-detail">${detail}</div></div>`;

  $("#metric-cards").innerHTML =
    card("Uptime", fmtDuration(counters.__uptime?.x || 0), `backend: <b>${esc(counters.__backend || "?")}</b>`) +
    card("HTTP requests", sum("fsb_http_requests_total"),
      Object.entries(codes).map(([k, v]) => `${k}: <b>${v}</b>`).join(" · ") || "—") +
    card("Memory writes", sum("fsb_memory_writes_total"),
      Object.entries(writes).map(([k, v]) => `${k}: <b>${v}</b>`).join(" · ") || "—") +
    card("Searches", sum("fsb_memory_searches_total"), "hybrid queries") +
    card("Documents", sum("fsb_documents_ingested_total"),
      `chunks: <b>${sum("fsb_document_chunks_total")}</b>`) +
    card("Projects created", sum("fsb_projects_created_total"), "") +
    card("Rate limited (429)", codes["429"] || 0, "sliding window 240/min") +
    card("Audit failures", sum("fsb_audit_write_failures_total"), "best-effort logging");
}

function parsePrometheus(text) {
  const out = { };
  for (const line of text.split("\n")) {
    if (!line || line.startsWith("#")) {
      const m = line.match(/fsb_build_info\{backend="([^"]+)"\}/);
      if (m) out.__backend = m[1];
      continue;
    }
    const mm = line.match(/^(fsb_[a-z_]+)(\{[^}]*\})?\s+([\d.]+)$/);
    if (!mm) continue;
    const [, name, labelStr, valueStr] = mm;
    const labels = {};
    if (labelStr) for (const pair of labelStr.slice(1, -1).split(",")) {
      const [k, v] = pair.split("=").map((s) => s.trim().replace(/^"|"$/g, ""));
      if (k) labels[k] = v;
    }
    (out[name] ||= {})[
      name === "fsb_uptime_seconds" ? "x" : Object.values(labels).join("/") || "_"
    ] = parseFloat(valueStr);
    if (name === "fsb_uptime_seconds") out.__uptime = { x: parseFloat(valueStr) };
  }
  return out;
}

/* ─────────── write form ─────────── */
$("#wf-importance").addEventListener("input", (e) => ($("#wf-imp-val").textContent = e.target.value));

async function fillProjectSelect() {
  const sel = $("#wf-project");
  const current = sel.value;
  const projects = await api("/v1/projects?limit=200");
  sel.innerHTML = `<option value="">— không gán —</option>` +
    projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  sel.value = current;
}

$("#write-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const resultEl = $("#write-result");
  resultEl.textContent = "⏳ đang lưu…";
  resultEl.className = "write-result";
  setWidgetState("first","processing","Ingesting data…");
  setWidgetState("mid","routing","Structuring thoughts…");
  try {
    const payload = {
      title: $("#wf-title").value.trim(),
      content: $("#wf-content").value.trim(),
      type: $("#wf-type").value,
      importance: parseFloat($("#wf-importance").value),
    };
    const pid = $("#wf-project").value;
    if (pid) payload.project_id = pid;
    const resp = await api("/v1/memory", { method: "POST", json: payload });
    const dedup = resp.deduplicated ? "(dedupe trùng nội dung)" : `(redact ${resp.redaction_count} secrets)`;
    resultEl.textContent = `✅ đã lưu ${resp.memory.id.slice(0, 8)}… ${dedup}`;
    resultEl.className = "write-result ok";
    $("#wf-title").value = "";
    $("#wf-content").value = "";
    setWidgetState("first","success","Success ✓");
    setTimeout(()=> setWidgetState("mid","idle","Idle · Ready"), 600);
    await Promise.all([loadGraph(), loadStatus()]);
  } catch (err) {
    resultEl.textContent = "❌ " + err.message;
    resultEl.className = "write-result err";
  }
});

/* ─────────── search tab ─────────── */
$("#search-go").addEventListener("click", doSearch);
$("#search-input").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const q = $("#search-input").value.trim();
  const box = $("#search-results");
  if (!q) { box.innerHTML = "<em>Nhập từ khoá…</em>"; return; }
  box.innerHTML = "<em>⏳ đang tìm…</em>";
  setWidgetState("mid","routing","Analyzing context…");
  setWidgetState("second","querying","Searching Knowledge Base…");
  try {
    const data = await api("/v1/memory/search", {
      method: "POST",
      json: { query: q, top_k: parseInt($("#search-topk").value, 10) },
    });
    setWidgetState("second","success","Retrieved ✓");
    setTimeout(()=> setWidgetState("mid","idle","Idle · Ready"), 800);
    if (!data.results.length) { box.innerHTML = "<em>Không có kết quả.</em>"; return; }
    // giữ kết quả để nút Mở file dùng lại metadata.document_id
    window._lastSearch = data.results;
    box.innerHTML = data.results.map((r, i) => {
      const c = TYPE_COLORS[r.type] || "#888";
      const bar = (v, max = 1) => `<div class="bar"><i style="width:${Math.min(100, (v / max) * 100)}%"></i></div>`;
      const docId = r.metadata?.document_id || null;
      return `<div class="sr-item" data-id="m:${r.id}" data-i="${i}">
        <div class="sr-top">
          <span class="swatch" style="width:9px;height:9px;border-radius:50%;background:${c}"></span>
          <span class="sr-title">${esc(r.title)}</span>
          <span class="sr-score">${r.score.toFixed(3)}</span>
        </div>
        <div class="sr-snippet">${esc((r.content || "").slice(0, 160))}</div>
        <div class="score-bars">
          <div class="sb">sem${bar(r.scores.semantic)}</div>
          <div class="sb">kw${bar(r.scores.keyword)}</div>
          <div class="sb">imp${bar(r.scores.importance)}</div>
          <div class="sb">rec${bar(r.scores.recency)}</div>
        </div>
        ${docId ? `<div class="sr-actions"><button class="btn ghost small sr-open" data-doc="${docId}">📄 Mở file gốc</button></div>` : ""}
      </div>`;
    }).join("");
    $$(".sr-item").forEach((el) => el.addEventListener("click", () => {
      const id = el.dataset.id;
      activateTab("search");
      engine.focusNode(id, Math.max(engine.scale, 1.25));
      const node = engine.nodeById.get(id);
      if (node) { engine.selected = node; renderDetail(node); engine._dirty = true; }
    }));
    $$(".sr-open").forEach((btn) => btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openDocument(btn.dataset.doc);
    }));
  } catch (e) {
    box.innerHTML = `<em style="color:var(--red)">Lỗi: ${esc(e.message)}</em>`;
    setWidgetState("second","idle","Idle · Ready");
    setWidgetState("mid","idle","Idle · Ready");
  }
}

/* ─────────── files tab — tìm file gốc ─────────── */
async function fillFileProjects() {
  const sel = $("#file-search-project");
  if (!sel || sel.options.length > 1) return;
  try {
    const projects = await api("/v1/projects?limit=200");
    sel.innerHTML = `<option value="">— mọi project —</option>` +
      projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    setTimeout(initCustomSelects, 60);
  } catch { /* ignore */ }
}

async function doFileSearch(silentEmpty = false) {
  const q = $("#file-search-input").value.trim();
  const pid = $("#file-search-project").value;
  const box = $("#file-search-results");
  if (!q && !pid) {
    if (!silentEmpty) box.innerHTML = "<em>Nhập từ khoá hoặc chọn project…</em>";
    else {
      // mở tab lần đầu: liệt kê file mới nhất luôn cho trực quan
      box.innerHTML = "<em>⏳ đang tải file mới nhất…</em>";
    }
  } else {
    box.innerHTML = "<em>⏳ đang tìm file…</em>";
  }
  setWidgetState("second", "querying", "Finding files…");
  try {
    const params = new URLSearchParams({
      limit: $("#file-search-limit").value || "50",
    });
    if (q) params.set("q", q);
    if (pid) params.set("project_id", pid);
    const docs = await api(`/v1/documents?${params.toString()}`);
    setWidgetState("second", "success", "Found ✓");
    setTimeout(() => setWidgetState("second", "idle", "Idle · Ready"), 800);
    if (!docs.length) { box.innerHTML = "<em>Không có file nào.</em>"; return; }
    // BƯỚC 1 — tìm thư mục gốc bằng TÊN tài liệu trước: tên khớp lên đầu,
    // nhóm theo thư mục gốc để thấy cây. BƯỚC 2 mới tới Vector DB (nút 🔎).
    const ql = q.toLowerCase();
    const scoreName = (d) => {
      if (!ql) return 0;
      const fn = (d.filename || "").toLowerCase();
      if (fn === ql) return 0;
      if (fn.startsWith(ql)) return 1;
      if (fn.includes(ql)) return 2;
      return 3;
    };
    const sorted = [...docs].sort((a, b) => scoreName(a) - scoreName(b));
    const groups = new Map();
    for (const d of sorted) {
      const root = (d.source || "").split("/")[0] || "(gốc)";
      if (!groups.has(root)) groups.set(root, []);
      groups.get(root).push(d);
    }
    const icon = (m) => (m || "").includes("pdf") ? "📕" : (m || "").includes("word") ? "📘" : (m || "").includes("markdown") || (m || "").includes("text") ? "📝" : "📄";
    const fileCard = (d) => {
      const segs = (d.source || "").split("/").filter(Boolean);
      const folder = segs.length > 1 ? segs.slice(0, -1).join("/") : "";
      return `
      <div class="sr-item" data-doc="${d.id}">
        <div class="sr-top">
          <span style="font-size:15px">${icon(d.mime_type)}</span>
          <span class="sr-title file-title" data-doc="${d.id}" title="Bấm để đọc toàn văn">${esc(d.filename || d.title || d.id.slice(0, 8))}</span>
        </div>
        ${d.source ? `<div class="sr-snippet" style="color:var(--amber)">📁 ${esc(d.source)}</div>` : ""}
        <div class="sr-snippet">${esc(d.title || "")}${d.title ? " · " : ""}${fmtDate(d.created_at)}</div>
        <div class="sr-actions">
          ${folder ? `<button class="btn primary small file-folder" data-folder="${esc(folder)}">📁 Mở thư mục</button>` : `<button class="btn primary small file-open" data-doc="${d.id}">📄 Mở file</button>`}
          <button class="btn ghost small file-graph" data-doc="${d.id}">🎯 Graph</button>
          <button class="btn ghost small file-vector" data-name="${esc(d.filename || d.title || "")}">🔎 Vector</button>
        </div>
      </div>`;
    };
    box.innerHTML = [...groups.entries()].map(([root, arr]) => `
      <div class="file-group">
        <div class="file-group-head">📁 ${esc(root)} <small>${arr.length} file</small></div>
        ${arr.map(fileCard).join("")}
      </div>`).join("");
    $$("#file-search-results .file-open").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation(); openDocument(b.dataset.doc);
    }));
    // bấm tên file = đọc toàn văn
    $$("#file-search-results .file-title").forEach((t) => {
      t.style.cursor = "pointer";
      t.addEventListener("click", (e) => { e.stopPropagation(); openDocument(t.dataset.doc); });
    });
    // Mở thư mục đã lưu: lọc luôn theo đường dẫn thư mục chứa file
    $$("#file-search-results .file-folder").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      $("#file-search-input").value = b.dataset.folder;
      doFileSearch();
      toast(`📁 Đang xem thư mục: ${b.dataset.folder}`);
    }));
    $$("#file-search-results .file-graph").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const node = engine.nodeById.get(`d:${b.dataset.doc}`);
      if (node) {
        engine.focusNode(`d:${b.dataset.doc}`, Math.max(engine.scale, 1.25));
        engine.selected = node; renderDetail(node); engine._dirty = true;
      } else toast("Node file chưa có trên graph — Reload graph", true);
    }));
    // BƯỚC 2 — nhảy sang Vector DB với tên file làm query
    $$("#file-search-results .file-vector").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      activateTab("search");
      $("#search-input").value = b.dataset.name;
      doSearch();
    }));
  } catch (e) {
    box.innerHTML = `<em style="color:var(--red)">Lỗi: ${esc(e.message)}</em>`;
    setWidgetState("second", "idle", "Idle · Ready");
  }
}
$("#file-search-go")?.addEventListener("click", () => doFileSearch());
$("#file-search-input")?.addEventListener("keydown", (e) => { if (e.key === "Enter") doFileSearch(); });
$("#file-search-project")?.addEventListener("change", () => doFileSearch(true));

/* ─────────── projects tab ─────────── */
let activeProjectFilter = null;

async function loadProjects() {
  const grid = $("#project-grid");
  grid.innerHTML = `<em>⏳ đang tải…</em>`;
  try {
    const projects = await api("/v1/projects?limit=200");
    const graphData = state.graph.nodes.length ? state.graph : null;
    const countsByProject = {};
    if (graphData) {
      for (const n of graphData.nodes) {
        if (n.project_id) countsByProject[n.project_id] = (countsByProject[n.project_id] || 0) + 1;
      }
    }
    if (!projects.length) {
      grid.innerHTML = `<div style="color:var(--muted);grid-column:1/-1">Chưa có dự án — tạo mới ở trên.</div>`;
      return;
    }
    grid.innerHTML = projects.map((p) => {
      const n = countsByProject[p.id] || 0;
      const isActive = activeProjectFilter === p.id;
      return `<div class="project-card ${isActive ? "active" : ""}" data-id="${p.id}">
        <div class="p-name" title="${esc(p.name)}">${esc(p.name)}</div>
        <div class="p-desc" title="${esc(p.description || "")}">${esc(p.description || "— không mô tả —")}</div>
        <div class="p-meta"><span>🧠 ${n} memories</span><span style="margin-left:auto">${fmtDate(p.created_at).slice(0, 10)}</span></div>
        <div class="p-actions">
          <button class="btn ghost p-view">👁️ Xem đồ thị</button>
          <button class="btn ghost p-copy" title="Copy ID">⎘ ID</button>
        </div>
      </div>`;
    }).join("");

    $$(".project-card .p-view").forEach((btn) => btn.addEventListener("click", async (e) => {
      const card = e.target.closest(".project-card");
      const pid = card.dataset.id;
      if (activeProjectFilter === pid) {
        activeProjectFilter = null;
        await refreshAll(true);
        loadProjects();
        return;
      }
      activeProjectFilter = pid;
      try {
        const data = await api(`/v1/graph?max_memories=800&project_id=${pid}`);
        engine.setData(data.nodes, data.links);
        state.graph = data;
        buildTypeFilterChips(data.nodes);
        applyFilters();
        $("#empty-hint").classList.toggle("hidden", data.nodes.length > 0);
        engine.fitView();
        $$(".project-card").forEach((c) => c.classList.toggle("active", c.dataset.id === pid));
        toast(`🔍 Lọc đồ thị theo dự án (${data.nodes.length} nodes)`);
      } catch (err) { toast("Lọc thất bại: " + err.message, true); }
    }));
    $$(".project-card .p-copy").forEach((btn) => btn.addEventListener("click", (e) => {
      const id = e.target.closest(".project-card").dataset.id;
      navigator.clipboard.writeText(id).then(() => toast("📋 Đã copy ID"));
    }));
    // sync dropdowns với danh sách mới — đảm bảo Ghi memory / Upload cập nhật ngay
    await Promise.all([fillProjectSelect(), fillUploadProjects()]);
  } catch (e) {
    grid.innerHTML = `<em style="color:var(--red)">Lỗi: ${esc(e.message)}</em>`;
  }
}

$("#project-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#pf-name").value.trim();
  const desc = $("#pf-desc").value.trim();
  const el = $("#pf-result");
  if (!name) { el.textContent = "❌ Tên dự án bắt buộc"; el.className = "write-result err"; return; }
  el.textContent = "⏳ đang tạo…"; el.className = "write-result";
  try {
    const created = await api("/v1/projects", { method: "POST", json: { name, description: desc || null } });
    el.textContent = `✅ Đã tạo "${created.name}" (${created.id.slice(0, 8)}…)`; el.className = "write-result ok";
    $("#pf-name").value = ""; $("#pf-desc").value = "";
    // cập nhật ngay lập tức dropdown Ghi memory để thấy dự án mới (không đợi graph)
    for (const selId of ["#wf-project", "#up-project", "#mi-project", "#folder-project"]) {
      const sel = $(selId);
      if (sel && ![...sel.options].some((o) => o.value === created.id)) {
        const opt = document.createElement("option");
        opt.value = created.id; opt.textContent = created.name;
        sel.appendChild(opt);
      }
    }
    $("#wf-project").value = created.id;
    await Promise.all([loadProjects(), loadStatus(), loadGraph()]);
    // đảm bảo sau khi reload từ server vẫn giữ dự án mới (tránh bị ghi đè nếu fetch chậm)
    for (const selId of ["#wf-project", "#up-project", "#mi-project", "#folder-project"]) {
      const sel = $(selId);
      if (sel && ![...sel.options].some((o) => o.value === created.id)) {
        const opt = document.createElement("option");
        opt.value = created.id; opt.textContent = created.name;
        sel.appendChild(opt);
      }
    }
    $("#wf-project").value = created.id;
    toast(`📁 Dự án "${created.name}" đã tạo`);
  } catch (err) {
    el.textContent = "❌ " + err.message; el.className = "write-result err";
  }
});

/* ─────────── buttons / shortcuts ─────────── */
$("#btn-fit").addEventListener("click", () => engine.fitView());
$("#btn-reheat").addEventListener("click", () => engine.reheat(0.8));
$("#btn-reload-graph").addEventListener("click", () => refreshAll(true));
$("#btn-refresh").addEventListener("click", () => refreshAll(true));

document.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "r" || e.key === "R") refreshAll(true);
  if (e.key === "f" || e.key === "F") engine.fitView();
  if (e.key === "Escape") { engine.selected = null; renderDetail(null); engine._dirty = true; }
});

/* ─────────── upload tab ─────────── */
const uploadState = { target: "local", files: [], seq: 0 };
const UPLOAD_EXT = [".pdf", ".docx", ".md", ".txt"];
const MAX_MB = 200;

$("#cloud-url").value = localStorage.getItem("fsb.cloudUrl") || "";
$("#cloud-key").value = localStorage.getItem("fsb.cloudKey") || "";

$$("#target-row .chip").forEach((chip) => chip.addEventListener("click", () => {
  $$("#target-row .chip").forEach((c) => c.classList.remove("active"));
  chip.classList.add("active");
  uploadState.target = chip.dataset.target;
  $("#cloud-config").classList.toggle("hidden", uploadState.target !== "cloud");
  fillUploadProjects();
}));

function uploadCfg() {
  if (uploadState.target === "local") return { base: "", key: state.apiKey, name: "local" };
  const base = ($("#cloud-url").value || "").trim().replace(/\/+$/, "");
  return { base, key: $("#cloud-key").value.trim(), name: "cloud" };
}

async function fillUploadProjects() {
  const cfg = uploadCfg();
  if (uploadState.target === "cloud" && !cfg.base) return;
  for (const selId of ["#up-project", "#mi-project"]) {
    const sel = $(selId);
    if (!sel) continue;
    const keep = sel.value;
    try {
      const res = await fetch(`${cfg.base}/v1/projects?limit=200`, { headers: { "X-API-Key": cfg.key } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const projects = await res.json();
      sel.innerHTML = `<option value="">— không gán —</option>` +
        projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
      sel.value = keep;
    } catch (e) {
      toast(`Không lấy được project từ ${cfg.name}: ${e.message}`, true);
    }
  }
}

function humanSize(bytes) {
  return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function addFiles(list) {
  for (const f of list) {
    const ext = "." + f.name.split(".").pop().toLowerCase();
    if (!UPLOAD_EXT.includes(ext)) { toast(`Bỏ qua ${f.name}: định dạng không hỗ trợ`, true); continue; }
    if (f.size > MAX_MB * 1048576) { toast(`Bỏ qua ${f.name}: > ${MAX_MB} MB`, true); continue; }
    uploadState.files.push({ uid: ++uploadState.seq, file: f, status: "pending", message: "" });
  }
  renderFileList();
}

function renderFileList() {
  const wrap = $("#file-list");
  wrap.innerHTML = "";
  for (const item of uploadState.files) {
    const div = document.createElement("div");
    const cls = item.status === "ok" ? "ok" : item.status === "error" ? "err" : item.status === "busy" ? "busy" : "";
    div.className = `file-item ${cls}`;
    const icon = item.status === "ok" ? "✅" : item.status === "error" ? "❌" : item.status === "busy" ? "⏳" : "📄";
    div.innerHTML = `
      <span>${icon}</span>
      <span class="f-name">${esc(item.file.name)}</span>
      <span class="f-size">${humanSize(item.file.size)}</span>
      <span class="f-status">${esc(item.message)}</span>
      ${item.status === "pending" ? `<button class="f-remove" title="Bỏ">✕</button>` : ""}`;
    div.querySelector(".f-remove")?.addEventListener("click", () => {
      uploadState.files = uploadState.files.filter((x) => x.uid !== item.uid);
      renderFileList();
    });
    wrap.appendChild(div);
  }
  $("#up-count").textContent = uploadState.files.length ? `(${uploadState.files.length})` : "";
  $("#btn-upload").disabled = !uploadState.files.some((f) => f.status === "pending");
}

$("#dropzone").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
["dragover", "dragenter"].forEach((ev) =>
  $("#dropzone").addEventListener(ev, (e) => { e.preventDefault(); $("#dropzone").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) =>
  $("#dropzone").addEventListener(ev, (e) => { e.preventDefault(); $("#dropzone").classList.remove("over"); }));
$("#dropzone").addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
$("#btn-clear-files").addEventListener("click", () => { uploadState.files = []; renderFileList(); });

function setProgress(ratio) { setProgressFor($("#up-progress"), ratio); }

function xhrUpload(cfg, path, entry, fields) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", entry.file);
    for (const [k, v] of Object.entries(fields)) if (v) fd.append(k, v);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${cfg.base}${path}`);
    xhr.setRequestHeader("X-API-Key", cfg.key);
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && e.total > 0) setProgress(e.loaded / e.total);
    });
    xhr.addEventListener("load", () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else {
        const code = body?.error?.code || "";
        const msg = body?.error?.message || "";
        reject(new Error(`HTTP ${xhr.status} ${code} ${msg}`.trim()));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("lỗi mạng hoặc CORS")));
    xhr.send(fd);
  });
}

$("#btn-upload").addEventListener("click", async () => {
  const cfg = uploadCfg();
  const pending = uploadState.files.filter((f) => f.status === "pending");
  if (!cfg.base && cfg.name === "cloud") { toast("Chưa nhập URL cloud", true); return; }
  if (!cfg.key) { toast("Chưa có API key cho đích đã chọn", true); return; }
  if (!pending.length) return;

  if (uploadState.target === "cloud") {
    localStorage.setItem("fsb.cloudUrl", $("#cloud-url").value.trim());
    localStorage.setItem("fsb.cloudKey", $("#cloud-key").value.trim());
  }

  $("#btn-upload").disabled = true;
  let okCount = 0, failCount = 0, chunkTotal = 0;
  const title = $("#up-title").value.trim();
  const source = $("#up-source").value.trim();
  const projectId = $("#up-project").value;

  for (let i = 0; i < pending.length; i++) {
    const entry = pending[i];
    entry.status = "busy";
    entry.message = "đang tải…";
    renderFileList();
    setProgress(0);
    try {
      const resp = await xhrUpload(cfg, "/v1/documents/upload", entry, { title, source, project_id: projectId });
      entry.status = "ok";
      chunkTotal += resp.chunks_indexed;
      entry.message = `${resp.chunks_indexed} chunk`;
      okCount++;
    } catch (e) {
      entry.status = "error";
      entry.message = e.message.slice(0, 60);
      failCount++;
    }
    renderFileList();
  }
  setProgress(null);

  const summary = $("#up-summary");
  summary.className = `write-result ${failCount ? "err" : "ok"}`;
  summary.textContent =
    `Xong: ${okCount} thành công (${chunkTotal} chunk)` + (failCount ? `, ${failCount} lỗi` : "") +
    ` → đích ${cfg.name}${cfg.base ? ` ${cfg.base}` : ""}`;
  if (okCount && uploadState.target === "local") await Promise.all([loadGraph(), loadStatus()]);
  if (okCount) toast(`📤 Đã nạp ${okCount} tài liệu vào ${cfg.name}`);
});

/* ─────────── upload mode: docs ↔ bulk memory ↔ folder ─────────── */
$$("#upload-mode .chip").forEach((chip) => chip.addEventListener("click", () => {
  $$("#upload-mode .chip").forEach((c) => c.classList.remove("active"));
  chip.classList.add("active");
  const mode = chip.dataset.mode;
  $("#pane-docs").classList.toggle("hidden", mode !== "docs");
  $("#pane-bulk").classList.toggle("hidden", mode !== "bulk");
  $("#pane-folder").classList.toggle("hidden", mode !== "folder");
  if (mode === "bulk" && $("#mi-project").options.length <= 1) fillUploadProjects();
  if (mode === "folder") fillFolderProjects();
}));

/* ─────────── folder → project upload (giữ cây thư mục) ─────────── */
const folderState = { files: [] };
const FOLDER_EXT = [".pdf", ".docx", ".md", ".txt"];

async function fillFolderProjects() {
  const cfg = uploadCfg();
  const sel = $("#folder-project");
  if (!sel) return;
  if (uploadState.target === "cloud" && !cfg.base) return;
  const keep = sel.value || localStorage.getItem("fsb.folderProject") || "";
  try {
    const res = await fetch(`${cfg.base}/v1/projects?limit=200`, { headers: { "X-API-Key": cfg.key } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const projects = await res.json();
    sel.innerHTML = `<option value="">— chọn project —</option>` +
      projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
    setTimeout(initCustomSelects, 60);
  } catch (e) {
    toast(`Không lấy được project cho folder upload: ${e.message}`, true);
  }
}
$("#folder-project")?.addEventListener("change", (e) => {
  localStorage.setItem("fsb.folderProject", e.target.value || "");
});

function renderFolderTree() {
  const wrap = $("#folder-tree");
  const files = folderState.files;
  // group theo thư mục cha để thấy cây
  const groups = {};
  for (const f of files) {
    const parts = f.rel.split("/");
    const dir = parts.length > 1 ? parts.slice(0, -1).join("/") : "(gốc)";
    (groups[dir] ||= []).push(f);
  }
  wrap.innerHTML = Object.keys(groups).sort().map((dir) =>
    `<div style="margin:4px 0"><div style="color:var(--amber);font-size:11px">📁 ${esc(dir)}</div>` +
    groups[dir].map((f) =>
      `<div class="file-item"><span>📄</span><span class="f-name">${esc(f.file.name)}</span>` +
      `<span class="f-size">${humanSize(f.file.size)}</span>` +
      `<span class="f-status" style="color:var(--muted)">${esc(f.rel)}</span></div>`
    ).join("") + `</div>`
  ).join("") || `<em style="color:var(--muted)">Chưa chọn thư mục.</em>`;
  $("#folder-count").textContent = files.length ? `(${files.length})` : "";
  $("#btn-folder-upload").disabled = !files.length;
  const rootInput = $("#folder-root");
  if (files.length && !rootInput.value) {
    rootInput.placeholder = `mặc định: ${files[0].rel.split("/")[0] || "folder"}`;
  }
}

function addFolderFiles(list) {
  let skipped = 0;
  for (const f of list) {
    const rel = f.webkitRelativePath || f.name;
    const ext = "." + f.name.split(".").pop().toLowerCase();
    if (!FOLDER_EXT.includes(ext)) { skipped++; continue; }
    if (f.size > MAX_MB * 1048576) { skipped++; continue; }
    if (folderState.files.some((x) => x.rel === rel)) continue;
    folderState.files.push({ file: f, rel });
  }
  if (skipped) toast(`Bỏ qua ${skipped} file (sai định dạng/quá ${MAX_MB}MB)`, true);
  if (folderState.files.length > 2000) {
    folderState.files = folderState.files.slice(0, 2000);
    toast("Giới hạn 2000 file/lần — chia nhỏ thư mục", true);
  }
  renderFolderTree();
}

$("#folder-dropzone")?.addEventListener("click", () => $("#folder-input").click());
$("#folder-input")?.addEventListener("change", (e) => { addFolderFiles(e.target.files); e.target.value = ""; });
$("#btn-folder-clear")?.addEventListener("click", () => { folderState.files = []; renderFolderTree(); });

$("#btn-folder-upload")?.addEventListener("click", async () => {
  const cfg = uploadCfg();
  const pid = $("#folder-project").value;
  if (!pid) { toast("Chọn project đích trước", true); return; }
  if (!cfg.key) { toast("Chưa có API key cho đích đã chọn", true); return; }
  if (!folderState.files.length) return;
  localStorage.setItem("fsb.folderProject", pid);

  const FOLDER_BATCH = 100; // backend cap/request — tự chia lô tới khi hết
  const all = [...folderState.files];
  const batches = Math.ceil(all.length / FOLDER_BATCH);
  const rootGuess = all[0].rel.split("/")[0] || "";
  const root = $("#folder-root").value.trim() || rootGuess;

  const btn = $("#btn-folder-upload"), summary = $("#folder-summary");
  btn.disabled = true;
  summary.className = "write-result";
  setWidgetState("first", "processing", "Ingesting folder…");
  let done = 0, okTotal = 0, failTotal = 0, chunkTotal = 0;
  const errSamples = [];
  try {
    for (let b = 0; b < batches; b++) {
      const slice = all.slice(b * FOLDER_BATCH, (b + 1) * FOLDER_BATCH);
      summary.textContent = `⏳ lô ${b + 1}/${batches}: đang upload ${slice.length} file (đã xong ${done}/${all.length})…`;
      setProgressFor($("#folder-progress"), done / all.length);
      const fd = new FormData();
      for (const f of slice) fd.append("files", f.file, f.file.name);
      fd.append("paths", JSON.stringify(slice.map((f) => f.rel)));
      fd.append("project_id", pid);
      fd.append("root", root);
      const res = await fetch(`${cfg.base}/v1/documents/upload-folder`, {
        method: "POST",
        headers: { "X-API-Key": cfg.key },
        body: fd,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(`lô ${b + 1}: HTTP ${res.status} ${body?.error?.message || ""}`.trim());
      done += slice.length;
      okTotal += body.succeeded || 0;
      failTotal += body.failed || 0;
      chunkTotal += body.total_chunks || 0;
      for (const i of (body.items || [])) {
        if (i.error && errSamples.length < 5) errSamples.push(`${i.path}: ${i.error}`);
      }
      setProgressFor($("#folder-progress"), done / all.length);
    }
    setProgressFor($("#folder-progress"), 1);
    summary.textContent =
      `✅ Xong: ${okTotal}/${all.length} file (${chunkTotal} chunk, ${batches} lô) → project` +
      (failTotal ? `, ${failTotal} lỗi` : "");
    summary.className = `write-result ${failTotal && !okTotal ? "err" : "ok"}`;
    if (errSamples.length) summary.textContent += " — lỗi: " + errSamples.join("; ");
    if (okTotal) {
      folderState.files = [];
      renderFolderTree();
      if (uploadState.target === "local") await Promise.all([loadGraph(), loadStatus()]);
      toast(`📁 Đã nạp thư mục: ${okTotal} file (${batches} lô) vào project`);
    }
    setWidgetState("first", "success", "Success ✓");
  } catch (e) {
    summary.textContent = `❌ Dừng ở ${done}/${all.length} file: ` + e.message;
    summary.className = "write-result err";
    toast("Upload thư mục lỗi: " + e.message, true);
  } finally {
    btn.disabled = !folderState.files.length;
    setTimeout(() => setProgressFor($("#folder-progress"), null), 800);
  }
});

/* ─────────── bulk file → memory import ─────────── */
const bulkState = { files: [], seq: 0 };
const BULK_EXT = [".json", ".jsonl", ".csv", ".md", ".markdown", ".txt"];
const MAX_ITEMS_HINT = 1000;

function estimateItems(name, text) {
  const ext = "." + name.split(".").pop().toLowerCase();
  try {
    if (ext === ".json") {
      const d = JSON.parse(text);
      return Array.isArray(d) ? d.length : Array.isArray(d?.items) ? d.items.length : 1;
    }
    if (ext === ".jsonl") return text.split("\n").filter((l) => l.trim()).length;
    if (ext === ".csv") return Math.max(0, text.split(/\r?\n/).filter((l) => l.trim()).length - 1);
    if (ext === ".md" || ext === ".markdown") {
      return Math.max(text.split(/\r?\n/).filter((l) => /^#{1,6}\s+/.test(l)).length, text.trim() ? 1 : 0);
    }
    return Math.max(text.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean).length, text.trim() ? 1 : 0);
  } catch { return "?"; }
}

async function addBulkFiles(list) {
  for (const f of list) {
    const ext = "." + f.name.split(".").pop().toLowerCase();
    if (!BULK_EXT.includes(ext)) { toast(`Bỏ qua ${f.name}: cần JSON/JSONL/CSV/MD/TXT`, true); continue; }
    const entry = { uid: ++bulkState.seq, file: f, status: "pending", message: "đang đọc…" };
    bulkState.files.push(entry);
    renderBulkList();
    try {
      const text = await f.text();
      const est = estimateItems(f.name, text);
      entry.estimate = est;
      entry.message = typeof est === "number"
        ? (est > MAX_ITEMS_HINT ? `⚠ ~${est} mục > ${MAX_ITEMS_HINT}` : `~${est} memory`)
        : "JSON lỗi?";
    } catch {
      entry.message = "không đọc được";
    }
    renderBulkList();
  }
}

function renderBulkList() {
  const wrap = $("#mi-list");
  wrap.innerHTML = "";
  for (const item of bulkState.files) {
    const div = document.createElement("div");
    const cls = item.status === "ok" ? "ok" : item.status === "error" ? "err" : item.status === "busy" ? "busy" : "";
    div.className = `file-item ${cls}`;
    const icon = item.status === "ok" ? "✅" : item.status === "error" ? "❌" : item.status === "busy" ? "⏳" : "🧠";
    div.innerHTML = `
      <span>${icon}</span>
      <span class="f-name">${esc(item.file.name)}</span>
      <span class="f-size">${esc(item.message || "")}</span>
      <span class="f-status">${esc(item.result || "")}</span>
      ${item.status === "pending" ? `<button class="f-remove" title="Bỏ">✕</button>` : ""}`;
    div.querySelector(".f-remove")?.addEventListener("click", () => {
      bulkState.files = bulkState.files.filter((x) => x.uid !== item.uid);
      renderBulkList();
    });
    wrap.appendChild(div);
  }
  $("#mi-count").textContent = bulkState.files.length ? `(${bulkState.files.length})` : "";
  $("#btn-import").disabled = !bulkState.files.some((f) => f.status === "pending");
}

$("#mi-dropzone").addEventListener("click", () => $("#mi-input").click());
$("#mi-input").addEventListener("change", (e) => { addBulkFiles(e.target.files); e.target.value = ""; });
["dragover", "dragenter"].forEach((ev) =>
  $("#mi-dropzone").addEventListener(ev, (e) => { e.preventDefault(); $("#mi-dropzone").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) =>
  $("#mi-dropzone").addEventListener(ev, (e) => { e.preventDefault(); $("#mi-dropzone").classList.remove("over"); }));
$("#mi-dropzone").addEventListener("drop", (e) => addBulkFiles(e.dataTransfer.files));
$("#btn-mi-clear").addEventListener("click", () => { bulkState.files = []; renderBulkList(); });

$("#btn-import").addEventListener("click", async () => {
  const cfg = uploadCfg();
  const pending = bulkState.files.filter((f) => f.status === "pending");
  if (!cfg.base && uploadState.target === "cloud") { toast("Chưa nhập URL cloud", true); return; }
  if (!cfg.key) { toast("Chưa có API key cho đích đã chọn", true); return; }
  if (!pending.length) return;

  if (uploadState.target === "cloud") {
    localStorage.setItem("fsb.cloudUrl", $("#cloud-url").value.trim());
    localStorage.setItem("fsb.cloudKey", $("#cloud-key").value.trim());
  }

  $("#btn-import").disabled = true;
  let totalCreated = 0, totalDedup = 0, totalErr = 0, okFiles = 0;

  for (const entry of pending) {
    entry.status = "busy";
    entry.message = "đang nạp…";
    entry.result = "";
    renderBulkList();
    setProgressFor($("#mi-progress"), 0.35);
    try {
      const resp = await xhrUpload(cfg, "/v1/memory/import", entry, {
        project_id: $("#mi-project").value,
        default_type: $("#mi-type").value,
        source: $("#mi-source").value.trim(),
      });
      entry.status = resp.errors.length ? "error" : "ok";
      entry.result =
        `+${resp.created}/${resp.total_parsed}` +
        (resp.deduplicated ? ` · trùng ${resp.deduplicated}` : "") +
        (resp.errors.length ? ` · lỗi ${resp.errors.length}` : "");
      totalCreated += resp.created;
      totalDedup += resp.deduplicated;
      totalErr += resp.errors.length;
      if (!resp.errors.length) okFiles++;
    } catch (e) {
      entry.status = "error";
      entry.result = e.message.slice(0, 60);
      totalErr++;
    }
    setProgressFor($("#mi-progress"), 1);
    renderBulkList();
  }
  setProgressFor($("#mi-progress"), null);

  const summary = $("#mi-summary");
  summary.className = `write-result ${totalErr && !totalCreated ? "err" : "ok"}`;
  summary.textContent =
    `Xong: +${totalCreated} memory` +
    (totalDedup ? ` · ${totalDedup} trùng bỏ qua` : "") +
    (totalErr ? ` · ${totalErr} lỗi` : "") +
    ` → ${cfg.name}${cfg.base ? ` ${cfg.base}` : ""}`;
  if (totalCreated && uploadState.target === "local") await Promise.all([loadGraph(), loadStatus()]);
  if (totalCreated) toast(`🧠 Đã nạp ${totalCreated} memories vào ${cfg.name}`);
});

/* ─────────── comfy tab ─────────── */
let comfyLastFilename = null;
async function checkComfyHealth(){
  const el=$("#comfy-health"); if(!el) return;
  try{
    const r=await api("/v1/comfy/health");
    el.textContent = r.status==="online" ? "● Comfy online" : r.status==="offline" ? "○ Comfy offline — chạy .\\scripts\\comfy.ps1" : r.status;
    el.style.color = r.status==="online" ? "var(--green)" : "var(--muted)";
  } catch { const e=$("#comfy-health"); if(e) e.textContent="○ Comfy offline"; }
}
async function doComfyGenerate(){
  const prompt=$("#comfy-prompt")?.value.trim();
  const negative=$("#comfy-negative")?.value.trim()||"";
  const workflow=$("#comfy-workflow")?.value||null;
  const status=$("#comfy-status"), preview=$("#comfy-preview"), progress=$("#comfy-progress");
  const btn=$("#comfy-generate");
  if(!prompt){ toast("Nhập prompt trước", true); return; }
  status.textContent="⏳ đang sinh ảnh (CPU 60-90s)…"; status.className="write-result";
  btn.disabled=true; setProgressFor(progress, 0.3);
  try{
    const data=await api("/v1/comfy/generate", {method:"POST", json:{prompt, negative, workflow_path: workflow}});
    setProgressFor(progress, 1);
    status.textContent=`✅ xong ${data.images?.length||0} ảnh`; status.className="write-result ok";
    if(data.images && data.images.length){
      const img=data.images[0];
      comfyLastFilename=img.filename;
      // ComfyUI view endpoint requires direct fetch via proxy? Use local Comfy base
      // Try via API: fetch image bytes as blob via comfy view
      const imgUrl=`http://127.0.0.1:8188/view?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder||"")}&type=${encodeURIComponent(img.type||"output")}`;
      // fetch via no-cors through local comfy (may need proxy) — try direct
      preview.innerHTML=`<img src="${imgUrl}" alt="comfy" onerror="this.onerror=null; this.src=''; this.parentElement.textContent='Ảnh đã lưu: ${img.filename} (mở http://127.0.0.1:8188/view?...)'" />`;
      preview.classList.add("has-img");
      $("#comfy-save-mem")?.classList.remove("hidden");
      $("#comfy-download")?.classList.remove("hidden");
      $("#comfy-download").onclick=()=> window.open(imgUrl, "_blank");
      toast("🎨 Comfy đã sinh xong");
    } else {
      preview.textContent="Không có ảnh trả về";
    }
  } catch(e){
    status.textContent="❌ "+e.message; status.className="write-result err";
    toast("Comfy lỗi: "+e.message, true);
  } finally { btn.disabled=false; setTimeout(()=>setProgressFor(progress, null), 800); }
}
$("#comfy-generate")?.addEventListener("click", doComfyGenerate);
$("#comfy-save-mem")?.addEventListener("click", async ()=>{
  if(!comfyLastFilename) return;
  const prompt=$("#comfy-prompt").value.trim();
  const resEl=$("#comfy-save-result");
  resEl.textContent="⏳ đang lưu…";
  try{
    const r=await api("/v1/memory", {method:"POST", json:{title: prompt.slice(0,120)||"Comfy image", content: `ComfyUI generated: ${prompt}\nImage: ${comfyLastFilename}`, type:"lesson", importance:0.7}});
    resEl.textContent=`✅ đã lưu memory ${r.memory.id.slice(0,8)}`; resEl.className="write-result ok";
    await Promise.all([loadGraph(), loadStatus()]);
    toast("Đã lưu ảnh thành memory");
  } catch(e){ resEl.textContent="❌ "+e.message; resEl.className="write-result err"; }
});
// hook detail panel: nếu chọn memory thì điền prompt nhanh
const _origRenderDetail = renderDetail;
renderDetail = function(node){
  _origRenderDetail(node);
  if(node && node.kind==="memory"){
    const btn=document.createElement("button");
    btn.className="btn ghost small"; btn.textContent="🎨 Tạo ảnh từ memory này";
    btn.onclick=()=>{ activateTab("comfy"); const p=$("#comfy-prompt"); if(p) p.value=(node.label+" — "+(node.content||"")).slice(0,600); toast("Đã điền prompt từ memory"); };
    const actions=document.querySelector("#detail-body .detail-actions");
    if(actions) actions.appendChild(btn);
  }
};

function setProgressFor(barEl, ratio) {
  barEl.classList.toggle("hidden", ratio == null);
  barEl.querySelector("i").style.width = `${Math.round((ratio || 0) * 100)}%`;
}

/* ─────────── main loop ─────────── */
let countdown = 15;

async function refreshAll(manual = false) {
  if (state.refreshing) return;
  state.refreshing = true;
  countdown = 15;
  try {
    await Promise.all([
      loadStatus(),
      activeProjectFilter ? api(`/v1/graph?max_memories=800&project_id=${activeProjectFilter}`).then((d) => {
        engine.setData(d.nodes, d.links); state.graph = d; buildTypeFilterChips(d.nodes); applyFilters();
      }) : loadGraph(),
      document.querySelector(".tab-page[data-page='activity']:not(.hidden)") ? loadAudit() : Promise.resolve(),
      document.querySelector(".tab-page[data-page='projects']:not(.hidden)") ? loadProjects() : Promise.resolve(),
    ]);
    if (manual) toast("🔄 Đã làm mới dữ liệu");
  } catch (e) {
    if (String(e.message) !== "unauthorized") toast("Lỗi tải dữ liệu: " + e.message, true);
  } finally {
    state.refreshing = false;
  }
}

setInterval(() => {
  countdown -= 1;
  $("#refresh-in").textContent = countdown;
  if (countdown <= 0) refreshAll(false);
}, 1000);

async function bootstrap() {
  try {
    await refreshAll(false);
  } catch (e) {
    console.error(e);
    showKeyModal();
  }
}

/* ── agent pro custom select — thay popup trắng native bằng popup agent ── */
function enhanceSelect(sel){
  if(!sel || sel.dataset.csEnhanced) return;
  sel.dataset.csEnhanced="1";
  const w=document.createElement("div"); w.className="custom-select";
  sel.parentNode.insertBefore(w, sel); w.appendChild(sel);
  sel.classList.add("native-hidden");
  const trigger=document.createElement("div"); trigger.className="cs-trigger"; trigger.tabIndex=0;
  const list=document.createElement("div"); list.className="cs-options";
  w.appendChild(trigger); w.appendChild(list);
  const sync=()=>{ const o=sel.options[sel.selectedIndex]; trigger.textContent=o?o.textContent:"—"; };
  const build=()=>{
    list.innerHTML="";
    [...sel.options].forEach((o,idx)=>{
      const d=document.createElement("div"); d.className="cs-option"+(idx===sel.selectedIndex?" active":""); d.textContent=o.textContent;
      d.addEventListener("click",()=>{ sel.selectedIndex=idx; sel.dispatchEvent(new Event("change",{bubbles:true})); sync(); build(); close(); });
      list.appendChild(d);
    });
  };
  const open=()=>{ trigger.classList.add("open"); list.classList.add("open"); };
  const close=()=>{ trigger.classList.remove("open"); list.classList.remove("open"); };
  trigger.addEventListener("click",(e)=>{ e.stopPropagation(); if(list.classList.contains("open")) close(); else { document.querySelectorAll(".cs-options.open").forEach(el=>{el.classList.remove("open"); el.previousElementSibling?.classList.remove("open")}); build(); open(); }});
  trigger.addEventListener("keydown",(e)=>{ if(e.key==="Enter"||e.key===" "){e.preventDefault(); trigger.click();} if(e.key==="Escape") close();});
  sel.addEventListener("change",()=>{ sync(); build();});
  new MutationObserver(()=>sync()).observe(sel,{childList:true});
  document.addEventListener("click",(e)=>{ if(!w.contains(e.target)) close();});
  sync(); build();
}
function initCustomSelects(){
  ["#wf-project","#wf-type","#up-project","#mi-project","#mi-type","#search-topk","#folder-project","#file-search-project","#file-search-limit"].forEach(id=>{ const el=document.querySelector(id); if(el&&el.tagName==="SELECT") enhanceSelect(el); });
  document.querySelectorAll(".write-form select, .upload-right select, .search-bar select").forEach(enhanceSelect);
}

if (!state.apiKey) showKeyModal();
else bootstrap();
setTimeout(initCustomSelects, 90);
setTimeout(initCustomSelects, 650);
document.addEventListener("DOMContentLoaded", initCustomSelects);
const _origFillProjectSelect = fillProjectSelect;
fillProjectSelect = async function(){ const r=await _origFillProjectSelect.apply(this, arguments); setTimeout(initCustomSelects, 60); return r; };
const _origFillUploadProjects = fillUploadProjects;
fillUploadProjects = async function(){ const r=await _origFillUploadProjects.apply(this, arguments); setTimeout(initCustomSelects, 60); return r; };

// live network indicator — browser online/offline events
window.addEventListener('online', () => {
  const net = document.getElementById("widget-network");
  if(net){ net.className="widget-val online"; net.innerHTML='<i class="wdot"></i> Online · Cloud Sync Active'; }
  refreshAll(false);
});
window.addEventListener('offline', () => {
  const net = document.getElementById("widget-network");
  if(net){ net.className="widget-val offline"; net.innerHTML='<i class="wdot"></i> Offline · Local Only'; }
  const apiPill = document.getElementById("pill-api");
  if(apiPill){ apiPill.innerHTML='<span class="dot red"></span><span>API offline</span>'; }
});

/* ══════════ Code Plugin — OpenCode ngầm :4096 ══════════ */
let codeOnline = false;
let codeIframeLoaded = false;

async function checkCodeHealth(){
  const els = ["#code-health-mini","#code-health-tab"];
  const dot = $("#code-fab-dot");
  try{
    const r = await api("/v1/code/health");
    codeOnline = r.status === "online";
    els.forEach(id=>{
      const el = document.querySelector(id);
      if(el) {
        el.textContent = codeOnline ? "● Online :4096" : (r.status==="offline"?"○ Offline :4096":"◐ "+r.status);
        el.style.color = codeOnline ? "var(--green)" : "var(--amber)";
      }
    });
    if(dot) dot.className = "fab-dot " + (codeOnline ? "online" : "offline");
    if(codeOnline && !codeIframeLoaded){
      // auto load iframe sau khi online
      setTimeout(()=> loadCodeIframe(), 400);
    }
    return r;
  } catch{
    els.forEach(id=>{ const el=document.querySelector(id); if(el) el.textContent="○ Offline"; });
    if(dot) dot.className="fab-dot offline";
    return {status:"offline"};
  }
}

async function getCodeAuthUrl(){
  // Use same-origin proxy :8100/code/ — no login popup, server injects Basic Auth
  return "/code/";
}
async function loadCodeIframe(){
  const iframe = $("#code-iframe");
  const tabIframe = $("#code-iframe-tab");
  const ph = $("#code-placeholder");
  const phTab = $("#code-placeholder-tab");
  const url = await getCodeAuthUrl();
  if(iframe && iframe.classList.contains("hidden")){
    iframe.src = url;
    iframe.classList.remove("hidden");
    if(ph) ph.classList.add("hidden");
    codeIframeLoaded = true;
    toast("🤖 OpenCode plugin đã kết nối (proxy /code/)");
  }
  if(tabIframe && tabIframe.classList.contains("hidden")){
    tabIframe.src = url;
    tabIframe.classList.remove("hidden");
    if(phTab) phTab.classList.add("hidden");
  }
}

function resetCodeIframe(){
  ["#code-iframe","#code-iframe-tab"].forEach(id=>{
    const el=document.querySelector(id); if(el){ el.src="about:blank"; el.classList.add("hidden"); }
  });
  ["#code-placeholder","#code-placeholder-tab"].forEach(id=>{
    const el=document.querySelector(id); if(el) el.classList.remove("hidden");
  });
  codeIframeLoaded = false;
}

// FAB toggle
$("#code-fab")?.addEventListener("click", ()=>{
  const p=$("#code-plugin");
  const isHidden = p.classList.contains("hidden");
  p.classList.toggle("hidden", !isHidden);
  if(isHidden){
    checkCodeHealth();
    $("#code-quick-input")?.focus();
  }
});
$("#code-close")?.addEventListener("click", ()=> $("#code-plugin")?.classList.add("hidden"));
$("#code-min")?.addEventListener("click", ()=>{
  const p=$("#code-plugin"); p.classList.toggle("mini");
  if(p.classList.contains("mini")) p.style.height="56px"; else p.style.height="520px";
});
$("#code-popout")?.addEventListener("click", ()=>{
  activateTab("code");
  const p=$("#code-plugin"); if(p) p.classList.add("hidden");
  checkCodeHealth();
  window.open("/code/", "_blank");
});

// Tab buttons
$("#code-launch")?.addEventListener("click", async ()=>{
  const el=$("#code-launch"); if(el) el.textContent="⏳ đang khởi…";
  await triggerCodeStart();
});
$("#code-launch-tab")?.addEventListener("click", triggerCodeStart);
$("#code-start-tab")?.addEventListener("click", triggerCodeStart);
$("#code-open-tab")?.addEventListener("click", ()=> window.open("/code/", "_blank"));
$("#code-stop-tab")?.addEventListener("click", async ()=>{
  const s=$("#code-status-tab"); if(s) s.textContent="⏳ dừng…";
  try{ await fetch("http://127.0.0.1:4096/",{method:"GET"}); }catch{}
  resetCodeIframe(); checkCodeHealth();
  if(s) s.textContent="Đã dừng (cần taskkill opencode.exe nếu vẫn chạy)";
});

async function triggerCodeStart(){
  const statusEls = ["#code-status-tab","#code-health-mini"];
  // Gọi ngầm: thử mở bat hidden qua fetch không được (browser cấm) -> hướng dẫn + tự poll
  const s=$("#code-status-tab"); if(s) s.textContent="Đang khởi OpenCode ngầm (5s)…";
  // Thử tự start bằng cách gọi tới D:\OPENCODE_WEB_HIDDEN.bat không thể từ browser -> thông báo manual
  toast("▶ Hãy chạy D:\\OPENCODE_WEB.bat hoặc bấm Start, đợi 5s rồi kiểm tra :4096");
  // poll 8s
  for(let i=0;i<8;i++){
    await new Promise(r=>setTimeout(r,1000));
    const h = await checkCodeHealth();
    if(h.status==="online"){ if(s) s.textContent="✅ Online"; loadCodeIframe(); return; }
  }
  if(s) s.textContent="○ Vẫn offline — chạy D:\\OPENCODE_WEB.bat";
}

// Quick input -> focus iframe + copy
$("#code-quick-send")?.addEventListener("click", ()=>{
  const inp=$("#code-quick-input"); const v=inp?.value.trim();
  if(!v) return;
  if(!codeOnline){ toast("OpenCode offline — bấm Start trước", true); return; }
  // Đưa text vào clipboard để paste nhanh vào iframe, đồng thời mở plugin full
  navigator.clipboard.writeText(v).then(()=> toast("📋 Đã copy — dán (Ctrl+V) vào OpenCode"));
  inp.value="";
  // Mở iframe nếu chưa
  if(!codeIframeLoaded) loadCodeIframe();
  // Focus iframe
  const ifr=$("#code-iframe"); if(ifr) ifr.focus();
});
$("#code-quick-input")?.addEventListener("keydown", (e)=>{
  if(e.key==="Enter") $("#code-quick-send")?.click();
  if(e.key==="Escape") $("#code-plugin")?.classList.add("hidden");
});

// Hook activateTab for code
const _origActivateTab = activateTab;
activateTab = function(name){
  _origActivateTab(name);
  if(name==="code") checkCodeHealth();
};

// Poll code health mỗi 12s
setInterval(checkCodeHealth, 12000);
async function fillCodePass(){
  try{
    const cfg = await api("/v1/code/config");
    const els = ["#code-pass-mini","#code-pass-tab"];
    els.forEach(id=>{ const el=document.querySelector(id); if(el&&cfg.password) el.textContent=cfg.password; });
  }catch{}
}
setTimeout(fillCodePass, 800);
setInterval(fillCodePass, 15000);
setTimeout(checkCodeHealth, 1500);

/* ══════════ LMStudio — Local LLM thông minh ══════════ */
async function checkLMStudioHealth(){
  const hEl=$("#lmstudio-health"), pill=$("#pill-lmstudio"), wEl=$("#widget-lmstudio"), pillW=$("#lmstudio-pill"), det=$("#lmstudio-detail"), modelsEl=$("#lmstudio-models");
  try{
    const r=await api("/v1/lmstudio/status");
    const lm=r.lmstudio, mode=r.mode;
    const isOn = lm.available && lm.llm_ready;
    const dot = isOn ? "green" : (lm.available ? "amber" : "red");
    const txt = isOn ? `● LMStudio ${lm.models.join(", ")}` : (lm.available ? `◐ Thiếu model` : "○ Offline");
    if(hEl){ hEl.textContent = isOn ? `● Online ${lm.latency_ms}ms` : txt; hEl.style.color = isOn ? "var(--green)" : "var(--amber)"; }
    if(pill){ pill.className=`pill ${isOn?"ok":"warn"}`; pill.innerHTML=`<span class="dot ${dot}"></span><span>${isOn?"LMStudio":"LMStudio off"}</span>`; pill.title = lm.models.join(", ") + ` ${lm.latency_ms}ms`; }
    if(wEl){ wEl.className=`widget-val ${isOn?"success":"offline"}`; wEl.innerHTML=`<i class="sicon">${isOn?"●":"○"}</i> ${isOn?"vistral ready":"Offline"}`; }
    if(pillW){ pillW.className=`widget-val ${isOn?"online":"offline"}`; pillW.innerHTML=`<i class="sicon">${isOn?"●":"○"}</i> ${isOn?"Online":"Offline"}`; }
    if(det){ det.innerHTML = `Mode: <b>${mode}</b> · ${r.recommendation}<br>LLM: ${lm.llm_ready?"✓ vistral":"✗"} · Embed: ${lm.embed_ready?"✓ nomic":"✗"} · <code>${lm.base}</code><br>Ollama: ${r.ollama.available?r.ollama.models.join(", "):"offline"}`; }
    if(modelsEl){
      modelsEl.innerHTML = (lm.models.length?lm.models:["—"]).map(m=>`<div class="metric-card"><div class="m-name">model</div><div class="m-value" style="font-size:14px">${esc(m)}</div><div class="m-detail">${lm.available?"ready":"offline"}</div></div>`).join("");
    }
    return r;
  } catch(e){
    if(hEl) hEl.textContent="○ Offline";
    if(pill){ pill.className="pill err"; pill.innerHTML=`<span class="dot red"></span><span>LMStudio off</span>`; }
    if(wEl){ wEl.className="widget-val offline"; wEl.innerHTML=`<i class="sicon">○</i> Offline`; }
  }
}
async function doLMStudioChat(){
  const prompt=$("#lmstudio-prompt")?.value.trim();
  const status=$("#lmstudio-status"), resp=$("#lmstudio-response");
  if(!prompt){ toast("Nhập prompt", true); return; }
  status.textContent="⏳ LMStudio đang suy nghĩ..."; status.className="write-result";
  resp.classList.remove("hidden"); resp.textContent="⏳ ...";
  try{
    // Gọi qua Mid Brain để dùng LMStudio (First Brain) thông minh nhất
    const r=await api("/v1/mid-brain/process", {method:"POST", json:{question: prompt}});
    resp.textContent = r.answer || JSON.stringify(r, null, 2);
    status.textContent="✅ Xong"; status.className="write-result ok";
    toast("🧠 LMStudio đã trả lời");
  } catch(e){
    // Fallback trực tiếp 1234 nếu Mid fail
    try{
      const r2 = await fetch("http://127.0.0.1:1234/v1/chat/completions", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({model:"vistral-7b-chat", messages:[{role:"user", content: prompt}], max_tokens:400, temperature:0.2})});
      const j=await r2.json();
      resp.textContent = j.choices?.[0]?.message?.content || JSON.stringify(j, null, 2);
      status.textContent="✅ Xong (direct)"; status.className="write-result ok";
    } catch(e2){
      status.textContent="❌ "+e.message; status.className="write-result err";
      resp.textContent="Lỗi: "+e.message;
    }
  }
}
$("#lmstudio-send")?.addEventListener("click", doLMStudioChat);
$("#lmstudio-prompt")?.addEventListener("keydown", (e)=>{ if(e.key==="Enter" && (e.ctrlKey||e.metaKey)) doLMStudioChat(); });
$("#lmstudio-switch-ollama")?.addEventListener("click", async ()=>{
  if(!confirm("Chuyển sang Ollama?")) return;
  const s=$("#lmstudio-status"); if(s) s.textContent="⏳ đang chuyển...";
  try{ const r=await fetch("/v1/lmstudio/switch?provider=ollama", {method:"POST", headers:{"X-API-Key":state.apiKey}}); const j=await r.json(); toast(j.detail||"Đã chuyển"); checkLMStudioHealth(); } catch(e){ toast("Cần chạy .\\scripts\\lmstudio.ps1 switch -Provider ollama", true); }
});
$("#lmstudio-switch-lmstudio")?.addEventListener("click", async ()=>{
  const s=$("#lmstudio-status"); if(s) s.textContent="⏳ đang chuyển...";
  try{ const r=await fetch("/v1/lmstudio/switch?provider=lmstudio", {method:"POST", headers:{"X-API-Key":state.apiKey}}); const j=await r.json(); toast(j.detail||"Đã chuyển"); checkLMStudioHealth(); } catch(e){ toast("Cần chạy .\\scripts\\lmstudio.ps1 switch -Provider lmstudio", true); }
});
// Hook tab
const _origActivateTab2 = activateTab;
activateTab = function(name){
  _origActivateTab2(name);
  if(name==="code") checkCodeHealth();
  if(name==="lmstudio") checkLMStudioHealth();
  if(name==="odc") checkODCHealth();
};

// ── ODC Studio ──
async function checkODCHealth(){
  const el=$("#odc-health-tab"), log=$("#odc-log-tab");
  try{
    const r=await api("/v1/odc/health");
    const online=r.status==="online";
    if(el){ el.textContent=online?"● ODC online :3001":"○ Offline :3001"; el.style.color=online?"var(--green)":"var(--amber)"; }
    if(log && online) log.textContent="ODC online — workflows: "+(r.detail?.workflows ?? "?");
    // ensure iframe loads
    const ifr=$("#odc-iframe-tab");
    if(ifr && online && !ifr.src.includes("/odc/")) ifr.src="/odc/";
    return r;
  }catch{
    if(el) el.textContent="○ ODC offline — chạy .\\scripts\\odc.ps1";
  }
}
$("#odc-start-tab")?.addEventListener("click", async()=>{
  const s=$("#odc-status-tab"); if(s) s.textContent="⏳ đang khởi :3001…";
  toast("▶ Chạy .\\scripts\\odc.ps1 hoặc D:\\ODC_WEB.bat, đợi 3s…");
  for(let i=0;i<6;i++){ await new Promise(r=>setTimeout(r,1000)); const h=await checkODCHealth(); if(h?.status==="online"){ if(s) s.textContent="✅ Online"; toast("◈ ODC đã online :3001"); return; } }
  if(s) s.textContent="○ Vẫn offline — chạy scripts\\odc.ps1";
});
$("#odc-open-tab")?.addEventListener("click", ()=> window.open("/odc/", "_blank"));
$("#odc-check-tab")?.addEventListener("click", checkODCHealth);
const _origActivateTab3 = activateTab;
activateTab = function(name){
  _origActivateTab3(name);
  if(name==="odc") checkODCHealth();
};
setInterval(checkODCHealth, 15000);
setTimeout(checkODCHealth, 1200);
setInterval(checkLMStudioHealth, 15000);
setTimeout(checkLMStudioHealth, 1000);

