"""Real Home Assistant state, registries and disk storage; synthetic API data."""

from copy import deepcopy
from unittest.mock import AsyncMock, create_autospec

import pytest
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.domyland.api import DomylandApiClient
from custom_components.domyland.const import DOMAIN
from custom_components.domyland.coordinator import DomylandCoordinator


@pytest.fixture
def hass_config_dir(tmp_path):
    """Keep all HA registry and inventory files within this test's directory."""
    return str(tmp_path)


@pytest.fixture
def hass_storage():
    """Override the plugin's Store monkeypatch: exercise actual JSON persistence."""
    return {}


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow the local integration to be loaded by HA's real flow manager."""


@pytest.fixture
def entry(hass):
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic home",
        unique_id="synthetic-customer",
        data={"yandex_token": "synthetic-token", "jwt": "synthetic-jwt"},
        options={"enable_cameras": True},
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def place():
    return {
        "id": 101,
        "buildingId": 11,
        "buildingTitle": "Synthetic building",
        "placeTypeId": 1,
        "address": "Synthetic address",
    }


@pytest.fixture
def door():
    return {"id": 21, "title": "Synthetic entrance", "isAvailable": True}


@pytest.fixture
def camera():
    return {
        "id": 31,
        "title": "Synthetic courtyard",
        "streamURL": "https://video.ujin.tech/synthetic/camera-31",
        "image": "https://video.ujin.tech/synthetic/image-31.jpg",
    }


@pytest.fixture
def client(place, door):
    """Mock the remote API client only, not coordinator or HA infrastructure."""
    remote = create_autospec(DomylandApiClient, instance=True)
    remote.get_places.return_value = [deepcopy(place)]
    remote.get_access_points.return_value = []
    remote.get_access_detail.return_value = {
        **deepcopy(door),
        "video": "https://video.ujin.tech/synthetic/door-21-fresh",
        "videoType": "mjpeg",
    }
    remote.get_cameras.return_value = []
    remote.get_place_management.return_value = {"devices": []}
    remote.get_payment_widget.return_value = {}
    remote.get_orders_dispatcher.return_value = []
    remote.get_guest_passes.return_value = []
    return remote


@pytest.fixture
def mjpeg_frame(monkeypatch):
    """Replace only the remote stream-reading boundary."""
    remote = AsyncMock(return_value=b"\xff\xd8synthetic-frame\xff\xd9")
    monkeypatch.setattr(
        "custom_components.domyland.coordinator.async_get_mjpeg_frame", remote
    )
    return remote


@pytest.fixture
def make_coordinator(hass, entry, client, mjpeg_frame):
    async def create(*, cameras=True):
        coordinator = DomylandCoordinator(hass, entry, client, cameras)
        await coordinator.async_initialize()
        entry.runtime_data = coordinator
        return coordinator

    return create


@pytest.fixture
def refresh():
    async def update(coordinator):
        # Direct updates avoid HA setup/reauth side effects while retaining the
        # real coordinator data and availability semantics for entity checks.
        data = await coordinator._async_update_data()
        coordinator.async_set_updated_data(data)
        return data.buildings

    return update


@pytest.fixture
def inventory_store(hass, entry):
    def create():
        # A new Store instance must read the serialized snapshot, not a cached
        # object belonging to the coordinator under test.
        return Store(hass, 1, f"domyland.{entry.entry_id}.inventory")

    return create
