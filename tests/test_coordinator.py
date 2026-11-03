"""Inventory recovery must prove current access instead of replaying old data."""

from copy import deepcopy

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.domyland.api import DomylandAuthError, DomylandError
from custom_components.domyland.camera import DomylandCamera, DomylandDoorCamera
from custom_components.domyland.const import DOMAIN
from custom_components.domyland.lock import DomylandDoorLock


async def test_empty_discovery_recovers_only_freshly_verified_sources(
    make_coordinator, refresh, client, door, camera, mjpeg_frame
):
    client.get_access_points.return_value = [door]
    client.get_cameras.return_value = [camera]
    coordinator = await make_coordinator()
    initial = await refresh(coordinator)
    assert set(initial[11].doors) == {21}
    assert set(initial[11].cameras) == {31}
    mjpeg_frame.assert_not_awaited()

    client.get_access_points.return_value = []
    client.get_cameras.return_value = []
    client.get_access_detail.return_value = {
        **door,
        "title": "Fresh detail title",
        "video": "https://video.ujin.tech/synthetic/new-door-stream",
    }
    client.get_access_detail.reset_mock()
    recovered = await refresh(coordinator)

    assert recovered[11].doors[21]["title"] == "Fresh detail title"
    assert recovered[11].door_cameras[21]["video"].endswith("new-door-stream")
    assert recovered[11].cameras[31]["streamURL"] == camera["streamURL"]
    client.get_access_detail.assert_awaited_once_with(21, 101, 11)
    assert mjpeg_frame.await_count == 1
    assert mjpeg_frame.await_args.args[-1] == camera["streamURL"]


async def test_inventory_round_trip_survives_new_coordinator_without_door_video_or_tokens(
    make_coordinator, refresh, inventory_store, client, door, camera, mjpeg_frame
):
    client.get_access_points.return_value = [{**door, "token": "synthetic-secret"}]
    client.get_cameras.return_value = [
        {**camera, "authorization": "synthetic-secret"}
    ]
    first = await make_coordinator()
    await refresh(first)

    snapshot = await inventory_store().async_load()
    assert snapshot == {
        "buildings": {
            "11": {
                "doors": {"21": {"id": 21, "title": door["title"]}},
                "cameras": {"31": camera},
            }
        }
    }

    client.get_access_points.return_value = []
    client.get_cameras.return_value = []
    client.get_access_detail.reset_mock()
    second = await make_coordinator()
    assert second is not first
    recovered = await refresh(second)
    assert set(recovered[11].doors) == {21}
    assert set(recovered[11].cameras) == {31}
    client.get_access_detail.assert_awaited_once_with(21, 101, 11)
    assert mjpeg_frame.await_args.args[-1] == camera["streamURL"]


async def test_known_detail_failure_does_not_resurrect_old_healthy_data(
    make_coordinator, refresh, inventory_store, client, door
):
    client.get_access_points.return_value = [door]
    coordinator = await make_coordinator()
    await refresh(coordinator)
    lock = DomylandDoorLock(coordinator, 11, 21)
    camera = DomylandDoorCamera(coordinator, 11, 21)
    assert lock.available
    assert camera.available

    client.get_access_points.return_value = []
    client.get_access_detail.side_effect = DomylandError("synthetic offline detail")
    current = await refresh(coordinator)
    assert current[11].doors == {}
    assert current[11].door_cameras == {}
    assert not lock.available
    assert not camera.available
    assert "21" in (await inventory_store().async_load())["buildings"]["11"]["doors"]

    # A temporary failure must not erase the ID needed to recover next time.
    client.get_access_detail.side_effect = None
    client.get_access_detail.return_value = {**door, "title": "Back online"}
    current = await refresh(coordinator)
    assert current[11].doors[21]["title"] == "Back online"
    assert lock.available
    assert not camera.available  # No fresh video was returned.


