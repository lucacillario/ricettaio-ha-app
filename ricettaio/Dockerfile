FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-alpine3.21

ARG BUILD_VERSION="dev"
ARG BUILD_ARCH="unknown"

LABEL \
    io.hass.name="RicettAIo" \
    io.hass.description="Ricettario personale con assistente AI" \
    io.hass.type="app" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="RicettAIo" \
    org.opencontainers.image.licenses="Apache-2.0"

RUN apk add --no-cache libjpeg-turbo libwebp su-exec tiff zlib \
    && addgroup -S ricettaio \
    && adduser -S -G ricettaio -h /app ricettaio

WORKDIR /app
COPY backend/ /app/backend/
RUN pip install --no-cache-dir /app/backend
COPY --from=frontend-build /build/frontend/dist/ /app/frontend/
COPY run.sh /run.sh

RUN chmod 755 /run.sh \
    && mkdir -p /data /app/frontend \
    && chown -R ricettaio:ricettaio /data /app

EXPOSE 8099
ENV RICETTAIO_DATA_DIR=/data \
    RICETTAIO_OPTIONS_PATH=/data/options.json \
    RICETTAIO_FRONTEND_DIR=/app/frontend \
    RICETTAIO_VERSION=${BUILD_VERSION} \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/api/v1/health', timeout=3)"

CMD ["/run.sh"]
