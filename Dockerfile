# ---------- Base Image ----------
FROM python:3.11-slim

# ---------- Environment ----------
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ---------- System Dependencies ----------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl git build-essential wget \
        texlive-latex-base texlive-latex-recommended \
        texlive-fonts-recommended texlive-latex-extra \
        tini && \
    rm -rf /var/lib/apt/lists/*

# ---------- Working Directory ----------
WORKDIR /app

# Install Python dependencies first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Run startup verification
RUN python startup_check.py || echo "⚠️ Startup check warnings (may not block deployment)"

# ---------- Expose Port ----------
EXPOSE 8000

# ---------- Entrypoint + CMD ----------
ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
