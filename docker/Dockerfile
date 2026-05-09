FROM python:3.11-slim

# Non-root user for sandbox isolation
RUN useradd -m -u 1000 runner

WORKDIR /app

COPY ../requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ../src /app/src

ENV PYTHONUNBUFFERED=1
ENV PORT=5000
ENV DATASETS_DIR=/app/datasets
ENV OUTPUT_DIR=/app/output
ENV RUN_TIMEOUT_S=300

# Read-only datasets, writeable output (mounted by docker-compose)
RUN mkdir -p /app/datasets /app/output && chown -R runner:runner /app

USER runner

EXPOSE 5000

CMD ["python", "/app/src/runner.py"]
