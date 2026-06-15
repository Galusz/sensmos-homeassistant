"""Sensmos — koordynator odpytujący node."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SensmosApi, SensmosApiError
from .const import DOMAIN, SCAN_INTERVAL_S, SLOW_EVERY_N_CYCLES

_LOGGER = logging.getLogger(__name__)


class SensmosCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Status co 30 s; config/wallet/native co N cykli."""

    def __init__(
        self, hass: HomeAssistant, api: SensmosApi, device_id: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_id[:8]}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_S),
        )
        self.api = api
        self.device_id = device_id
        self._cycle = 0
        self._slow: dict[str, Any] = {"config": {}, "wallet": {}, "native": []}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.api.data_status()
        except SensmosApiError as err:
            raise UpdateFailed(str(err)) from err

        if self._cycle % SLOW_EVERY_N_CYCLES == 0:
            for key, call in (
                ("config", self.api.config),
                ("wallet", self.api.wallet_balance),
            ):
                try:
                    self._slow[key] = await call()
                except SensmosApiError as err:
                    _LOGGER.debug("Slow fetch %s failed: %s", key, err)
            try:
                native = await self.api.data_native()
                self._slow["native"] = native.get("entities", [])
            except SensmosApiError as err:
                _LOGGER.debug("Slow fetch native failed: %s", err)
        self._cycle += 1

        return {"status": status, **self._slow}

    @property
    def pool_entities(self) -> list[dict[str, Any]]:
        if not self.data:
            return []
        return self.data["status"].get("pool", []) or []

    @property
    def native_entities(self) -> list[dict[str, Any]]:
        if not self.data:
            return []
        return self.data.get("native", []) or []
