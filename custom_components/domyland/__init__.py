"""Интеграция Domyland — домофоны и камеры ЖК через платформу Domyland."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import DomylandApiClient, DomylandError
from .const import (
    CONF_ENABLE_CAMERAS,
    CONF_JWT,
    CONF_YANDEX_TOKEN,
    DEFAULT_ENABLE_CAMERAS,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import DomylandConfigEntry, DomylandCoordinator

PLATFORMS: list[Platform] = [Platform.LOCK, Platform.CAMERA, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Зарегистрировать websocket-команды интеграции."""
    websocket_api.async_register_command(hass, _ws_notification_detail)
    return True


@websocket_api.websocket_command(
    {
        vol.Required("type"): "domyland/notification_detail",
        vol.Required("notification_id"): int,
        vol.Optional("building_id"): int,
    }
)
@websocket_api.async_response
async def _ws_notification_detail(hass, connection, msg):
    """Полный текст уведомления по требованию (детальный вид ленты)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator = entry.runtime_data
        buildings = coordinator.data.buildings
        building = buildings.get(msg.get("building_id")) or next(
            iter(buildings.values()), None
        )
        if building is None:
            continue
        try:
            detail = await coordinator.client.get_notification_detail(
                building.place_id, building.building_id, msg["notification_id"]
            )
        except DomylandError as err:
            connection.send_error(msg["id"], "domyland_error", str(err)[:200])
            return
        connection.send_result(msg["id"], detail)
        return
    connection.send_error(msg["id"], "no_building", "Нет доступных домов Domyland")


async def async_setup_entry(hass: HomeAssistant, entry: DomylandConfigEntry) -> bool:
    """Настроить config entry."""
    session = async_get_clientsession(hass)
    client = DomylandApiClient(
        session,
        yandex_token=entry.data[CONF_YANDEX_TOKEN],
        jwt=entry.data.get(CONF_JWT),
    )
    enable_cameras = entry.options.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS)

    coordinator = DomylandCoordinator(hass, entry, client, enable_cameras)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DomylandConfigEntry) -> bool:
    """Выгрузить config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: DomylandConfigEntry) -> None:
    """Удалить личный архив источников вместе с интеграцией."""
    await Store(
        hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry.entry_id), private=True
    ).async_remove()


async def _async_update_listener(
    hass: HomeAssistant, entry: DomylandConfigEntry
) -> None:
    """Перезагрузить при изменении опций (напр. вкл/выкл камеры)."""
    await hass.config_entries.async_reload(entry.entry_id)
