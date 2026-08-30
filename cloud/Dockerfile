FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY cloud/requirements.txt cloud/requirements-postgres.txt /tmp/
COPY cloud/requirements-documents.txt /tmp/requirements-documents.txt
RUN pip install --no-cache-dir -r /tmp/requirements-postgres.txt -r /tmp/requirements-documents.txt

COPY cloud /srv/cloud

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/health', timeout=3).status_code == 200 else 1)"

ENTRYPOINT ["python", "-m", "cloud.container_init"]
