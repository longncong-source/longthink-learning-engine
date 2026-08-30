"""ODC Studio — Visual Data Orchestration for LongThink :3001

Lightweight Studio that speaks LongThink protocols:
- Canvas: RETRIEVE → THINK → PLAN → EXECUTE → STORE → VERIFY
- Runs workflows by calling Second Brain APIs (:8100)
- No external deps beyond FastAPI/uvicorn already in venv
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

LONGTHINK_URL = "http://127.0.0.1:8100"
API_KEY = "dev-local-key"

app = FastAPI(title="ODC Studio", version="1.0.0")

WORKFLOWS: dict[str, dict] = {}

# ── Health ──
@app.get("/health")
async def health():
    return {"status": "ok", "service": "odc-studio", "version": "1.0.0"}

@app.get("/api/health")
async def api_health():
    # proxy check LongThink
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{LONGTHINK_URL}/health")
            lt = r.json() if r.status_code == 200 else {"status": "offline"}
    except Exception as e:
        lt = {"status": "offline", "error": str(e)}
    return {"odc": "online", "longthink": lt, "workflows": len(WORKFLOWS)}

# ── Workflows CRUD ──
@app.get("/api/workflows")
async def list_workflows():
    return {"workflows": list(WORKFLOWS.values())}

@app.post("/api/workflows")
async def create_workflow(payload: dict):
    wid = payload.get("id") or f"wf_{uuid.uuid4().hex[:8]}"
    wf = {
        "id": wid,
        "name": payload.get("name", "Untitled"),
        "nodes": payload.get("nodes", []),
        "edges": payload.get("edges", []),
        "created_at": time.time(),
    }
    WORKFLOWS[wid] = wf
    return wf

@app.get("/api/workflows/{wf_id}")
async def get_workflow(wf_id: str):
    if wf_id not in WORKFLOWS:
        return JSONResponse({"error": "not found"}, status_code=404)
    return WORKFLOWS[wf_id]

@app.delete("/api/workflows/{wf_id}")
async def delete_workflow(wf_id: str):
    WORKFLOWS.pop(wf_id, None)
    return {"deleted": wf_id}

# ── Run workflow: execute nodes sequentially calling LongThink ──
@app.post("/api/run")
async def run_workflow(payload: dict):
    """payload: {workflow: {nodes, edges} | workflow_id, input: {query, project_id}}"""
    wf = payload.get("workflow")
    if not wf and payload.get("workflow_id"):
        wf = WORKFLOWS.get(payload["workflow_id"])
    if not wf:
        return JSONResponse({"error": "workflow required"}, status_code=400)
    inp = payload.get("input", {})
    query = inp.get("query", "LongThink ODC test")
    project_id = inp.get("project_id")
    steps = []
    # Simulate orchestrator: each node type maps to an API call
    nodes = wf.get("nodes", [])
    # Ensure order by x or explicit order; fallback to list order
    for n in nodes:
        t = n.get("type", "unknown")
        label = n.get("label", t)
        start = time.time()
        result: Any = None
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                if t == "retrieve":
                    r = await c.post(f"{LONGTHINK_URL}/v1/memory/search",
                                     headers={"X-API-Key": API_KEY},
                                     json={"query": query, "top_k": 3})
                    result = r.json() if 200 <= r.status_code < 300 else {"error": r.text}
                elif t == "think":
                    r = await c.post(f"{LONGTHINK_URL}/v1/mid-brain/process",
                                     headers={"X-API-Key": API_KEY},
                                     json={"question": query, "project_id": project_id})
                    result = r.json() if 200 <= r.status_code < 300 else {"error": r.text}
                elif t == "store":
                    r = await c.post(f"{LONGTHINK_URL}/v1/memory",
                                     headers={"X-API-Key": API_KEY},
                                     json={"title": f"ODC run {label}", "content": f"ODC Studio workflow result for: {query}", "type": "lesson", "importance": 0.7})
                    result = r.json() if 200 <= r.status_code < 300 else {"error": r.text}
                elif t == "comfy":
                    r = await c.get(f"{LONGTHINK_URL}/v1/comfy/health", headers={"X-API-Key": API_KEY})
                    result = r.json()
                elif t == "code":
                    r = await c.get(f"{LONGTHINK_URL}/v1/code/health", headers={"X-API-Key": API_KEY})
                    result = r.json()
                else:
                    result = {"echo": label, "input": query}
        except Exception as e:
            result = {"error": str(e)}
        steps.append({"node": label, "type": t, "duration_ms": int((time.time()-start)*1000), "result": result})
    return {"workflow": wf.get("name", "run"), "input": inp, "steps": steps, "done": True}

# ── UI ──
UI_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>ODC Studio · LongThink</title>
<style>
:root{--bg:#0b0f14;--panel:#111827;--border:#1f2937;--text:#e5e7eb;--muted:#9ca3af;--accent:#06ffa5;--accent2:#8b5cf6;--orange:#fb923c}
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column;height:100vh}
header{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--border);background:linear-gradient(90deg,#0b0f14,#111827)}
.logo{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,var(--accent2),var(--accent));display:grid;place-items:center;font-weight:800}
h1{font-size:15px;margin:0}.sub{font-size:11px;color:var(--muted)}
.badge{margin-left:auto;font-size:11px;padding:4px 8px;border-radius:999px;background:#065f46;color:#6ee7b7;border:1px solid #047857}
main{flex:1;display:grid;grid-template-columns:220px 1fr 300px;gap:0;overflow:hidden}
.palette{border-right:1px solid var(--border);background:var(--panel);padding:10px;overflow:auto}
.palette h3{font-size:11px;letter-spacing:.08em;color:var(--muted);margin:8px 0}
.node-btn{width:100%;text-align:left;padding:8px 10px;margin:4px 0;border-radius:8px;border:1px solid var(--border);background:#0f172a;color:var(--text);cursor:pointer;font-size:12px;display:flex;align-items:center;gap:8px}
.node-btn:hover{border-color:var(--accent);background:#13233a}
.node-btn i{width:22px;height:22px;border-radius:6px;display:grid;place-items:center;font-size:12px}
.canvas{position:relative;background:radial-gradient(circle at 1px 1px,#1f2937 1px,transparent 0);background-size:22px 22px;overflow:auto;padding:24px}
.workflow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-height:200px;padding:20px;border:1px dashed #334155;border-radius:12px;background:#0f172a88}
.w-node{min-width:140px;padding:12px;border-radius:10px;border:1px solid var(--border);background:#111827;text-align:center;position:relative}
.w-node.retrieve{border-color:#60a5fa}.w-node.think{border-color:var(--accent)}.w-node.plan{border-color:#f472b6}.w-node.execute{border-color:var(--orange)}.w-node.store{border-color:#34d399}
.w-node .k{font-size:10px;letter-spacing:.08em;color:var(--muted)}.w-node .t{font-size:13px;font-weight:700;margin-top:4px}
.arrow{font-size:18px;color:var(--muted)}
.inspector{border-left:1px solid var(--border);background:var(--panel);padding:12px;overflow:auto}
.inspector h3{font-size:11px;color:var(--muted);margin:0 0 8px}
textarea,input,select{width:100%;background:#0b1220;color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px;font-size:12px}
button.primary{width:100%;padding:10px;border-radius:8px;border:none;background:linear-gradient(135deg,var(--accent2),var(--accent));color:#001010;font-weight:800;cursor:pointer;margin-top:8px}
button.ghost{width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--text);cursor:pointer;margin-top:6px}
.log{margin-top:10px;max-height:240px;overflow:auto;background:#0b1220;border:1px solid var(--border);border-radius:8px;padding:8px;font-size:11px;white-space:pre-wrap}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:11px;padding:4px 8px;border-radius:999px;border:1px solid var(--border);background:#0f172a}
.dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 6px #22c55e}
</style>
</head>
<body>
<header>
  <div class="logo">◈</div>
  <div><h1>ODC Studio <span style="font-weight:400;color:var(--muted)">— Visual Orchestration for LongThink</span></h1><div class="sub">RETRIEVE → THINK → PLAN → EXECUTE → STORE · proxy via :8100/odc</div></div>
  <span class="badge"><span class="dot"></span> ODC online · LongThink <span id="lt-status">checking…</span></span>
</header>
<main>
  <div class="palette">
    <h3>PALETTE — KÉO VÀO CANVAS</h3>
    <button class="node-btn" data-type="retrieve"><i style="background:#1e3a5f">◉</i> RETRIEVE — Search</button>
    <button class="node-btn" data-type="think"><i style="background:#064e3b">⬢</i> THINK — Mid Brain</button>
    <button class="node-btn" data-type="plan"><i style="background:#4a1942">⬣</i> PLAN — Planner</button>
    <button class="node-btn" data-type="execute"><i style="background:#5a2e0a">⚡</i> EXECUTE — Comfy/Code</button>
    <button class="node-btn" data-type="store"><i style="background:#0f3a2a">✓</i> STORE — Memory</button>
    <button class="node-btn" data-type="comfy"><i style="background:#3b1f0a">🎨</i> Comfy — Image</button>
    <button class="node-btn" data-type="code"><i style="background:#1e1b4b">🤖</i> Code — OpenCode</button>
    <h3 style="margin-top:14px">TEMPLATE</h3>
    <button class="node-btn" id="tpl-learning"><i style="background:#312e81">📚</i> Learning Loop</button>
    <button class="node-btn" id="tpl-creative"><i style="background:#7c2d12">✨</i> Creative Pipeline</button>
    <button class="node-btn" id="tpl-dev"><i style="background:#14532d">💻</i> Dev Pipeline</button>
  </div>
  <div class="canvas">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
      <span class="pill"><span class="dot"></span> Canvas — bấm node ở trái để thêm</span>
      <button class="ghost" style="width:auto;padding:6px 10px;margin-left:auto" id="clear">🗑 Clear</button>
      <button class="ghost" style="width:auto;padding:6px 10px" id="save">💾 Save</button>
    </div>
    <div class="workflow" id="wf"></div>
    <div style="margin-top:12px;color:var(--muted);font-size:11px">Mẹo: Workflow chạy tuần tự gọi <code>:8100/v1/memory/search</code> → <code>/v1/mid-brain/process</code> → <code>/v1/memory</code>. Kết quả hiện ở Inspector.</div>
  </div>
  <div class="inspector">
    <h3>INPUT</h3>
    <label style="font-size:11px;color:var(--muted)">Query / Question</label>
    <textarea id="q" rows="3" placeholder="VD: Tóm tắt bài học về hybrid search…">LongThink ODC demo — hybrid search + mid brain</textarea>
    <label style="font-size:11px;color:var(--muted);margin-top:8px;display:block">Project ID (optional)</label>
    <input id="pid" placeholder="— không gán —"/>
    <button class="primary" id="run">▶ Run Workflow</button>
    <button class="ghost" id="check">⟡ Check LongThink</button>
    <h3 style="margin-top:12px">LOG</h3>
    <div class="log" id="log">Chưa chạy.</div>
    <h3 style="margin-top:12px">WORKFLOW JSON</h3>
    <textarea id="j" rows="6" style="font-family:monospace;font-size:11px"></textarea>
  </div>
</main>
<script>
const wfEl=document.getElementById('wf'), logEl=document.getElementById('log'), qEl=document.getElementById('q'), pidEl=document.getElementById('pid'), jEl=document.getElementById('j');
let nodes=[];
const TYPE_LABEL={retrieve:'RETRIEVE',think:'THINK',plan:'PLAN',execute:'EXECUTE',store:'STORE',comfy:'COMFY',code:'CODE'};
function render(){
  wfEl.innerHTML='';
  if(!nodes.length){ wfEl.innerHTML='<span style="color:var(--muted)">Trống — chọn node bên trái</span>'; }
  nodes.forEach((n,i)=>{
    const d=document.createElement('div'); d.className='w-node '+n.type;
    d.innerHTML=`<div class="k">${TYPE_LABEL[n.type]||n.type}</div><div class="t">${n.label}</div><div style="position:absolute;top:4px;right:6px;cursor:pointer;color:var(--muted)" data-i="${i}">✕</div>`;
    d.querySelector('[data-i]').onclick=()=>{ nodes.splice(i,1); render(); sync(); };
    wfEl.appendChild(d);
    if(i<nodes.length-1){ const a=document.createElement('div'); a.className='arrow'; a.textContent='→'; wfEl.appendChild(a); }
  });
  sync();
}
function sync(){ jEl.value=JSON.stringify({name:'ODC Workflow',nodes},null,2); }
document.querySelectorAll('.node-btn[data-type]').forEach(b=> b.onclick=()=>{
  const t=b.dataset.type; nodes.push({type:t,label:TYPE_LABEL[t]||t}); render();
});
document.getElementById('clear').onclick=()=>{ nodes=[]; render(); };
document.getElementById('tpl-learning').onclick=()=>{ nodes=[{type:'retrieve',label:'RETRIEVE'},{type:'think',label:'THINK'},{type:'store',label:'STORE'}]; render(); };
document.getElementById('tpl-creative').onclick=()=>{ nodes=[{type:'retrieve',label:'RETRIEVE'},{type:'think',label:'THINK'},{type:'comfy',label:'COMFY'},{type:'store',label:'STORE'}]; render(); };
document.getElementById('tpl-dev').onclick=()=>{ nodes=[{type:'retrieve',label:'RETRIEVE'},{type:'code',label:'CODE'},{type:'store',label:'STORE'}]; render(); };
document.getElementById('save').onclick=async()=>{
  const r=await fetch('/api/workflows',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'ODC-'+Date.now(),nodes})});
  const j=await r.json(); logEl.textContent='Saved '+j.id+'\\n'+JSON.stringify(j,null,2);
};
async function check(){
  try{ const r=await fetch('/api/health'); const j=await r.json(); document.getElementById('lt-status').textContent=j.longthink.status||'offline'; logEl.textContent=JSON.stringify(j,null,2); }catch(e){ logEl.textContent='check fail '+e; }
}
document.getElementById('check').onclick=check;
document.getElementById('run').onclick=async()=>{
  const payload={workflow:{name:'ODC run',nodes},input:{query:qEl.value.trim(),project_id:pidEl.value.trim()||null}};
  logEl.textContent='⏳ Running '+nodes.length+' nodes…';
  try{
    const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await r.json();
    logEl.textContent=JSON.stringify(j,null,2);
  }catch(e){ logEl.textContent='Run fail '+e; }
};
check(); nodes=[{type:'retrieve',label:'RETRIEVE'},{type:'think',label:'THINK'},{type:'store',label:'STORE'}]; render();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(UI_HTML)

# also serve at /odc for proxy compatibility
@app.get("/odc", response_class=HTMLResponse)
async def ui_odc():
    return HTMLResponse(UI_HTML)
