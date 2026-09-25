# --- Build Stage ---
FROM python:3.13-slim AS builder

WORKDIR /app

COPY requirements.txt .
# FIX: Removed --no-deps so it builds wheels for all sub-dependencies and extras
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# --- Production Stage ---
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create unprivileged system user
RUN groupadd -r scrapergroup && useradd -r -g scrapergroup -s /sbin/nologin scraperuser

WORKDIR /app

# Copy built wheels and requirements
COPY --from=builder /app/wheels /wheels
COPY requirements.txt .

# FIX: Install using requirements.txt so pip respects the [binary] extra tag
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels

# Copy application script
COPY scraper.py .

# Enforce non-root ownership and execution
RUN chown -R scraperuser:scrapergroup /app
USER scraperuser

CMD ["python", "scraper.py"]
