FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

ENV PORT=5002
EXPOSE 5002

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5002} --workers 2 --timeout 120 'app:create_app()'"]
