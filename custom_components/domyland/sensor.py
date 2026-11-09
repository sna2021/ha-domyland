"""Probe-сенсоры Domyland: сырые ответы ключевых эндпоинтов в атрибутах.

Разведка перед тем, как проектировать полноценные платформы: не в каждом ЖК
есть все сервисы платформы (white-label), поэтому сначала смотрим, что
реально отвечает customer-api этого дома.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DomylandError
from .const import DOMAIN
from .coordinator import DomylandConfigEntry, DomylandCoordinator
from .entity import DomylandBuildingEntity

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=30)

# Эндпоинты разведки (только GET): счётчики, квитанции, пропуска,
# уведомления (звонки/заявки), умный дом квартиры.
PROBE_ENDPOINTS: tuple[str, ...] = (
    "/meteringdata/dashboard",
    "/meteringdata/form",
    "/meteringdata/history",
    "/payments",
    "/main-payment-widget",
    "/v2/pass/init",
    "/notifications",
    "/smarthome/place/devices",
    "/smarthome/place/index",
    "/currentplace/info",
)

# State machine и recorder не любят гигантские состояния: режем каждый ответ.
_MAX_ATTR_CHARS = 4000


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomylandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать probe-сенсор на каждый дом."""
    coordinator = entry.runtime_data
    async_add_entities(
        (
            DomylandProbeSensor(coordinator, building_id)
            for building_id in coordinator.data.buildings
        ),
        True,  # update_before_add: заполнить атрибуты сразу при старте
    )


class DomylandProbeSensor(DomylandBuildingEntity, SensorEntity):
    """Диагностический сенсор: дёргает API и складывает ответы в атрибуты.

    Ошибки отдельных эндпоинтов не роняют обновление — фиксируем их как есть,
    чтобы видеть отсутствующие в этом ЖК сервисы.
    """

    _attr_name = "API probe"

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._attr_unique_id = f"{DOMAIN}_probe_{building_id}"

    async def async_update(self) -> None:
        building = self._building
        if building is None:
            return
        client = self.coordinator.client
        results: dict[str, Any] = {}
        for path in PROBE_ENDPOINTS:
            try:
                data = await client.probe_get(
                    path,
                    place_id=building.place_id,
                    building_id=building.building_id,
                )
            except DomylandError as err:
                results[path] = {"status": "error", "error": str(err)[:300]}
                continue
            blob = json.dumps(data, ensure_ascii=False, default=str)
            if len(blob) > _MAX_ATTR_CHARS:
                blob = blob[:_MAX_ATTR_CHARS] + "…(truncated)"
            results[path] = {"status": "ok", "data": blob}
        errors = sum(1 for item in results.values() if item["status"] == "error")
        self._attr_native_value = (
            f"ok ({len(results) - errors}/{len(results)})"
            if errors
            else "ok"
        )
        self._attr_extra_state_attributes = results
        _LOGGER.debug(
            "Probe дома %s: %s ошибок из %s эндпоинтов",
            building.building_id,
            errors,
            len(results),
        )
