FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    IMAGES_DIR=/data/images \
    MATERIALS_DIR=/data/materials \
    PORT=8900 \
    HF_HOME=/data/huggingface \
    XDG_CACHE_HOME=/data/cache \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

# Run as a normal user; the host data directory must be writable by uid 1000
# (see README: chown -R 1000:1000 /vol2/1000/study if needed).
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin study \
    && mkdir -p /data \
    && chown -R study:study /app /data
USER study

EXPOSE 8900

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8900/health', timeout=3).status == 200 else 1)"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8900"]
