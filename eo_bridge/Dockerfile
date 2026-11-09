FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The build context is this folder, so the package lives at /app/eo_bridge.
COPY . /app/eo_bridge

# Railway services that are configured with the literal command `python main.py`
# need an entry file at /app; this launcher runs the real package entry point.
COPY railway_entry.py /app/main.py

# Fail the build instead of the deploy if the package is not importable.
RUN python -c "import eo_bridge.app, eo_bridge.main, eo_bridge.settings" && \
    test -f /app/eo_bridge/main.py && test -f /app/main.py

EXPOSE 8080

CMD ["python", "-m", "eo_bridge.main"]
