LMStudio Smart Complete 20260830-041013
- Smart: LMStudio vistral-7b-chat (LLM) + nomic 768d (embed) — tự phát hiện LMStudio > Ollama > offline
- Backend: cloud/app/config lmstudio, embeddings truncate 768->384 fallback 768 full, services/lmstudio_service, routers/lmstudio, code_proxy /code
- Frontend: pill-lmstudio + tab LMStudio + widget + FAB plugin /code proxy (no login)
- Scripts: lmstudio.ps1 (status/test/switch), start_all auto LMStudio, serve, comfy, code
- Test: LMStudio health 200 246ms, status lmstudio mode, UI v20260831i, doctor PASS, mid-brain process OK
