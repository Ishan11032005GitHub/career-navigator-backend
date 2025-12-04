#!/usr/bin/env bash
set -e

echo "[startup] Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# crude wait to let it boot; adjust if needed
sleep 10

echo "[startup] Pulling model gemma3:4b (if not present)..."
ollama pull gemma3:4b || true

echo "[startup] Starting FastAPI (Uvicorn)..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
