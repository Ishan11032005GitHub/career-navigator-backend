# ---------- Base Image ----------
FROM python:3.11-slim

# ---------- Environment ----------
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ---------- System Setup ----------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl git build-essential wget \
        texlive-latex-base texlive-latex-recommended \
        texlive-fonts-recommended texlive-latex-extra \
        tini && \
    rm -rf /var/lib/apt/lists/*

# ---------- Install Ollama ----------
RUN curl -fsSL https://ollama.com/install.sh | sh

# ---------- Working Directory ----------
WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Ensure start script is executable
RUN chmod +x /app/start.sh

# ---------- Expose Ports ----------
EXPOSE 8000
EXPOSE 11434

# ---------- Entrypoint + Command ----------
# tini acts as PID 1 and forwards signals properly
ENTRYPOINT ["/usr/bin/tini", "--"]

# JSON-form CMD, no more shell-form nonsense
CMD ["/app/start.sh"]
