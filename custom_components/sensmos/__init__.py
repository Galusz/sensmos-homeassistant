"""Sensmos — integracja noda ESP32 z Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo

from .api import SensmosApi, SensmosApiError, SensmosAuthError
from .const import (
    CONF_HOST,
    CONF_PIN,
    DOMAIN,
    OPT_FEEDS,
    OPT_WEBHOOK,
    PLATFORMS,
)
from .coordinator import SensmosCoordinator
from .feeder import Feeder
from .webhook import async_remove_node_webhook, async_setup_node_webhook

_LOGGER = logging.getLogger(__name__)

SERVICE_PUSH_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Required("entity_id"): cv.string,
        vol.Required("value"): cv.string,
        vol.Optional("unit", default=""): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = SensmosApi(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PIN]
    )

    try:
        cfg = await api.config()
    except SensmosAuthError as err:
        raise ConfigEntryAuthFailed("invalid_pin") from err
    except SensmosApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    device_id = cfg.get("device_id", entry.unique_id or "unknown")

    info = {}
    try:
        info = await api.info()
    except SensmosApiError:
        pass

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=entry.title,
        manufacturer="Sensmos",
        model="ESP32 Node",
        sw_version=str(info.get("version") or info.get("firmware") or ""),
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )

    coordinator = SensmosCoordinator(hass, api, device_id)
    await coordinator.async_config_entry_first_refresh()

    feeder = Feeder(hass, api, entry.options.get(OPT_FEEDS, []))
    feeder.start()

    if entry.options.get(OPT_WEBHOOK, True):
        await async_setup_node_webhook(hass, api, device_id)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "feeder": feeder,
        "device_info": device_info,
        "device_id": device_id,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data:
        data["feeder"].stop()
        await async_remove_node_webhook(
            hass, None, data["device_id"], clear_node=False
        )
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Opcje zmienione (mapowania/webhook) → przeładuj wpis."""
    await hass.config_entries.async_reload(entry.entry_id)


# ── Serwisy ───────────────────────────────────────────────────


def _entry_data_for_call(hass: HomeAssistant, call: ServiceCall) -> dict:
    """Znajdź dane wpisu po device_id z rejestru HA (albo jedyny wpis)."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("Brak skonfigurowanych nodów Sensmos")

    ha_device_id = call.data.get("device_id")
    if not ha_device_id:
        if len(entries) == 1:
            return next(iter(entries.values()))
        raise ValueError("Wiele nodów — wskaż device_id")

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(ha_device_id)
    if device:
        for ident in device.identifiers:
            if ident[0] == DOMAIN:
                for data in entries.values():
                    if data["device_id"] == ident[1]:
                        return data
    # fallback: potraktuj jako device_id Sensmos
    for data in entries.values():
        if data["device_id"].startswith(ha_device_id):
            return data
    raise ValueError(f"Nie znaleziono noda: {ha_device_id}")


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "push"):
        return

    async def handle_push(call: ServiceCall) -> None:
        data = _entry_data_for_call(hass, call)
        api: SensmosApi = data["api"]
        await api.push_data(
            call.data["entity_id"], call.data["value"], call.data.get("unit", "")
        )

    hass.services.async_register(
        DOMAIN, "push", handle_push, schema=SERVICE_PUSH_SCHEMA
    )
