FROM node:20-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt
COPY medibytes/ ./medibytes/
COPY evaluation/ ./evaluation/
COPY tools/ ./tools/
COPY --from=frontend /build/frontend/dist ./frontend/dist
ENV PYTHONUNBUFFERED=1 \
    MEDIBYTES_HOST=0.0.0.0 \
    MEDIBYTES_PORT=8000 \
    HF_HOME=/data/hf \
    MEDIBYTES_RUNS=/data/runs
CMD ["python", "-m", "medibytes.api"]
