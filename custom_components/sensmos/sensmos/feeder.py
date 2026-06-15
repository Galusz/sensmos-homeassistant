"""Sensmos — karmienie noda encjami z HA.

Każde mapowanie {node_entity, ha_entity, unit}:
- nasłuch zmian stanu encji HA → konwersja jednostki → POST /data,
- throttle (min FEED_MIN_INTERVAL_S między pushami),
- keepalive co FEED_KEEPALIVE_S (encje na nodzie mają wiek — odświeżamy).
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .api import SensmosApi, SensmosApiError
from .const import FEED_KEEPALIVE_S, FEED_MIN_INTERVAL_S
from .units import convert

_LOGGER = logging.getLogger(__name__)


def _fmt(value: float) -> str:
    """Float → string dla FW (które czyta value jako tekst)."""
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


class Feeder:
    """Silnik karmienia jednego noda."""

    def __init__(
        self, hass: HomeAssistant, api: SensmosApi, feeds: list[dict[str, Any]]
    ) -> None:
        self._hass = hass
        self._api = api
        self._feeds = feeds
        self._unsubs: list = []
        self._last_push: dict[str, float] = {}   # node_entity → monotonic
        self._last_value: dict[str, str] = {}    # node_entity → ostatnio wysłane

    def start(self) -> None:
        ha_ids = [f["ha_entity"] for f in self._feeds]
        if not ha_ids:
            return
        self._unsubs.append(
            async_track_state_change_event(self._hass, ha_ids, self._on_state)
        )
        self._unsubs.append(
            async_track_time_interval(
                self._hass, self._keepalive, timedelta(seconds=FEED_KEEPALIVE_S)
            )
        )
        # początkowy push aktualnych wartości
        self._hass.async_create_task(self._push_all(force=True))

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ── handlers ──────────────────────────────────────────────

    @callback
    def _on_state(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        for feed in self._feeds:
            if feed["ha_entity"] == event.data["entity_id"]:
                self._hass.async_create_task(self._push_feed(feed, new_state))

    async def _keepalive(self, _now=None) -> None:
        await self._push_all(force=True)

    async def _push_all(self, force: bool = False) -> None:
        for feed in self._feeds:
            state = self._hass.states.get(feed["ha_entity"])
            if state is not None:
                await self._push_feed(feed, state, force=force)

    # ── push ──────────────────────────────────────────────────

    async def _push_feed(
        self, feed: dict[str, Any], state: State, force: bool = False
    ) -> None:
        node_entity: str = feed["node_entity"]
        target_unit: str = feed.get("unit") or ""

        if state.state in ("unknown", "unavailable", ""):
            return

        now = time.monotonic()
        if not force and now - self._last_push.get(node_entity, 0) < FEED_MIN_INTERVAL_S:
            return

        ha_unit = state.attributes.get("unit_of_measurement")
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            # stan nienumeryczny — wyślij surowy tekst
            await self._send(node_entity, state.state[:60], ha_unit or "")
            return

        unit_out = target_unit or ha_unit or ""
        if target_unit and ha_unit and target_unit != ha_unit:
            converted = convert(value, ha_unit, target_unit)
            if converted is None:
                _LOGGER.warning(
                    "Feed %s: jednostki %s→%s nieprzeliczalne, wysyłam surowo",
                    node_entity, ha_unit, target_unit,
                )
                unit_out = ha_unit
            else:
                value = converted

        out = _fmt(value)
        if not force and self._last_value.get(node_entity) == out:
            return  # bez zmiany — nie spamuj
        await self._send(node_entity, out, unit_out)

    async def _send(self, node_entity: str, value: str, unit: str) -> None:
        try:
            await self._api.push_data(node_entity, value, unit)
            self._last_push[node_entity] = time.monotonic()
            self._last_value[node_entity] = value
            _LOGGER.debug("Feed %s = %s %s", node_entity, value, unit)
        except SensmosApiError as err:
            _LOGGER.warning("Feed %s nie powiódł się: %s", node_entity, err)
