FROM python:3.12-slim

ARG XRAY_VERSION=26.3.27
ARG TARGETARCH=amd64

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XRAY_LOCATION_ASSET=/opt/xray

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip passwd \
    && rm -rf /var/lib/apt/lists/*

# Xray-core is bundled so the panel can generate, validate and run configs.
RUN case "$TARGETARCH" in \
        amd64) asset="Xray-linux-64.zip" ;; \
        arm64) asset="Xray-linux-arm64-v8a.zip" ;; \
        *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && mkdir -p /opt/xray \
    && curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${asset}" -o /tmp/xray.zip \
    && unzip -q /tmp/xray.zip -d /opt/xray \
    && install -m 0755 /opt/xray/xray /usr/local/bin/xray \
    && rm -rf /tmp/xray.zip

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system --gid 10001 spectergate \
    && useradd --uid 10001 --gid spectergate --create-home --shell /usr/sbin/nologin spectergate \
    && mkdir -p /app/data/xray /app/data \
    && chown -R spectergate:spectergate /app

COPY --chown=spectergate:spectergate app ./app

USER spectergate

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
