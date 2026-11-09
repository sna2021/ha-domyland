"""Ручные показания счётчиков: приватное хранилище + WS list/set.

Значения вводит пользователь в карточке дашборда; они НЕ создают сущностей
и не смешиваются с данными УК — хранятся отдельным словарём в .storage.
"""

from __future__ import annotations

import logging
import time

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "domyland.manual_readings"


def _store(hass: HomeAssistant) -> Store:
    return Store(hass, STORAGE_VERSION, STORAGE_KEY, private=True)


async def _load(hass: HomeAssistant) -> dict:
    return (await _store(hass).async_load()) or {}


async def async_save_reading(
    hass: HomeAssistant, key: str, value: float
) -> dict:
    """Сохранить ручное показание и вернуть весь словарь."""
    readings = await _load(hass)
    readings[key] = {"value": value, "updated_at": int(time.time())}
    await _store(hass).async_save(readings)
    return readings


@websocket_api.websocket_command({"type": "domyland/manual_readings/list"})
@websocket_api.async_response
async def ws_list(hass, connection, msg):
    """Все ручные показания: {ключ счётчика: {value, updated_at}}."""
    connection.send_result(msg["id"], await _load(hass))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "domyland/manual_readings/set",
        vol.Required("key"): vol.All(str, vol.Length(min=1, max=64)),
        vol.Required("value"): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1_000_000)
        ),
    }
)
@websocket_api.async_response
async def ws_set(hass, connection, msg):
    """Сохранить ручное показание по ключу счётчика."""
    connection.send_result(
        msg["id"],
        await async_save_reading(hass, msg["key"], msg["value"]),
    )


def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_set)
