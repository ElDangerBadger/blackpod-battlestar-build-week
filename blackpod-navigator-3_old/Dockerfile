# Production Dockerfile for React + Python fullstack (shadcn variant)
# Uses prebuilt base image for faster builds

# Build stage for frontend - uses base image with node_modules pre-installed
ARG BASE_IMAGE=node:20-slim
FROM ${BASE_IMAGE} AS frontend-builder

WORKDIR /app/frontend

# Copy frontend package files
COPY frontend/package*.json ./

# Install/update dependencies
# If base image has node_modules, npm install only adds new packages (fast)
# If no node_modules, does full install (slower but still works)
RUN npm install

# Copy frontend source code
COPY frontend/ ./

# Build the Vite frontend
ENV NODE_ENV=production
RUN npm run build

# Production image - Python backend serving static frontend
FROM python:3.11-slim AS runner

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/src ./src

# Copy built frontend to serve as static files
COPY --from=frontend-builder /app/frontend/dist ./static

# Runtime configuration (override via -e / orchestrator env).
# Serve the bundled frontend from the API and run in production mode.
ENV PORT=8000 \
    BPN_ENVIRONMENT=production \
    BPN_STATIC_DIR=static \
    BPN_PROVIDER=yfinance \
    BPN_CACHE_DIR=/app/.cache \
    BPN_ALLOW_E2B_PREVIEW=false \
    PYTHONUNBUFFERED=1

# Writable on-disk cache (survives restarts when mounted as a volume).
RUN mkdir -p /app/.cache

# Create non-root user for security
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 appuser && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Container-level readiness probe (provider configured + registry loaded).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4).status==200 else sys.exit(1)" || exit 1

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
