FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Coleta estáticos na build (precisa de SECRET_KEY mínima)
RUN SECRET_KEY=build-only-placeholder \
    DATABASE_URL=postgres://x:x@localhost/x \
    python manage.py collectstatic --noinput

EXPOSE 8000
