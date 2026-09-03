"""Home Assistant integration for Camera AI.

Two transports, both make HA "see" detection results — no custom component needed:

1. MQTT + auto-discovery  (default, recommended)
   HA's built-in MQTT integration auto-creates entities from discovery topics
   (no YAML, no restart) — the same mechanism Frigate uses. Entities created:
     - binary_sensor.camera_ai_<id>_motion    (device_class: motion)
     - sensor.camera_ai_<id>_last_detection   (JSON: classes + confidence)
     - sensor.camera_ai_<id>_description      (LLM scene description)
     - image.camera_ai_<id>_snapshot          (annotated snapshot)

2. REST API  (alternative)
   Pushes a state entity update and fires a `camera_ai_result` event that
   automations can listen for (long-lived access token).

Enable via env vars (see config.py). When disabled the client is inert.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

import requests

log = logging.getLogger("ha")


class HAClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.camera_id = cfg.HA_CAMERA_ID
        self._base = f"camera_ai/{self.camera_id}"
        self._mqtt = None
        self._alarm_callback = None
        self._alarm_topic = getattr(cfg, "HA_ALARM_TOPIC", "homeassistant/alarm_control_panel/+/state")

    def on_alarm_state(self, fn) -> None:
        """Registrera callback som anropas nar HA-larmets tillstand andras."""
        self._alarm_callback = fn

    # ------------------------------------------------------------------ status
    def available(self) -> bool:
        return bool(self.cfg.HA_ENABLED)

    def status(self) -> dict:
        if not self.available():
            return {"enabled": False, "transport": None, "connected": False}
        if self.cfg.HA_TRANSPORT == "mqtt":
            connected = bool(self._mqtt and self._mqtt.is_connected())
        else:
            connected = bool(self.cfg.HA_REST_URL and self.cfg.HA_REST_TOKEN)
        return {"enabled": True, "transport": self.cfg.HA_TRANSPORT, "connected": connected}

    # ---------------------------------------------------------------- connect
    def connect(self) -> None:
        """Connect to the configured transport. Safe to call at startup."""
        if not self.available():
            return
        if self.cfg.HA_TRANSPORT == "mqtt":
            self._connect_mqtt()

    def reconnect(self) -> None:
        """Koppla från ev. gammal MQTT-klient och återanslut med nuvarande config.

        Anropas när HA-inställningar ändrats från GUI:t. Uppdaterar även
        camera_id/topics om HA_CAMERA_ID ändrats. Vid avstängd HA kopplas bara
        från (ingen återanslutning).
        """
        old = self._mqtt
        self._mqtt = None
        if old is not None:
            try:
                old.loop_stop()
            except Exception:  # noqa: BLE001 - bästa möjliga
                pass
            try:
                old.disconnect()
            except Exception:  # noqa: BLE001 - bästa möjliga
                pass
        self.camera_id = self.cfg.HA_CAMERA_ID
        self._base = f"camera_ai/{self.camera_id}"
        self.connect()

    def _connect_mqtt(self) -> None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(client_id=f"camera_ai_{self.camera_id}")
        if self.cfg.HA_MQTT_USER:
            client.username_pw_set(self.cfg.HA_MQTT_USER, self.cfg.HA_MQTT_PASS)
        client.connect(self.cfg.HA_MQTT_HOST, self.cfg.HA_MQTT_PORT, 30)
        client.loop_start()
        self._mqtt = client
        client.on_message = self._on_message
        client.subscribe(self._alarm_topic)
        self.publish_discovery()
        self.set_availability(True)
        log.info("[ha] mqtt connected to %s:%s (alarm topic %s)",
                 self.cfg.HA_MQTT_HOST, self.cfg.HA_MQTT_PORT, self._alarm_topic)

    def _on_message(self, client, userdata, msg) -> None:
        """Hantera inkommande MQTT (just nu: larmstatus)."""
        try:
            state = msg.payload.decode("utf-8").strip().lower()
            if self._alarm_callback:
                self._alarm_callback(state)
        except Exception as exc:  # noqa: BLE001
            log.warning("[ha] alarm message error: %s", exc)

    def set_availability(self, online: bool) -> None:
        if self._mqtt:
            self._mqtt.publish(
                f"{self._base}/availability", "online" if online else "offline", retain=True
            )

    # ------------------------------------------------------------- discovery
    def publish_discovery(self) -> None:
        """Publish HA MQTT discovery configs so entities appear automatically."""
        prefix = self.cfg.HA_DISCOVERY_PREFIX
        cam = self.camera_id
        av = f"{self._base}/availability"
        device = {
            "identifiers": [f"camera_ai_{cam}"],
            "name": "Camera AI",
            "manufacturer": "Camera AI",
            "model": "Reolink + YOLO + LLM",
            "sw_version": "0.13.0",
        }
        configs = {
            f"{prefix}/binary_sensor/camera_ai_{cam}/config": {
                "name": "Motion detected",
                "state_topic": f"{self._base}/detection",
                "device_class": "motion",
                "payload_on": "ON",
                "payload_off": "OFF",
                "availability_topic": av,
                "unique_id": f"camera_ai_{cam}_motion",
                "device": device,
            },
            f"{prefix}/sensor/camera_ai_{cam}/config": {
                "name": "Last detection",
                "state_topic": f"{self._base}/result",
                "value_template": "{{ value_json.classes }}",
                "json_attributes_topic": f"{self._base}/result",
                "availability_topic": av,
                "unique_id": f"camera_ai_{cam}_result",
                "device": device,
            },
            f"{prefix}/sensor/camera_ai_{cam}_desc/config": {
                "name": "Scene description",
                "state_topic": f"{self._base}/description",
                "availability_topic": av,
                "unique_id": f"camera_ai_{cam}_description",
                "device": device,
            },
            f"{prefix}/image/camera_ai_{cam}/config": {
                "name": "Snapshot",
                "image_topic": f"{self._base}/snapshot",
                "availability_topic": av,
                "unique_id": f"camera_ai_{cam}_snapshot",
                "device": device,
            },
        }
        for topic, cfg in configs.items():
            self._mqtt.publish(topic, json.dumps(cfg), retain=True)
        log.info("[ha] discovery published (%d entities)", len(configs))

    # -------------------------------------------------------------- publish
    def publish_result(
        self,
        detections: list,
        description: str | None,
        annotated_path: str | None = None,
        camera: str | None = None,
    ) -> None:
        """Send an analysis result to Home Assistant."""
        if not self.available():
            log.debug("[ha] disabled, skipping publish")
            return
        if self.cfg.HA_TRANSPORT == "mqtt":
            self._publish_mqtt(detections, description, annotated_path, camera)
        elif self.cfg.HA_TRANSPORT == "rest":
            self._publish_rest(detections, description, camera)

    def _publish_mqtt(
        self, detections: list, description: str | None, annotated_path: str | None, camera: str | None
    ) -> None:
        if not (self._mqtt and self._mqtt.is_connected()):
            raise RuntimeError("MQTT not connected — check HA_MQTT_* env vars and the broker")
        payload = {
            "camera": camera,
            "classes": [d["class"] for d in detections],
            "count": len(detections),
            "confidence": {d["class"]: d["confidence"] for d in detections},
            "ts": int(time.time()),
        }
        self._mqtt.publish(f"{self._base}/detection", "ON" if detections else "OFF")
        self._mqtt.publish(f"{self._base}/result", json.dumps(payload))
        self._mqtt.publish(f"{self._base}/description", (description or "").strip()[:500])
        if annotated_path and Path(annotated_path).exists():
            b64 = base64.b64encode(Path(annotated_path).read_bytes()).decode("ascii")
            self._mqtt.publish(f"{self._base}/snapshot", b64)

    def _publish_rest(self, detections: list, description: str | None, camera: str | None) -> None:
        if not (self.cfg.HA_REST_URL and self.cfg.HA_REST_TOKEN):
            raise RuntimeError("HA_REST_URL / HA_REST_TOKEN not set")
        url = self.cfg.HA_REST_URL.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.cfg.HA_REST_TOKEN}",
            "Content-Type": "application/json",
        }
        classes = [d["class"] for d in detections]
        # 1) update a state entity
        requests.post(
            f"{url}/api/states/sensor.camera_ai_{self.camera_id}_detection",
            json={
                "state": "ON" if detections else "OFF",
                "attributes": {
                    "classes": classes,
                    "count": len(classes),
                    "description": description or "",
                    "confidence": {d["class"]: d["confidence"] for d in detections},
                },
            },
            headers=headers,
            timeout=10,
        ).raise_for_status()
        # 2) fire an event automations can listen for
        requests.post(
            f"{url}/api/events/camera_ai_result",
            json={"detections": detections, "description": description},
            headers=headers,
            timeout=10,
        ).raise_for_status()
