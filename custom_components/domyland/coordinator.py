"""DataUpdateCoordinator интеграции Domyland."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DomylandApiClient,
    DomylandAuthError,
    DomylandError,
    async_get_mjpeg_frame,
)
from .const import (
    DOMAIN,
    PLACES_FAILURE_TOLERANCE,
    STORAGE_KEY,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type DomylandConfigEntry = ConfigEntry[DomylandCoordinator]


@dataclass
class BuildingData:
    """Один физический дом (buildingId) со своими дверями и камерами."""

    building_id: int
    building_title: str
    # place_id/тип помещения, чьими заголовками мы ходим за дверями/камерами.
    place_id: int
    place_address: str
    doors: dict[int, dict[str, Any]] = field(default_factory=dict)
    cameras: dict[int, dict[str, Any]] = field(default_factory=dict)
    # Встроенные камеры домофонов (door_id → детали с полем `video`).
    door_cameras: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass
class DomylandData:
    """Снимок состояния, который отдаёт координатор в платформы."""

    buildings: dict[int, BuildingData] = field(default_factory=dict)


class DomylandCoordinator(DataUpdateCoordinator[DomylandData]):
    """Тянет места → двери/камеры по каждому уникальному дому.

    Двери и камеры физически привязаны к дому (buildingId), а не к юниту.
    Несколько мест в одном доме (напр. квартира + машиноместо) дали бы дубли,
    поэтому группируем по buildingId и ходим за содержимым один раз на дом.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DomylandConfigEntry,
        client: DomylandApiClient,
        enable_cameras: bool,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.enable_cameras = enable_cameras
        self._inventory: dict[str, Any] = {}
        self._inventory_dirty = False
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY.format(entry_id=entry.entry_id),
            private=True,
        )
        self._entry_id = entry.entry_id
        self._requests = asyncio.Semaphore(5)
        self._places_failures = 0

    async def async_initialize(self) -> None:
        """Загрузить источники и восстановить ID дверей прежних установок."""
        stored = await self._store.async_load()
        self._inventory = (stored or {}).get("buildings", {})
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        for entity in er.async_entries_for_config_entry(entities, self._entry_id):
            if entity.platform != DOMAIN or entity.device_id is None:
                continue
            device = devices.async_get(entity.device_id)
            if device is None:
                continue
            building_id = next(
                (
                    identifier.removeprefix("building_")
                    for domain, identifier in device.identifiers
                    if domain == DOMAIN and identifier.startswith("building_")
                ),
                "",
            )
            if not building_id.isdecimal():
                continue
            for prefix in (f"{DOMAIN}_door_", f"{DOMAIN}_access_camera_"):
                if not entity.unique_id.startswith(prefix):
                    continue
                door_id = entity.unique_id.removeprefix(prefix)
                if door_id.isdecimal():
                    doors = self._known(int(building_id))["doors"]
                    if door_id not in doors:
                        doors[door_id] = {
                            "id": int(door_id),
                            "title": entity.original_name or entity.name or door_id,
                        }
                        self._inventory_dirty = True
                break
        await self._async_save_inventory()

    def _known(self, building_id: int) -> dict[str, Any]:
        return self._inventory.setdefault(
            str(building_id), {"doors": {}, "cameras": {}}
        )

    def _remember(self, building_id: int, kind: str, source: dict[str, Any]) -> None:
        """Храним идентичность двери, но не её устаревающую доступность/video."""
        fields = (
            ("id", "title", "streamURL", "image")
            if kind == "cameras"
            else ("id", "title")
        )
        saved = {key: source[key] for key in fields if key in source}
        known = self._known(building_id)[kind]
        key = str(source["id"])
        if known.get(key) != saved:
            known[key] = saved
            self._inventory_dirty = True

    async def _async_save_inventory(self) -> None:
        if self._inventory_dirty:
            await self._store.async_save({"buildings": self._inventory})
            self._inventory_dirty = False

    async def async_restore_cameras(
        self, building_id: int, cameras: list[dict[str, Any]]
    ) -> None:
        """Импорт личного архива; доступность потоков проверит обновление."""
        if (
            type(building_id) is not int
            or building_id not in self.data.buildings
            or not isinstance(cameras, list)
            or not cameras
        ):
            raise ValueError("Архив должен относиться к текущему дому аккаунта")
        ids: set[int] = set()
        for camera in cameras:
            if not isinstance(camera, dict):
                raise TypeError("Ожидался объект камеры")
            camera_id = camera.get("id")
            title = camera.get("title")
            url = camera.get("streamURL")
            if (
                type(camera_id) is not int
                or camera_id <= 0
                or camera_id in ids
                or not isinstance(title, str)
                or not title.strip()
                or not isinstance(url, str)
                or ("image" in camera and not isinstance(camera["image"], str))
            ):
                raise ValueError("Неверные данные камеры")
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if (
                parsed.scheme != "https"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
                or not any(
                    host == domain or host.endswith(f".{domain}")
                    for domain in ("ujin.tech", "mysmartflat.ru")
                )
            ):
                raise ValueError("Ожидалась HTTPS-ссылка потока UJIN")
            ids.add(camera_id)
        # Валидация всего архива завершается до первого изменения хранилища.
        for camera in cameras:
            self._remember(building_id, "cameras", camera)
        await self._async_save_inventory()

    async def _async_update_data(self) -> DomylandData:
        try:
            places = await self.client.get_places()
        except DomylandAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except DomylandError as err:
            if self.data is None or self._places_failures >= PLACES_FAILURE_TOLERANCE:
                raise UpdateFailed(str(err)) from err
            self._places_failures += 1
            _LOGGER.warning(
                "Domyland places недоступны (%s), оставляем данные прошлого опроса "
                "(сбой %s/%s подряд)",
                err,
                self._places_failures,
                PLACES_FAILURE_TOLERANCE,
            )
            return self.data
        self._places_failures = 0

        buildings: dict[int, BuildingData] = {}
        for place in places:
            building_id = place.get("buildingId")
            if building_id is None:
                continue
            existing = buildings.get(building_id)
            is_flat = place.get("placeTypeId") == 1
            if existing is None or (is_flat and existing.place_id != place["id"]):
                buildings[building_id] = BuildingData(
                    building_id=building_id,
                    building_title=place.get("buildingTitle") or str(building_id),
                    place_id=place["id"],
                    place_address=place.get("address") or "",
                )

        # Из архива нельзя восстановить доступ к дому, которого уже нет в places.
        try:
            for building in buildings.values():
                await self._async_update_doors(building)
                if self.enable_cameras:
                    await self._async_update_cameras(building)
        except DomylandAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        await self._async_save_inventory()
        return DomylandData(buildings=buildings)

    async def _async_update_doors(self, building: BuildingData) -> None:
        known = self._known(building.building_id)["doors"]
        try:
            doors = await self.client.get_access_points(
                building.place_id, building.building_id
            )
        except DomylandAuthError:
            raise
        except DomylandError as err:
            _LOGGER.warning(
                "Не удалось получить список дверей дома %s: %s",
                building.building_title,
                err,
            )
            doors = []
        building.doors = {door["id"]: door for door in doors}
        for door in doors:
            self._remember(building.building_id, "doors", door)
        missing = set(map(int, known)) - building.doors.keys()
        if missing:
            _LOGGER.warning(
                "Domyland не вернул %s известных дверей дома %s; проверяем их индивидуально",
                len(missing), building.building_title,
            )
        to_check = set(building.doors) | missing if self.enable_cameras else missing

        async def _one(door_id: int) -> None:
            async with self._requests:
                try:
                    detail = await self.client.get_access_detail(
                        door_id, building.place_id, building.building_id
                    )
                except DomylandAuthError:
                    raise
                except DomylandError as err:
                    _LOGGER.warning("Не удалось проверить дверь %s: %s", door_id, err)
                    return
            # Успешный индивидуальный ответ — свежие данные, а не старое состояние.
            source = {**building.doors.get(door_id, {}), **detail, "id": door_id}
            building.doors[door_id] = source
            self._remember(building.building_id, "doors", source)
            if self.enable_cameras and detail.get("video"):
                building.door_cameras[door_id] = detail

        results = await asyncio.gather(
            *(_one(door_id) for door_id in to_check), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _async_update_cameras(self, building: BuildingData) -> None:
        known = self._known(building.building_id)["cameras"]
        try:
            cameras = await self.client.get_cameras(
                building.place_id, building.building_id
            )
        except DomylandAuthError:
            raise
        except DomylandError as err:
            _LOGGER.warning(
                "Не удалось получить список камер дома %s: %s",
                building.building_title,
                err,
            )
            cameras = []
        building.cameras = {camera["id"]: camera for camera in cameras}
        for camera in cameras:
            self._remember(building.building_id, "cameras", camera)
        missing = set(map(int, known)) - building.cameras.keys()
        if missing:
            _LOGGER.warning(
                "Domyland не вернул %s известных камер дома %s; проверяем сохранённые потоки",
                len(missing), building.building_title,
            )
        session = async_get_clientsession(self.hass)

        async def _one(camera_id: int) -> None:
            source = known[str(camera_id)]
            url = source.get("streamURL")
            if not url:
                return
            async with self._requests:
                frame = await async_get_mjpeg_frame(session, url)
            if frame is not None:
                building.cameras[camera_id] = source

        await asyncio.gather(*(_one(camera_id) for camera_id in missing))
