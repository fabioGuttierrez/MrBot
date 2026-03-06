#!/bin/bash
# ============================================================
# deploy.sh — Script de deploy do MrBot no VPS
# Executar na VPS como: bash deploy.sh
# ============================================================
set -e

echo "🚀 Iniciando deploy do MrBot..."

# ── 1. Atualizar código ──────────────────────────────────────
echo "[1/5] Atualizando código..."
git pull origin main

# ── 2. Build e subir containers ──────────────────────────────
echo "[2/5] Build dos containers..."
docker compose -f docker-compose.prod.yml build --no-cache

echo "[3/5] Subindo containers..."
docker compose -f docker-compose.prod.yml up -d

# ── 3. Aguardar Redis ────────────────────────────────────────
echo "[4/5] Aguardando Redis..."
sleep 5

# ── 4. Migrations ────────────────────────────────────────────
echo "[5/5] Aplicando migrations..."
docker compose -f docker-compose.prod.yml exec web \
    python manage.py migrate --noinput

echo ""
echo "✅ Deploy concluído!"
echo "   App rodando em: https://$(grep APP_BASE_URL .env | cut -d= -f2)"
