# Camera AI app image (for LXC / Docker deployment)
# Ollama runs as a separate service in docker-compose.yml.
FROM python:3.12-slim

# Intel iGPU userspace — needed by OpenVINO GPU / Quick Sync
RUN apt-get update && apt-get install -y --no-install-recommends \
        intel-opencl-icd ocl-icd-libopencl1 mesa-vulkan-drivers vainfo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt openvino

COPY . .

# Default to the bundled Ollama service from compose; override as needed
ENV LLM_BACKEND=ollama
ENV OLLAMA_URL=http://ollama:11434
ENV OLLAMA_MODEL=moondream
ENV HA_ENABLED=0

EXPOSE 8000

CMD ["python", "app.py"]
