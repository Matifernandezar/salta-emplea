FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home emplea && mkdir -p /data/uploads && chown -R emplea:emplea /data /app
COPY --chown=emplea:emplea . .
USER emplea
ENV APP_ENV=production DATABASE_PATH=/data/salta.sqlite3 UPLOAD_DIR=/data/uploads
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "45", "--error-logfile", "-", "wsgi:app"]
