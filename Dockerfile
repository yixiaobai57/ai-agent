# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# 两阶段构建：node 编前端 → python 跑后端，最终镜像里没有 node_modules
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SESSION_BACKEND=sqlite \
    DATA_DIR=/app/data \
    WORKSPACE_DIR=/app/workspace

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/dist ./frontend/dist

# 运行期无需 root；/app/data 与 /app/workspace 需要可写
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /app/data /app/workspace \
    && chown -R agent:agent /app/data /app/workspace
USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["python", "main.py"]
