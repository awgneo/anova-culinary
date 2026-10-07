"""The base of every Anova device: identity, typed state, availability and listeners."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from .models import AnovaModel
from .product import AnovaProduct

if TYPE_CHECKING:
    from .client import AnovaClient

_LOGGER = logging.getLogger(__name__)

StateT = TypeVar("StateT", bound=AnovaModel)


class AnovaDevice(Generic[StateT]):
    """A paired device: updated from its state events, controlled through the client."""

    product: ClassVar[AnovaProduct]
    state_class: ClassVar[type[AnovaModel]]
    # The device types this class supports, with their product names
    models: ClassVar[dict[str, str]]

    def __init__(self, client: AnovaClient, id: str, type: str, name: str = "") -> None:
        """Initialize from the device list's entry."""
        self._client = client
        self.id = id
        self.type = type
        self.name = name or self.model
        self.state: StateT | None = None
        self._callbacks: list[Callable[[], None]] = []

    @property
    def model(self) -> str:
        """The product name, e.g. Anova Precision Oven 2.0."""
        return self.models[self.type]

    @property
    def available(self) -> bool:
        """Whether the device is reachable: connected to us, reported, and online."""
        return self._client.connected and self.state is not None and self.state.system_info.online

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Calls `callback` on every state or availability change; returns its remover."""
        self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback)

    def update(self, state: dict[str, Any]) -> None:
        """Takes a state event's state."""
        try:
            self.state = self.state_class.from_dict(state)
        except Exception:
            _LOGGER.exception("%s sent a state that couldn't be read: %s", self.name, state)
            return
        self.notify()

    def notify(self) -> None:
        """Tells every listener the device changed."""
        for callback in list(self._callbacks):
            callback()

    async def _request(self, message: dict[str, Any]) -> dict[str, Any]:
        """Sends a command and returns its response."""
        return await self._client.request(message)
