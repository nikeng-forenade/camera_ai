# Camera AI app image (for LXC / Docker deployment)
# Ollama runs as a separate service in docker-compose.yml.
# Pin to Debian 12 (bookworm): the floating python:3.12-slim tag now points to
# trixie, where some of the Intel/VA-API packages below are named differently.
# bookworm also matches the Debian 12 LXC that lxc/proxmox-create.sh creates.
FROM python:3.12-slim-bookworm

# Intel iGPU userspace — needed by OpenVINO GPU / Quick Sync.
# libgl1 + libglib2.0-0 are required by OpenCV (pulled in by ultralytics):
# without them cv2 fails to import with 'libGL.so.1: cannot open shared object'.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
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
