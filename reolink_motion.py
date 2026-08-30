"""Optional: Reolink motion → AI pipeline (the real-world version of the GUI).

The test GUI uploads files; this script grabs a snapshot from a Reolink camera
on motion and runs the SAME analyzer pipeline, then sends the result on.

Facts about the Reolink HTTP snapshot API:
  GET http://<host>/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=<token>&user=<user>&password=<pass>
  (rs is a signed token; for newer firmware use 'snap' command with token, or
   use the RTSP snapshot route instead:
   ffmpeg -rtsp_transport tcp -i "rtsp://user:pass@host:554/h264Preview_01_main" -frames:v 1 snap.jpg)

Run:
  python reolink_motion.py

Env vars: REOLINK_HOST, REOLINK_USER, REOLINK_PASS, MQTT_HOST, MQTT_PORT, MQTT_TOPIC
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

import config
from analyzer import YoloAnalyzer, describe_with_ollama

analyzer = YoloAnalyzer()


def fetch_snapshot(out_path: Path) -> None:
    """Try the Reolink HTTP snapshot API, fall back to a clear error."""
    host = config.REOLINK_HOST
    if not host:
        raise RuntimeError("REOLINK_HOST not set — configure in config.py or env vars.")
    params = {
        "cmd": "Snap",
        "channel": 0,
        "rs": "wuwPxxHrR8zo4LKwAA",  # default rs token on many Reolink firmwares
        "user": config.REOLINK_USER,
        "password": config.REOLINK_PASS,
    }
    url = f"http://{host}/cgi-bin/api.cgi?{urlencode(params)}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)


def send_mqtt(topic: str, payload: dict) -> None:
    """Optional: publish the result to Home Assistant over MQTT (paho-mqtt)."""
    try:
        import paho.mqtt.client as mqtt  # pip install paho-mqtt
    except ImportError:
        print("[mqtt] paho-mqtt not installed — skipping publish")
        return
    client = mqtt.Client()
    client.connect(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")), 60)
    client.publish(topic, json.dumps(payload), qos=1)
    client.disconnect()


def main() -> None:
    snap = config.UPLOAD_DIR / f"reolink_{int(time.time())}.jpg"
    fetch_snapshot(snap)
    print(f"[camera] snapshot saved: {snap}")

    result = analyzer.analyze(snap)
    print(f"[yolo] {len(result['detections'])} object(s): "
          f"{[d['class'] for d in result['detections']]}")

    description = None
    if config.LLM_BACKEND == "ollama":
        try:
            description = describe_with_ollama(snap)
            print(f"[llm] {description}")
        except Exception as exc:  # noqa: BLE001
            print(f"[llm] failed: {exc}")

    payload = {
        "ts": int(time.time()),
        "detections": result["detections"],
        "description": description,
        "annotated": result["annotated"],
    }
    print(json.dumps(payload, indent=2))

    if os.getenv("MQTT_TOPIC"):
        send_mqtt(os.getenv("MQTT_TOPIC"), payload)


if __name__ == "__main__":
    main()