async def test_fresh_detail_unavailable_does_not_present_old_camera_as_healthy(
    make_coordinator, refresh, client, door
):
    client.get_access_points.return_value = [door]
    coordinator = await make_coordinator()
    await refresh(coordinator)
    lock = DomylandDoorLock(coordinator, 11, 21)
    camera = DomylandDoorCamera(coordinator, 11, 21)
    assert lock.available and camera.available

    client.get_access_points.return_value = []
    client.get_access_detail.return_value = {**door, "isAvailable": False}
    await refresh(coordinator)
    assert not lock.available
    assert not camera.available


async def test_fresh_list_survives_detail_error_without_reusing_video(
    make_coordinator, refresh, client, door
):
    client.get_access_points.return_value = [door]
    coordinator = await make_coordinator()
    await refresh(coordinator)
    client.get_access_points.return_value = [{**door, "title": "Fresh list title"}]
    client.get_access_detail.side_effect = DomylandError("synthetic detail failure")
    current = await refresh(coordinator)
    assert current[11].doors[21]["title"] == "Fresh list title"
    assert current[11].door_cameras == {}
    assert DomylandDoorLock(coordinator, 11, 21).available
    assert not DomylandDoorCamera(coordinator, 11, 21).available


@pytest.mark.parametrize("failed_list", ["get_access_points", "get_cameras"])
async def test_list_failures_do_not_suppress_independent_discovery(
    failed_list, make_coordinator, refresh, client, door, camera, mjpeg_frame
):
    client.get_access_points.return_value = [door]
    client.get_cameras.return_value = [camera]
    coordinator = await make_coordinator()
    await refresh(coordinator)
    getattr(client, failed_list).side_effect = DomylandError("synthetic list outage")
    client.get_access_detail.reset_mock()
    current = await refresh(coordinator)
    assert set(current[11].doors) == {21}
    assert set(current[11].cameras) == {31}
    assert set(current[11].door_cameras) == {21}
    client.get_access_detail.assert_awaited_once_with(21, 101, 11)
    assert mjpeg_frame.await_count == (1 if failed_list == "get_cameras" else 0)


@pytest.mark.parametrize(
    "method", ["get_places", "get_access_points", "get_cameras", "get_access_detail"]
)
@pytest.mark.parametrize("known_only", [False, True], ids=["listed", "recovered"])
async def test_auth_failure_always_requires_reauthentication(
    method, known_only, make_coordinator, refresh, client, door
):
    client.get_access_points.return_value = [door]
    coordinator = await make_coordinator()
    await refresh(coordinator)
    if known_only:
        client.get_access_points.return_value = []
    getattr(client, method).side_effect = DomylandAuthError("synthetic expired login")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_places_network_failure_is_not_successful_empty_inventory(
    make_coordinator, client
):
    coordinator = await make_coordinator()
    client.get_places.side_effect = DomylandError("synthetic places outage")
    with pytest.raises(UpdateFailed, match="synthetic places outage"):
        await coordinator._async_update_data()


async def test_removed_current_place_prevents_all_inventory_recovery(
    make_coordinator, refresh, inventory_store, client, door, camera, mjpeg_frame
):
    client.get_access_points.return_value = [door]
    client.get_cameras.return_value = [camera]
    coordinator = await make_coordinator()
    await refresh(coordinator)
    snapshot = deepcopy(await inventory_store().async_load())
    client.get_places.return_value = []
    for method in (client.get_access_points, client.get_cameras, client.get_access_detail):
        method.reset_mock()

    # A new instance also must gate persisted data by current account places.
    coordinator = await make_coordinator()
    current = await refresh(coordinator)
    assert current == {}
    client.get_access_points.assert_not_awaited()
    client.get_cameras.assert_not_awaited()
    client.get_access_detail.assert_not_awaited()
    mjpeg_frame.assert_not_awaited()
    assert await inventory_store().async_load() == snapshot
    assert not DomylandDoorLock(coordinator, 11, 21).available
    assert not DomylandCamera(coordinator, 11, 31).available


