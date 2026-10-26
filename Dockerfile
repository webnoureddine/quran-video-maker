FROM python:3.12-slim
# ffmpeg (with libass + HarfBuzz for Arabic captions) and raqm for accurate text measuring
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libraqm0 fontconfig \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data WORK_DIR=/tmp/mqv-work PORT=8000 HF_HOME=/data/models
VOLUME ["/data"]
EXPOSE 8000
# one process (jobs live in memory), many threads for the API; renders run as child processes
CMD ["sh", "-c", "gunicorn -w 1 --threads 16 --timeout 600 -b 0.0.0.0:${PORT} app.server:app"]
