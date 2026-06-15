"""Sensmos — sensory: dane subskrypcji (sub.*) + statusy noda (GALU, uptime)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, POOL_EXCLUDED_PREFIXES
from .coordinator import SensmosCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: SensmosCoordinator = data["coordinator"]
    device_info: DeviceInfo = data["device_info"]

    # statusy noda
    entities: list[SensorEntity] = [
        GaluSensor(coordinator, device_info, "available", "GALU dostępne", "mdi:hand-coin"),
        GaluSensor(coordinator, device_info, "pending_galu", "GALU do odebrania", "mdi:download"),
        UptimeSensor(coordinator, device_info),
    ]

    known: set[str] = set()

    @callback
    def _discover_pool() -> None:
        new: list[SensorEntity] = []
        for ent in coordinator.pool_entities:
            eid = ent.get("entity_id", "")
            if not eid or eid in known:
                continue
            if eid.startswith(POOL_EXCLUDED_PREFIXES):
                continue
            known.add(eid)
            new.append(PoolSensor(coordinator, device_info, eid))
        if new:
            async_add_entities(new)

    async_add_entities(entities)
    _discover_pool()
    entry.async_on_unload(coordinator.async_add_listener(_discover_pool))


class _Base(CoordinatorEntity[SensmosCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SensmosCoordinator, device_info: DeviceInfo
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info


class PoolSensor(_Base):
    """Encja z subskrypcji (sub.* / prefix usera) widoczna w HA."""

    def __init__(
        self, coordinator: SensmosCoordinator, device_info: DeviceInfo, entity_id: str
    ) -> None:
        super().__init__(coordinator, device_info)
        self._eid = entity_id
        self._attr_unique_id = f"{coordinator.device_id}_pool_{entity_id}"
        self._attr_name = entity_id
        self._attr_state_class = SensorStateClass.MEASUREMENT

    def _find(self) -> dict[str, Any] | None:
        for ent in self.coordinator.pool_entities:
            if ent.get("entity_id") == self._eid:
                return ent
        return None

    @property
    def available(self) -> bool:
        return super().available and self._find() is not None

    @property
    def native_value(self) -> Any:
        ent = self._find()
        if ent is None:
            return None
        val = ent.get("value")
        try:
            f = float(val)
            return int(f) if f == int(f) else round(f, 4)
        except (TypeError, ValueError):
            self._attr_state_class = None
            return val

    @property
    def native_unit_of_measurement(self) -> str | None:
        ent = self._find()
        return (ent or {}).get("unit") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ent = self._find() or {}
        return {"age_s": ent.get("age_s")}


class GaluSensor(_Base):
    """Saldo GALU z portfela właściciela noda."""

    _attr_native_unit_of_measurement = "GALU"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3

    def __init__(
        self,
        coordinator: SensmosCoordinator,
        device_info: DeviceInfo,
        field: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, device_info)
        self._field = field
        self._attr_unique_id = f"{coordinator.device_id}_{field}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def native_value(self) -> float | None:
        wallet = (self.coordinator.data or {}).get("wallet") or {}
        val = wallet.get(self._field)
        try:
            return round(float(val), 4)
        except (TypeError, ValueError):
            return None


class UptimeSensor(_Base):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_entity_registry_enabled_default = True
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, coordinator: SensmosCoordinator, device_info: DeviceInfo
    ) -> None:
        super().__init__(coordinator, device_info)
        self._attr_unique_id = f"{coordinator.device_id}_uptime"
        self._attr_name = "Uptime"

    @property
    def native_value(self) -> int | None:
        status = (self.coordinator.data or {}).get("status") or {}
        return status.get("uptime_s")