async def test_disabled_cameras_still_recovers_known_door_on_reload(
    make_coordinator, refresh, client, door, mjpeg_frame
):
    client.get_access_points.return_value = [door]
    coordinator = await make_coordinator(cameras=False)
    await refresh(coordinator)
    client.get_access_detail.assert_not_awaited()
    client.get_access_points.return_value = []
    coordinator = await make_coordinator(cameras=False)
    current = await refresh(coordinator)
    assert set(current[11].doors) == {21}
    assert current[11].cameras == {}
    assert current[11].door_cameras == {}
    assert DomylandDoorLock(coordinator, 11, 21).available
    client.get_access_detail.assert_awaited_once_with(21, 101, 11)
    client.get_cameras.assert_not_awaited()
    mjpeg_frame.assert_not_awaited()


@pytest.mark.parametrize(
    ("entity_domain", "unique_id"),
    [("lock", "domyland_door_21"), ("camera", "domyland_access_camera_21")],
)
async def test_registry_bootstraps_pre_inventory_installation(
    entity_domain, unique_id, hass, entry, make_coordinator, refresh, client,
    inventory_store
):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "building_11")},
        name="Synthetic registered building",
    )
    er.async_get(hass).async_get_or_create(
        entity_domain,
        DOMAIN,
        unique_id,
        config_entry=entry,
        device_id=device.id,
        original_name="Synthetic existing entrance",
    )
    assert await inventory_store().async_load() is None
    coordinator = await make_coordinator()
    current = await refresh(coordinator)
    assert set(current[11].doors) == {21}
    client.get_access_detail.assert_awaited_once_with(21, 101, 11)
    assert (await inventory_store().async_load())["buildings"]["11"]["doors"]["21"]["id"] == 21


@pytest.mark.parametrize(
    "invalid_owner", ["entry", "platform", "device_domain", "device_missing", "unique_id"]
)
async def test_registry_bootstrap_ignores_unowned_or_unidentifiable_entities(
    invalid_owner, hass, entry, make_coordinator, refresh, client
):
    owner = entry
    if invalid_owner == "entry":
        owner = MockConfigEntry(domain=DOMAIN, unique_id="synthetic-other-customer")
        owner.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={
            ("unrelated" if invalid_owner == "device_domain" else DOMAIN, "building_11")
        },
    )
    er.async_get(hass).async_get_or_create(
        "lock",
        "unrelated" if invalid_owner == "platform" else DOMAIN,
        "domyland_door_invalid" if invalid_owner == "unique_id" else "domyland_door_22",
        config_entry=owner,
        device_id=None if invalid_owner == "device_missing" else device.id,
    )
    coordinator = await make_coordinator()
    current = await refresh(coordinator)
    assert current[11].doors == {}
    client.get_access_detail.assert_not_awaited()


async def test_registry_camera_without_saved_url_stays_unavailable(
    hass, entry, make_coordinator, refresh, client, mjpeg_frame
):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "building_11")},
    )
    er.async_get(hass).async_get_or_create(
        "camera", DOMAIN, "domyland_camera_31", config_entry=entry, device_id=device.id
    )
    coordinator = await make_coordinator()
    current = await refresh(coordinator)
    assert current[11].cameras == {}
    assert not DomylandCamera(coordinator, 11, 31).available
    client.get_access_detail.assert_not_awaited()
    mjpeg_frame.assert_not_awaited()


async def test_one_auth_failure_among_parallel_door_details_is_not_swallowed(
    make_coordinator, client, door
):
    client.get_access_points.return_value = [door, {**door, "id": 22}]

    async def detail(door_id, place_id, building_id):
        if door_id == 22:
            raise DomylandAuthError("synthetic second door auth failure")
        return {**door, "video": "https://video.ujin.tech/synthetic/door-21"}

    client.get_access_detail.side_effect = detail
    coordinator = await make_coordinator()
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert {call.args[0] for call in client.get_access_detail.await_args_list} == {21, 22}
