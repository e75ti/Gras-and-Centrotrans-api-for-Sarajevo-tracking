# --- Build Stage ---
FROM python:3.13-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# --- Production Stage ---
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create unprivileged system user
RUN groupadd -r scrapergroup && useradd -r -g scrapergroup -s /sbin/nologin scraperuser

WORKDIR /app

# Install pre-built wheels from builder
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application script
COPY scraper.py .

# Enforce non-root ownership and execution
RUN chown -R scraperuser:scrapergroup /app
USER scraperuser

CMD ["python", "scraper.py"]
