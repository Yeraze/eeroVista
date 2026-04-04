"""MQTT client wrapper with connection management."""

import json
import logging
import threading
from typing import Any, Optional

import paho.mqtt.client as mqtt

from src.config import Settings

logger = logging.getLogger(__name__)


class MQTTClient:
    """Manages MQTT broker connection and message publishing."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """Connect to the MQTT broker. Returns True if successful."""
        if self._connected and self._client and self._client.is_connected():
            return True

        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self._settings.mqtt_client_id,
            )

            if self._settings.mqtt_username:
                self._client.username_pw_set(
                    self._settings.mqtt_username,
                    self._settings.mqtt_password,
                )

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect

            # Set last will to mark availability as offline
            self._client.will_set(
                f"{self._settings.mqtt_topic_prefix}/status",
                payload="offline",
                qos=self._settings.mqtt_qos,
                retain=True,
            )

            self._client.connect(
                self._settings.mqtt_broker,
                self._settings.mqtt_port,
                keepalive=60,
            )
            self._client.loop_start()

            # Wait briefly for connection
            for _ in range(50):
                if self._connected:
                    return True
                import time
                time.sleep(0.1)

            logger.warning("MQTT connection timed out after 5s")
            return False

        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self._client:
            # Publish offline status before disconnecting
            self.publish(
                f"{self._settings.mqtt_topic_prefix}/status",
                "offline",
            )
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            self._client = None

    def publish(self, topic: str, payload: Any, retain: Optional[bool] = None) -> bool:
        """Publish a message to an MQTT topic.

        Args:
            topic: MQTT topic string
            payload: Message payload (str or dict, dicts are JSON-encoded)
            retain: Override default retain setting

        Returns:
            True if published successfully
        """
        if not self._client or not self._connected:
            return False

        if retain is None:
            retain = self._settings.mqtt_retain

        if isinstance(payload, dict):
            payload = json.dumps(payload)

        try:
            result = self._client.publish(
                topic,
                payload=payload,
                qos=self._settings.mqtt_qos,
                retain=retain,
            )
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self._connected = True
            logger.info(
                f"Connected to MQTT broker at "
                f"{self._settings.mqtt_broker}:{self._settings.mqtt_port}"
            )
            # Publish online status
            self.publish(
                f"{self._settings.mqtt_topic_prefix}/status",
                "online",
            )
        else:
            self._connected = False
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False
        if reason_code != 0:
            logger.warning(f"Unexpected MQTT disconnect: {reason_code}")
