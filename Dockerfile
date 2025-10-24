# ---------- Base Image ----------
FROM python:3.11-slim

# ---------- System Setup ----------
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl git build-essential wget \
        texlive-latex-base texlive-latex-recommended \
        texlive-fonts-recommended texlive-latex-extra && \
    rm -rf /var/lib/apt/lists/*

# ---------- Install Ollama ----------
RUN curl -fsSL https://ollama.com/install.sh | sh

# ---------- Working Directory ----------
WORKDIR /app
COPY . .

# ---------- Install Python Dependencies ----------
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Expose Ports ----------
EXPOSE 8000
EXPOSE 11434

# ---------- Start Ollama + FastAPI ----------
CMD bash -c "\
    ollama serve & \
    sleep 10 && \
    ollama pull gemma3:4b || true && \
    uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
