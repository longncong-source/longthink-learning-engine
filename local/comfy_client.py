"""ComfyUI client for First Brain (local) — LONG-TERM image generation (offline).

ComfyUI must be running: python main.py --listen 127.0.0.1 --port 8188
API: POST /prompt {prompt: workflow_json} -> {prompt_id}, GET /history/{prompt_id}
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from local.config import BrainSettings


class ComfyUnavailable(RuntimeError):
    pass


# Minimal workflow template — text2image moon base (user can replace with custom workflow.json)
DEFAULT_WORKFLOW = {
    "3": {"inputs": {"seed": 0, "steps": 20, "cfg": 7, "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}, "class_type": "KSampler"},
    "4": {"inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}, "class_type": "CheckpointLoaderSimple"},
    "5": {"inputs": {"width": 512, "height": 512, "batch_size": 1}, "class_type": "EmptyLatentImage"},
    "6": {"inputs": {"text": "", "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
    "7": {"inputs": {"text": "", "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
    "8": {"inputs": {"samples": ["3", 0], "vae": ["4", 2]}, "class_type": "VAEDecode"},
    "9": {"inputs": {"filename_prefix": "longthink", "images": ["8", 0]}, "class_type": "SaveImage"},
}


class ComfyClient:
    def __init__(self, settings: BrainSettings | None = None, base_url: str | None = None, workflow_path: str | None = None) -> None:
        from local.config import get_brain_settings

        self.settings = settings or get_brain_settings()
        self.base_url = (base_url or getattr(self.settings, "comfy_url", "") or "http://127.0.0.1:8188").rstrip("/")
        self.workflow_path = workflow_path
        self._http = httpx.Client(timeout=30.0)

    def health(self) -> bool:
        try:
            r = self._http.get(f"{self.base_url}/system_stats", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def _load_workflow(self, prompt: str, negative: str = "", seed: int | None = None) -> dict:
        if self.workflow_path and Path(self.workflow_path).exists():
            wf = json.loads(Path(self.workflow_path).read_text(encoding="utf-8"))
        else:
            wf = json.loads(json.dumps(DEFAULT_WORKFLOW))
        # inject prompt
        if "6" in wf:
            wf["6"]["inputs"]["text"] = prompt
        if "7" in wf:
            wf["7"]["inputs"]["text"] = negative
        if seed is not None and "3" in wf:
            wf["3"]["inputs"]["seed"] = seed
        else:
            if "3" in wf:
                wf["3"]["inputs"]["seed"] = int(uuid.uuid4().int % 2_000_000_000)
        return wf

    def generate(self, prompt: str, negative: str = "", workflow_path: str | None = None, timeout: float = 240) -> dict[str, Any]:
        wf_path = workflow_path or self.workflow_path
        wf = self._load_workflow(prompt, negative)
        if wf_path and Path(wf_path).exists():
            wf = json.loads(Path(wf_path).read_text(encoding="utf-8"))
            # try to inject into CLIP nodes heuristically
            for nid, node in wf.items():
                if node.get("class_type") == "CLIPTextEncode" and "text" in node.get("inputs", {}):
                    # first CLIP is positive
                    if prompt and nid == "6":
                        node["inputs"]["text"] = prompt
                    if negative and nid == "7":
                        node["inputs"]["text"] = negative
                    break
        try:
            r = self._http.post(f"{self.base_url}/prompt", json={"prompt": wf, "client_id": str(uuid.uuid4())})
        except httpx.HTTPError as e:
            raise ComfyUnavailable(f"ComfyUI unreachable {self.base_url}: {e}") from e
        if r.status_code != 200:
            raise ComfyUnavailable(f"ComfyUI POST /prompt {r.status_code}: {r.text[:300]}")
        prompt_id = r.json().get("prompt_id")
        if not prompt_id:
            raise ComfyUnavailable("No prompt_id returned")
        # poll history
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                h = self._http.get(f"{self.base_url}/history/{prompt_id}", timeout=5)
                if h.status_code == 200:
                    data = h.json()
                    if prompt_id in data:
                        outputs = data[prompt_id].get("outputs", {})
                        for _, out in outputs.items():
                            if "images" in out:
                                images = out["images"]
                                if images:
                                    return {"prompt_id": prompt_id, "images": images, "raw": data[prompt_id]}
            except Exception:
                pass
            time.sleep(1.2)
        raise ComfyUnavailable(f"Timeout waiting for ComfyUI result {prompt_id}")

    def get_image(self, filename: str, subfolder: str = "", img_type: str = "output") -> bytes:
        r = self._http.get(f"{self.base_url}/view", params={"filename": filename, "subfolder": subfolder, "type": img_type})
        r.raise_for_status()
        return r.content

