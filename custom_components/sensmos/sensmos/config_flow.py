"""Sensmos — config flow + options flow (mapowania, subskrypcje)."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SensmosApi, SensmosApiError, SensmosAuthError
from .const import CONF_HOST, CONF_PIN, DOMAIN, OPT_FEEDS, OPT_WEBHOOK
from .units import device_classes_for_unit

_SLUG = re.compile(r"[^a-z0-9_]+")


def _slugify(name: str) -> str:
    return _SLUG.sub("_", name.strip().lower()).strip("_")[:28]


class SensmosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Dodanie noda: host + PIN."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().replace("http://", "").rstrip("/")
            pin = user_input[CONF_PIN].strip()
            api = SensmosApi(async_get_clientsession(self.hass), host, pin)
            try:
                cfg = await api.config()
                device_id = cfg.get("device_id", "")
                if not device_id:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()
                    info = {}
                    try:
                        info = await api.info()
                    except SensmosApiError:
                        pass
                    title = info.get("city") or f"Node {device_id[:8]}"
                    return self.async_create_entry(
                        title=f"Sensmos {title}",
                        data={CONF_HOST: host, CONF_PIN: pin},
                        options={OPT_FEEDS: [], OPT_WEBHOOK: True},
                    )
            except SensmosAuthError:
                errors["base"] = "invalid_pin"
            except SensmosApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): selector.TextSelector(),
                    vol.Required(CONF_PIN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> SensmosOptionsFlow:
        return SensmosOptionsFlow(entry)


class SensmosOptionsFlow(OptionsFlow):
    """Menu: karmienie pub/own, usuwanie, subskrypcja, ustawienia."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._pending_pub: dict[str, Any] = {}
        self._pending_sub: dict[str, Any] = {}

    # ── helpers ───────────────────────────────────────────────

    def _api(self) -> SensmosApi:
        return SensmosApi(
            async_get_clientsession(self.hass),
            self._entry.data[CONF_HOST],
            self._entry.data[CONF_PIN],
        )

    def _feeds(self) -> list[dict[str, Any]]:
        return list(self._entry.options.get(OPT_FEEDS, []))

    def _save_feeds(self, feeds: list[dict[str, Any]]) -> Any:
        return self.async_create_entry(
            data={**self._entry.options, OPT_FEEDS: feeds}
        )

    # ── menu ──────────────────────────────────────────────────

    async def async_step_init(self, user_input=None) -> Any:
        return self.async_show_menu(
            step_id="init",
            menu_options=["feed_pub", "feed_own", "feed_remove", "subscribe", "settings"],
        )

    # ── karmienie: encja natywna (pub.*) ──────────────────────

    async def async_step_feed_pub(self, user_input=None) -> Any:
        api = self._api()
        try:
            native = (await api.data_native()).get("entities", [])
        except SensmosApiError:
            return self.async_abort(reason="cannot_connect")

        mapped = {f["node_entity"] for f in self._feeds()}
        options = []
        for ent in native:
            pub_id = ent.get("pub_id") or f"pub.{ent['entity_id']}"
            if pub_id in mapped:
                continue
            unit = ent.get("unit") or ""
            label = f"{pub_id}  [{unit}]" if unit else pub_id
            options.append(selector.SelectOptionDict(value=f"{pub_id}|{unit}", label=label))

        if not options:
            return self.async_abort(reason="no_native_left")

        if user_input is not None:
            pub_id, _, unit = user_input["node_entity"].partition("|")
            self._pending_pub = {"node_entity": pub_id, "unit": unit}
            return await self.async_step_feed_pub_entity()

        return self.async_show_form(
            step_id="feed_pub",
            data_schema=vol.Schema(
                {
                    vol.Required("node_entity"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_feed_pub_entity(self, user_input=None) -> Any:
        unit = self._pending_pub.get("unit", "")
        if user_input is not None:
            feeds = self._feeds()
            feeds.append(
                {
                    "node_entity": self._pending_pub["node_entity"],
                    "ha_entity": user_input["ha_entity"],
                    "unit": unit,
                }
            )
            return self._save_feeds(feeds)

        dev_classes = device_classes_for_unit(unit)
        ent_filter = (
            selector.EntityFilterSelectorConfig(domain="sensor", device_class=dev_classes)
            if dev_classes
            else selector.EntityFilterSelectorConfig(domain="sensor")
        )
        return self.async_show_form(
            step_id="feed_pub_entity",
            data_schema=vol.Schema(
                {
                    vol.Required("ha_entity"): selector.EntitySelector(
                        selector.EntitySelectorConfig(filter=ent_filter)
                    )
                }
            ),
            description_placeholders={
                "node_entity": self._pending_pub["node_entity"],
                "unit": unit or "—",
            },
        )

    # ── karmienie: własna encja (own.*) ───────────────────────

    async def async_step_feed_own(self, user_input=None) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = _slugify(user_input["name"])
            if not name:
                errors["name"] = "invalid_name"
            else:
                node_entity = f"own.{name}"
                feeds = self._feeds()
                if any(f["node_entity"] == node_entity for f in feeds):
                    errors["name"] = "already_mapped"
                else:
                    feeds.append(
                        {
                            "node_entity": node_entity,
                            "ha_entity": user_input["ha_entity"],
                            "unit": "",  # jednostka przejmowana z encji HA
                        }
                    )
                    return self._save_feeds(feeds)

        return self.async_show_form(
            step_id="feed_own",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.TextSelector(),
                    vol.Required("ha_entity"): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            filter=selector.EntityFilterSelectorConfig(domain="sensor")
                        )
                    ),
                }
            ),
            errors=errors,
        )

    # ── usuwanie mapowań ──────────────────────────────────────

    async def async_step_feed_remove(self, user_input=None) -> Any:
        feeds = self._feeds()
        if not feeds:
            return self.async_abort(reason="no_feeds")

        if user_input is not None:
            keep = [
                f for f in feeds if f["node_entity"] not in user_input["remove"]
            ]
            return self._save_feeds(keep)

        options = [
            selector.SelectOptionDict(
                value=f["node_entity"],
                label=f"{f['node_entity']}  ←  {f['ha_entity']}",
            )
            for f in feeds
        ]
        return self.async_show_form(
            step_id="feed_remove",
            data_schema=vol.Schema(
                {
                    vol.Required("remove"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # ── subskrypcja innego noda ───────────────────────────────

    async def async_step_subscribe(self, user_input=None) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            esp_id = user_input["esp_id"].strip()
            prefix = _slugify(user_input.get("prefix") or "sub") or "sub"
            days = int(user_input.get("days", 7))
            api = self._api()
            try:
                avail = await api.remote_available(esp_id)
            except SensmosApiError:
                errors["base"] = "target_unavailable"
            else:
                pub = avail.get("pub", []) or []
                listing = "\n".join(
                    f"• {e.get('entity_id', '?')}"
                    + (f" [{e['unit']}]" if e.get("unit") else "")
                    for e in pub[:20]
                ) or "—"
                self._pending_sub = {
                    "esp_id": esp_id,
                    "prefix": prefix,
                    "days": days,
                    "listing": listing,
                    "count": len(pub),
                }
                return await self.async_step_subscribe_confirm()

        return self.async_show_form(
            step_id="subscribe",
            data_schema=vol.Schema(
                {
                    vol.Required("esp_id"): selector.TextSelector(),
                    vol.Required("prefix", default="sub"): selector.TextSelector(),
                    vol.Required("days", default=7): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, max=30, step=1)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_subscribe_confirm(self, user_input=None) -> Any:
        p = self._pending_sub
        if user_input is not None:
            api = self._api()
            try:
                await api.subscribe(p["esp_id"], p["days"], p["prefix"])
            except SensmosApiError as err:
                if "insufficient" in str(err):
                    return self.async_abort(reason="insufficient_balance")
                return self.async_abort(reason="subscribe_failed")
            return self.async_abort(reason="subscribe_ok")

        return self.async_show_form(
            step_id="subscribe_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "esp_id": p["esp_id"][:16] + "…",
                "prefix": p["prefix"],
                "days": str(p["days"]),
                "count": str(p["count"]),
                "listing": p["listing"],
            },
        )

    # ── ustawienia ────────────────────────────────────────────

    async def async_step_settings(self, user_input=None) -> Any:
        if user_input is not None:
            return self.async_create_entry(
                data={**self._entry.options, OPT_WEBHOOK: user_input[OPT_WEBHOOK]}
            )
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPT_WEBHOOK,
                        default=self._entry.options.get(OPT_WEBHOOK, True),
                    ): selector.BooleanSelector()
                }
            ),
        )
