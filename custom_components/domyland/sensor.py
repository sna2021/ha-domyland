"""Сенсоры Domyland: счётчики, счёт ЖКХ, заявки УК, пропуска, уведомления."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import BuildingData, DomylandConfigEntry, DomylandCoordinator
from .entity import DomylandBuildingEntity

_LOGGER = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# signalName из API → (единица измерения HA, device_class).
_SIGNAL_UNITS: dict[str, tuple[str, SensorDeviceClass | None]] = {
    "m3": (UnitOfVolume.CUBIC_METERS, SensorDeviceClass.WATER),
    "gcal": ("Гкал", None),
}


def _parse_number(text: str | None) -> float | None:
    """Число из строк вида «Показание 59.86 м³» или «12 135,70 ₽»."""
    if not text:
        return None
    cleaned = text.replace("\xa0", " ").replace(" ", "")
    match = _NUMBER_RE.search(cleaned)
    if not match:
        return None
    return float(match.group().replace(",", "."))


def _clean_preview(text: str | None) -> str:
    """Превью уведомления без HTML (УК шлёт разметку) и лишних пробелов."""
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return " ".join(cleaned.split())[:200]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomylandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Сенсоры счётчиков на каждое устройство + сенсор счёта ЖКХ на дом."""
    coordinator = entry.runtime_data
    known: set[tuple[str, int, int]] = set()

    @callback
    def _add_new() -> None:
        entities: list[SensorEntity] = []
        for building_id, building in coordinator.data.buildings.items():
            for device in building.smart_devices:
                key = ("meter", building_id, device["id"])
                if key in known or not device.get("isMetering"):
                    continue
                known.add(key)
                entities.append(
                    DomylandMeterSensor(coordinator, building_id, device["id"])
                )
            if building.payment_widget and ("invoice", building_id, 0) not in known:
                known.add(("invoice", building_id, 0))
                entities.append(DomylandInvoiceSensor(coordinator, building_id))
            if ("orders", building_id, 0) not in known:
                known.add(("orders", building_id, 0))
                entities.append(DomylandOrdersSensor(coordinator, building_id))
            if ("passes", building_id, 0) not in known:
                known.add(("passes", building_id, 0))
                entities.append(DomylandPassesSensor(coordinator, building_id))
            if ("notifications", building_id, 0) not in known:
                known.add(("notifications", building_id, 0))
                entities.append(
                    DomylandNotificationsSensor(coordinator, building_id)
                )
            if ("news", building_id, 0) not in known:
                known.add(("news", building_id, 0))
                entities.append(DomylandNewsSensor(coordinator, building_id))
        if entities:
            async_add_entities(entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class DomylandMeterSensor(DomylandBuildingEntity, SensorEntity):
    """Показания одного умного счётчика (Пульсар, Sanext и т.п.).

    Источник: devices из /smarthome/place/management, indicators[0].value —
    готовая строка «Показание 59.86 м³».
    """

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int, device_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_meter_{device_id}"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def _device(self) -> dict[str, Any] | None:
        building = self._building
        if building is None:
            return None
        for device in building.smart_devices:
            if device.get("id") == self._device_id:
                return device
        return None

    @property
    def available(self) -> bool:
        return super().available and self._device is not None

    @property
    def name(self) -> str | None:
        device = self._device
        return device.get("title") if device else None

    @property
    def device_class(self) -> SensorDeviceClass | None:
        device = self._device
        if device is None:
            return None
        return _SIGNAL_UNITS.get(device.get("signalName", ""), ("", None))[1]

    @property
    def native_unit_of_measurement(self) -> str | None:
        device = self._device
        if device is None:
            return None
        return _SIGNAL_UNITS.get(device.get("signalName", ""), ("", None))[0] or None

    @property
    def native_value(self) -> float | None:
        device = self._device
        if not device:
            return None
        indicators = device.get("indicators") or []
        if not indicators:
            return None
        return _parse_number(indicators[0].get("value"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device or {}
        return {
            "device_name": device.get("deviceName"),
            "signal_name": device.get("signalName"),
        }


class DomylandInvoiceSensor(DomylandBuildingEntity, SensorEntity):
    """Текущий счёт ЖКХ из /main-payment-widget (amountText, invoicesCount).

    paymentContext/paymentLink в атрибуты не кладём: это одноразовые
    платёжные токены, им не место в state machine и логах.
    """

    _attr_name = "Счёт ЖКХ"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "₽"

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._attr_unique_id = f"{DOMAIN}_invoice_{building_id}"

    @property
    def _widget(self) -> dict[str, Any]:
        building: BuildingData | None = self._building
        return building.payment_widget if building else {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._widget)

    @property
    def native_value(self) -> float | None:
        return _parse_number(self._widget.get("amountText"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "invoices_count": self._widget.get("invoicesCount"),
            "title": self._widget.get("title"),
        }


class DomylandOrdersSensor(DomylandBuildingEntity, SensorEntity):
    """Активные заявки УК из /my-orders/dispatcher (только card+active)."""

    _attr_name = "Заявки УК"

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._attr_unique_id = f"{DOMAIN}_orders_{building_id}"

    @property
    def native_value(self) -> int:
        building = self._building
        return len(building.orders) if building else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        building = self._building
        orders = building.orders if building else []
        return {
            "orders": [
                {
                    "id": order.get("id"),
                    "title": order.get("title"),
                    "status": order.get("orderStatusTitle"),
                    "created_at": order.get("createdAtFormatted"),
                    "has_status_update": order.get("hasStatusUpdate"),
                    "unread_messages": order.get("unreadCustomerMessagesCount"),
                }
                for order in orders[:10]
            ],
            "has_status_updates": any(
                order.get("hasStatusUpdate") for order in orders
            ),
        }


class DomylandPassesSensor(DomylandBuildingEntity, SensorEntity):
    """Разовые гостевые пропуска из /v2/pass (сырой список, до 10 записей)."""

    _attr_name = "Гостевые пропуска"

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._attr_unique_id = f"{DOMAIN}_passes_{building_id}"

    @property
    def native_value(self) -> int:
        building = self._building
        return len(building.guest_passes) if building else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        building = self._building
        passes = building.guest_passes if building else []
        return {"passes": passes[:10]}


class DomylandNotificationsSensor(DomylandBuildingEntity, SensorEntity):
    """Уведомления ЖКХ из /notifications: состояние — число непрочитанных.

    В атрибутах последние 20 записей (заголовок, превью без HTML до 200
    символов, дата, прочитано) — из них строится лента на дашборде.
    """

    _attr_name = "Уведомления ЖКХ"
    _feed_attr = "notifications"
    _attr_key = "notifications"

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._attr_unique_id = f"{DOMAIN}_notifications_{building_id}"

    @property
    def native_value(self) -> int:
        building = self._building
        items = getattr(building, self._feed_attr) if building else []
        return sum(1 for item in items if not item.get("isViewed"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        building = self._building
        items = getattr(building, self._feed_attr) if building else []
        return {
            self._attr_key: [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "preview": _clean_preview(item.get("preview")),
                    "date": item.get("label"),
                    "is_viewed": item.get("isViewed"),
                }
                for item in items[:20]
            ]
        }


class DomylandNewsSensor(DomylandNotificationsSensor):
    """Новости УК из /newsfeed: тот же формат, что у уведомлений."""

    _attr_name = "Новости ЖК"
    _feed_attr = "news"
    _attr_key = "news"

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._attr_unique_id = f"{DOMAIN}_news_{building_id}"
