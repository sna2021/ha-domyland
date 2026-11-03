"""Camera recovery stores only validated sources and checks cached liveness."""

from copy import deepcopy

import pytest

from custom_components.domyland.api import DomylandError
from custom_components.domyland.camera import DomylandCamera


@pytest.mark.parametrize(
    "url",
    [
        "https://ujin.tech/synthetic/camera-31",
        "https://video.ujin.tech/synthetic/camera-31",
        "https://a.b.ujin.tech/synthetic/camera-31",
        "https://mysmartflat.ru/synthetic/camera-31",
        "https://video.mysmartflat.ru/synthetic/camera-31",
    ],
)
async def test_valid_backup_is_persisted_and_recovered_after_new_coordinator(
    url, make_coordinator, refresh, inventory_store, client, camera, mjpeg_frame
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    restored = {**camera, "streamURL": url}
    await coordinator.async_restore_cameras(11, [restored])
    saved = await inventory_store().async_load()
    assert saved["buildings"]["11"]["cameras"] == {"31": restored}
    mjpeg_frame.assert_not_awaited()

    reloaded = await make_coordinator()
    recovered = await refresh(reloaded)
    assert recovered[11].cameras[31] == restored
    assert DomylandCamera(reloaded, 11, 31).available
    assert mjpeg_frame.await_args.args[-1] == url
    client.get_access_detail.assert_not_awaited()


@pytest.mark.parametrize(
    "patch",
    [
        {"id": "31"},
        {"id": True},
        {"id": 0},
        {"id": -1},
        {"title": ""},
        {"title": "   "},
        {"title": None},
        {"title": 31},
        {"streamURL": None},
        {"streamURL": "http://video.ujin.tech/synthetic/camera-31"},
        {"streamURL": "https://ujin.tech.invalid/synthetic/camera-31"},
        {"streamURL": "https://notujin.tech/synthetic/camera-31"},
        {"streamURL": "https://video.mysmartflat.ru.invalid/synthetic/camera-31"},
        {"streamURL": "https://example.invalid/synthetic/camera-31"},
        {"streamURL": "https://127.0.0.1/synthetic/camera-31"},
        {"streamURL": "https://synthetic@video.ujin.tech/synthetic/camera-31"},
        {"streamURL": "https://synthetic:password@video.ujin.tech/synthetic/camera-31"},
        {"streamURL": "not a URL"},
        {"image": 31},
    ],
    ids=[
        "string-id", "boolean-id", "zero-id", "negative-id", "empty-title",
        "blank-title", "null-title", "numeric-title", "null-url", "insecure-url",
        "domain-suffix", "domain-prefix", "second-domain-suffix", "foreign-host",
        "loopback", "username", "credentials", "malformed-url", "numeric-image",
    ],
)
async def test_invalid_camera_fields_do_not_mutate_saved_inventory(
    patch, make_coordinator, refresh, inventory_store, camera
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    before = deepcopy(await inventory_store().async_load())

    with pytest.raises(ValueError):
        await coordinator.async_restore_cameras(11, [{**camera, **patch}])
    assert await inventory_store().async_load() == before


@pytest.mark.parametrize("payload", [None, {}, "not cameras", [None], [{}]])
async def test_malformed_camera_collection_is_rejected_without_writes(
    payload, make_coordinator, refresh, inventory_store, camera
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    before = deepcopy(await inventory_store().async_load())
    with pytest.raises((ValueError, TypeError)):
        await coordinator.async_restore_cameras(11, payload)
    assert await inventory_store().async_load() == before


@pytest.mark.parametrize("building_id", [True, "11", 0, -1])
async def test_invalid_building_id_does_not_import(
    building_id, make_coordinator, refresh, inventory_store, camera
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    before = deepcopy(await inventory_store().async_load())
    with pytest.raises(ValueError):
        await coordinator.async_restore_cameras(building_id, [camera])
    assert await inventory_store().async_load() == before


@pytest.mark.parametrize("invalid_second", ["malformed", "duplicate"])
async def test_camera_batch_validation_is_atomic_in_memory_and_on_disk(
    invalid_second, make_coordinator, refresh, inventory_store, camera
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    before = deepcopy(await inventory_store().async_load())
    first = {**camera, "title": "Must not be partially written"}
    second = {**camera, "id": 0} if invalid_second == "malformed" else deepcopy(first)
    with pytest.raises(ValueError):
        await coordinator.async_restore_cameras(11, [first, second])

    assert await inventory_store().async_load() == before
    # Refresh this same instance too: a failed import cannot secretly alter its
    # in-memory inventory while leaving the serialized copy unchanged.
    current = await refresh(coordinator)
    assert current[11].cameras[31]["title"] == camera["title"]
    reloaded = await make_coordinator()
    current = await refresh(reloaded)
    assert current[11].cameras[31]["title"] == camera["title"]


async def test_persisted_building_is_not_permission_to_import_without_current_place(
    make_coordinator, refresh, inventory_store, client, camera, mjpeg_frame
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    before = deepcopy(await inventory_store().async_load())
    client.get_places.return_value = []
    coordinator = await make_coordinator()
    assert await refresh(coordinator) == {}
    with pytest.raises(ValueError):
        await coordinator.async_restore_cameras(11, [{**camera, "title": "No access"}])
    assert await inventory_store().async_load() == before
    mjpeg_frame.assert_not_awaited()


@pytest.mark.parametrize("discovery", ["empty", "error"])
async def test_cached_source_requires_current_frame_and_remains_retryable(
    discovery, make_coordinator, refresh, inventory_store, client, camera, mjpeg_frame
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    if discovery == "error":
        client.get_cameras.side_effect = DomylandError("synthetic discovery failure")
    mjpeg_frame.return_value = None
    current = await refresh(coordinator)
    assert current[11].cameras == {}
    entity = DomylandCamera(coordinator, 11, 31)
    assert not entity.available
    assert (await inventory_store().async_load())["buildings"]["11"]["cameras"]["31"] == camera
    assert mjpeg_frame.await_args.args[-1] == camera["streamURL"]

    mjpeg_frame.return_value = b"\xff\xd8synthetic-new-frame\xff\xd9"
    current = await refresh(coordinator)
    assert current[11].cameras[31] == camera
    assert entity.available
    assert mjpeg_frame.await_count == 2


async def test_fresh_discovery_replaces_cached_url_without_duplicate_health_probe(
    make_coordinator, refresh, inventory_store, client, camera, mjpeg_frame
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    fresh = {**camera, "streamURL": "https://video.ujin.tech/synthetic/fresh-camera-31"}
    client.get_cameras.return_value = [fresh]
    mjpeg_frame.return_value = None
    current = await refresh(coordinator)
    assert current[11].cameras[31] == fresh
    assert DomylandCamera(coordinator, 11, 31).available
    mjpeg_frame.assert_not_awaited()
    assert (await inventory_store().async_load())["buildings"]["11"]["cameras"]["31"] == fresh


async def test_camera_option_disabled_does_not_expose_or_probe_saved_sources(
    make_coordinator, refresh, inventory_store, client, camera, door, mjpeg_frame
):
    coordinator = await make_coordinator()
    client.get_access_points.return_value = [door]
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    client.get_access_points.return_value = []
    client.get_cameras.reset_mock()
    client.get_access_detail.reset_mock()
    coordinator = await make_coordinator(cameras=False)
    current = await refresh(coordinator)
    assert set(current[11].doors) == {21}
    assert current[11].cameras == {}
    assert current[11].door_cameras == {}
    assert not DomylandCamera(coordinator, 11, 31).available
    client.get_access_detail.assert_awaited_once_with(21, 101, 11)
    client.get_cameras.assert_not_awaited()
    mjpeg_frame.assert_not_awaited()
    assert (await inventory_store().async_load())["buildings"]["11"]["cameras"]["31"] == camera
