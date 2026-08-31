#!/bin/bash
# Camera AI — one-shot GPU fix & verify (run on the Proxmox HOST, as root).
#
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/nikeng-forenade/camera_ai/main/lxc/fix-gpu.sh)"
#   bash -c "$(...)" 202        # explicit container ID (default 202)
#
# Does, in one shot:
#   1. .env  -> YOLO_DEVICE=openvino:GPU
#   2. rebuilds the image + recreates the camera-ai container (new code)
#   3. verifies the running process normalizes 'gpu' -> openvino:GPU
#   4. verifies OpenVINO sees the Intel GPU
set -euo pipefail

CT_ID="${1:-202}"
APP="/root/camera-ai"

echo "=== Camera AI GPU fix/verify (CT $CT_ID) ==="

pct status "$CT_ID" >/dev/null 2>&1 || { echo "ERROR: container $CT_ID not found"; exit 1; }

echo ""
echo "--- 1. .env: YOLO_DEVICE ---"
pct exec "$CT_ID" -- bash -c "cd '$APP' && sed -i 's/^YOLO_DEVICE=.*/YOLO_DEVICE=openvino:GPU/' .env && grep YOLO_DEVICE .env"

echo ""
echo "--- 2. Rebuilding image + recreating camera-ai ---"
pct exec "$CT_ID" -- bash -c "cd '$APP' && docker compose up -d --build --force-recreate camera-ai"

echo ""
echo "--- 3. Running code check (expect True) ---"
pct exec "$CT_ID" -- docker exec camera-ai python -c "import analyzer; print('has _normalize_device:', hasattr(analyzer.YoloAnalyzer, '_normalize_device'))"

echo ""
echo "--- 4. Device normalization (expect openvino:GPU) ---"
pct exec "$CT_ID" -- docker exec camera-ai python -c "from analyzer import YoloAnalyzer; print('gpu ->', YoloAnalyzer(device='gpu').device)"

echo ""
echo "--- 5. OpenVINO devices (expect GPU listed) ---"
pct exec "$CT_ID" -- docker exec camera-ai python -c "import openvino as ov; print(ov.Core().available_devices)"

echo ""
echo "=== Klart! Analysera en bild i GUI:t, sedan: ==="
echo "    pct exec $CT_ID -- docker logs camera-ai | grep '\\[analyzer\\]'"
