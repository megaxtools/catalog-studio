#!/usr/bin/env bash
# نصب روی لینوکس / WSL / macOS
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install "rembg[cpu]" || echo "[i] rembg نصب نشد؛ موتور داخلی استفاده می‌شود."
.venv/bin/python -m playwright install chromium || true
.venv/bin/python -c "from studio.images import ensure_model; ensure_model('isnet-general-use')" || true
echo "نصب تمام شد. با ./run.sh اجرا کنید."
