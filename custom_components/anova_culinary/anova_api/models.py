"""Typed models shared by every Anova device, mirroring the apps' own schemas.

Anova's wire format is camelCase JSON; each field names its wire key with `wire()`.
Every field has a default, so a state that leaves a node out still parses.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.dict import DataClassDictMixin


def wire(name: str, default: Any = None, factory: Any = None) -> Any:
    """A dataclass field read from and written to the wire key `name`."""
    metadata = field_options(alias=name)
    if factory is not None:
        return field(default_factory=factory, metadata=metadata)
    return field(default=default, metadata=metadata)


class AnovaModel(DataClassDictMixin):
    """Base for wire models: parsed from and serialized to Anova's JSON."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


@dataclass
class AnovaTemperature(AnovaModel):
    """A temperature; Anova's current protocols carry Celsius only."""

    celsius: float | None = None


@dataclass
class AnovaTimerNode(AnovaModel):
    """A device's timer: `initial` seconds, counting from `startedAtTimestamp` while running."""

    mode: str = "idle"  # idle, running, paused, completed
    initial: int | None = None
    started_at_timestamp: str | None = wire("startedAtTimestamp")

    def remaining(self, now: datetime) -> int | None:
        """Seconds left: the whole timer until it runs, counting down while running."""
        if self.initial is None:
            return None
        if self.mode != "running" or not self.started_at_timestamp:
            return 0 if self.mode == "completed" else self.initial
        elapsed = (now - parse_timestamp(self.started_at_timestamp)).total_seconds()
        return max(0, int(self.initial - elapsed))


@dataclass
class AnovaOtaUpdate(AnovaModel):
    """A firmware update in progress."""

    mode: str = "default"
    progress: float | None = None


@dataclass
class AnovaSystemInfo(AnovaModel):
    """A device's connectivity and firmware."""

    online: bool = False
    device_id: str | None = wire("deviceId")
    firmware_version: str | None = wire("firmwareVersion")
    hardware_version: str | None = wire("hardwareVersion")
    release_track: str | None = wire("releaseTrack")
    firmware_updated_timestamp: str | None = wire("firmwareUpdatedTimestamp")
    last_connected_timestamp: str | None = wire("lastConnectedTimestamp")
    last_disconnected_timestamp: str | None = wire("lastDisconnectedTimestamp")
    triacs_failed: bool | None = wire("triacsFailed")
    ota_update: AnovaOtaUpdate | None = wire("otaUpdate")


@dataclass
class AnovaCook(AnovaModel):
    """The cook a device is running: its stages (wire format) and where it is in them."""

    cook_id: str = wire("cookId", "")
    stages: list[dict[str, Any]] = field(default_factory=list)
    active_stage_id: str = wire("activeStageId", "")
    active_stage_index: int = wire("activeStageIndex", 0)
    active_stage_mode: str | None = wire("activeStageMode")  # entering, running
    active_stage_started_timestamp: str | None = wire("activeStageStartedTimestamp")
    started_timestamp: str | None = wire("startedTimestamp")
    cookable_type: str | None = wire("cookableType")  # manual, recipe, guide, ...
    cookable_id: str | None = wire("cookableId")
    origin_source: str | None = wire("originSource")

    @property
    def active_stage(self) -> dict[str, Any] | None:
        """The running stage, by id (falling back to its index)."""
        for stage in self.stages:
            if stage.get("id") == self.active_stage_id:
                return stage
        if 0 <= self.active_stage_index < len(self.stages):
            return self.stages[self.active_stage_index]
        return None


def parse_timestamp(value: str) -> datetime:
    """An Anova ISO 8601 timestamp (e.g. 2026-04-12T05:16:14Z) as an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
