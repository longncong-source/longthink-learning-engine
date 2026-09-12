FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx pydantic

COPY organization_core /srv/organization_core

EXPOSE 8101

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8101/health', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "organization_core.service"]
