FROM python:3.12-slim-bookworm

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Persistent SQLite storage — mount a volume at /data
RUN mkdir -p /data
ENV DATABASE_PATH=/data/course_alert.db

EXPOSE 5000

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
# Single worker is mandatory: APScheduler runs in-process
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]
