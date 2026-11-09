FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The build context is this folder, so the service lives at /app/eo_bridge
# and is started as a module (keeping its relative imports intact).
COPY . /app/eo_bridge

EXPOSE 8080

CMD ["python", "-m", "eo_bridge.main"]
