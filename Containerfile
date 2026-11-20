# Frecklebubby: one image with the web app, REST API and MCP server.
# Build: podman build -t frecklebubby -f Containerfile .   (or docker build)

# Stage 1: build the web app (SvelteKit, static files).
FROM docker.io/library/node:24-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Output goes to /src/src/frecklebubby/static (see frontend/vite.config.ts).
RUN npm run build

# Stage 2: install the Python app with uv. git is needed for the optional Huckleberry import extra.
# The cry extra (onnxruntime) runs the cry models. The model files are in the package (src/frecklebubby/data).
FROM docker.io/library/python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra import --extra cry --no-install-project
COPY src/ ./src/
COPY --from=web /src/src/frecklebubby/static ./src/frecklebubby/static
RUN uv sync --frozen --no-dev --extra import --extra cry --no-editable

# Stage 3: run as a non-root user. ffmpeg decodes the cry helper's recordings (webm/opus, mp4/aac).
FROM docker.io/library/python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 app && mkdir /data && chown app:app /data
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH DATA_DIR=/data HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
USER app
WORKDIR /data
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
CMD ["frecklebubby"]
