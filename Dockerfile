# Camera AI app image (for LXC / Docker deployment)
# Ollama runs as a separate service in docker-compose.yml.
FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to the bundled Ollama service from compose; override as needed
ENV LLM_BACKEND=ollama
ENV OLLAMA_URL=http://ollama:11434
ENV OLLAMA_MODEL=moondream
ENV HA_ENABLED=0

EXPOSE 8000

CMD ["python", "app.py"]
