FROM python:3.11-slim

ARG RAILWAY_GIT_COMMIT_SHA=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ROZLF_BUILD_SHA=${RAILWAY_GIT_COMMIT_SHA} \
    ROZLF_ROLE=worker

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python scripts/verify_build.py

CMD ["sh", "-c", "python scripts/verify_build.py && exec python main.py"]
