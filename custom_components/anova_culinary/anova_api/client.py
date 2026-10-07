"""Anova API Client: one account's connection and its devices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from .apc.device import AnovaPCDevice
from .apo.device import AnovaPODevice
from .auth import AnovaAuth
from .connection import AnovaConnection
from .device import AnovaDevice
from .exceptions import AnovaAuthError
from .product import AnovaProduct

_LOGGER = logging.getLogger(__name__)

DEVICE_CLASSES: dict[AnovaProduct, type[AnovaDevice]] = {
    AnovaProduct.APO: AnovaPODevice,
    AnovaProduct.APC: AnovaPCDevice,
}
# How long connect() waits for the first device list
DISCOVERY_TIMEOUT = 10


class AnovaClient:
    """Client for interacting with Anova WiFi devices."""

    def __init__(self, token: str, session: aiohttp.ClientSession) -> None:
        """Initialize from a refresh token kept from sign-in."""
        self.session = session
        self._auth = AnovaAuth(session, token)
        self._connection = AnovaConnection(
            session, self._auth, self._handle_message, self._handle_connection, self._handle_auth_error
        )
        self._devices: dict[str, AnovaDevice] = {}
        self._device_callbacks: list[Callable[[AnovaDevice, bool], None]] = []
        self._auth_error_callbacks: list[Callable[[AnovaAuthError], None]] = []
        self._discovered = asyncio.Event()
        self._unsupported: set[str] = set()

    @property
    def devices(self) -> dict[str, AnovaDevice]:
        """Return discovered devices."""
        return self._devices

    @property
    def connected(self) -> bool:
        """Whether the WebSocket is open."""
        return self._connection.connected

    @property
    def user_id(self) -> str | None:
        """The signed-in account's user id, once connected."""
        return self._auth.user_id

    async def connect(self) -> None:
        """Connects, and waits briefly for the device list so devices exist before setup continues."""
        await self._connection.connect()
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT):
                await self._discovered.wait()
        except TimeoutError:
            _LOGGER.warning("Anova sent no device list within %ds", DISCOVERY_TIMEOUT)

    async def close(self) -> None:
        """Close connection."""
        await self._connection.close()

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        """Sends a command and returns its response."""
        return await self._connection.request(message)

    def register_device_callback(self, callback: Callable[[AnovaDevice, bool], None]) -> Callable[[], None]:
        """Calls `callback(device, added)` when a device is paired or removed; returns its remover."""
        self._device_callbacks.append(callback)
        return lambda: self._device_callbacks.remove(callback)

    def register_auth_error_callback(self, callback: Callable[[AnovaAuthError], None]) -> Callable[[], None]:
        """Calls `callback(error)` when Anova stops accepting the sign-in; returns its remover."""
        self._auth_error_callbacks.append(callback)
        return lambda: self._auth_error_callbacks.remove(callback)

    def _handle_message(self, data: dict[str, Any]) -> None:
        """Handles an event: device lists, pairing changes and device states."""
        command = data.get("command", "")
        payload = data.get("payload")
        for product in DEVICE_CLASSES:
            prefix = f"EVENT_{product.value}_"
            if not command.startswith(prefix):
                continue
            event = command.removeprefix(prefix)
            if event == "WIFI_LIST" and isinstance(payload, list):
                self._process_discovery(product, payload)
            elif event == "WIFI_ADDED" and isinstance(payload, dict):
                self._add_device(product, payload)
            elif event == "WIFI_REMOVED" and isinstance(payload, dict):
                self._remove_device(payload.get("cookerId", ""))
            elif event == "STATE" and isinstance(payload, dict):
                device = self._devices.get(payload.get("cookerId", ""))
                if device is not None and isinstance(payload.get("state"), dict):
                    device.update(payload["state"])
            return

    def _process_discovery(self, product: AnovaProduct, pairings: list[dict[str, Any]]) -> None:
        """Takes a full device list for one product: adds new devices and removes unpaired ones."""
        listed = {pairing.get("cookerId") for pairing in pairings}
        for device in [d for d in self._devices.values() if d.product == product and d.id not in listed]:
            self._remove_device(device.id)
        for pairing in pairings:
            self._add_device(product, pairing)
        self._discovered.set()

    def _add_device(self, product: AnovaProduct, pairing: dict[str, Any]) -> None:
        """Adds a paired device of a supported type."""
        device_id, device_type = pairing.get("cookerId"), pairing.get("type", "")
        if not device_id or device_id in self._devices:
            return
        device_class = DEVICE_CLASSES[product]
        if device_type not in device_class.models:
            if device_id not in self._unsupported:
                self._unsupported.add(device_id)
                _LOGGER.info("Skipping %s (%s): only the latest Anova devices are supported", device_id, device_type)
            return
        device = device_class(self, device_id, device_type, pairing.get("name", ""))
        self._devices[device_id] = device
        _LOGGER.info("Discovered %s: %s (%s)", product.value, device_id, device.model)
        for callback in list(self._device_callbacks):
            callback(device, True)

    def _remove_device(self, device_id: str) -> None:
        """Removes a device that was unpaired."""
        if (device := self._devices.pop(device_id, None)) is None:
            return
        _LOGGER.info("Removed %s: %s", device.product.value, device_id)
        for callback in list(self._device_callbacks):
            callback(device, False)

    def _handle_connection(self, connected: bool) -> None:
        """Marks every device available or unavailable with the connection."""
        for device in self._devices.values():
            device.notify()

    def _handle_auth_error(self, error: AnovaAuthError) -> None:
        """Passes a rejected sign-in on."""
        for callback in list(self._auth_error_callbacks):
            callback(error)
