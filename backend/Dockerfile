FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
RUN apt-get update && apt-get install -y --no-install-recommends default-mysql-client clamav-daemon ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.lock /app/backend/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r backend/requirements.lock
COPY backend/app /app/backend/app
COPY database /app/database
COPY database /app/backend/database
COPY scripts /app/scripts
COPY deploy/clamd.conf /etc/clamav/clamd.remote.conf
RUN useradd --create-home --uid 10001 chemicalops && mkdir -p /app/storage /app/backups/mysql && chown -R chemicalops:chemicalops /app/storage /app/backups
USER chemicalops
EXPOSE 8888
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888", "--proxy-headers", "--forwarded-allow-ips", "*"]
