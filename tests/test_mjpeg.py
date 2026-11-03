"""The shared health probe needs JPEG bytes, not merely an HTTP 200 response."""

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.domyland.api import async_get_mjpeg_frame
from custom_components.domyland.coordinator import DomylandCoordinator


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"\xff\xd8synthetic-jpeg\xff\xd9", b"\xff\xd8synthetic-jpeg\xff\xd9"),
        (
            b"--boundary\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8synthetic-jpeg\xff\xd9\r\n--boundary",
            b"\xff\xd8synthetic-jpeg\xff\xd9",
        ),
        (
            b"x" * 4095 + b"\xff\xd8synthetic-jpeg\xff\xd9",
            b"\xff\xd8synthetic-jpeg\xff\xd9",
        ),
        (b"<html>Login required</html>", None),
        (b"\xff\xd8truncated", None),
        (b"", None),
    ],
    ids=["jpeg", "multipart", "split-marker", "html", "truncated", "empty"],
)
async def test_mjpeg_probe_requires_complete_jpeg(hass, aioclient_mock, body, expected):
    url = "https://video.ujin.tech/synthetic/camera-31"
    aioclient_mock.get(url, content=body)
    assert await async_get_mjpeg_frame(async_get_clientsession(hass), url) == expected


@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
async def test_http_failure_or_redirect_is_not_healthy(hass, aioclient_mock, status):
    url = "https://video.ujin.tech/synthetic/camera-31"
    aioclient_mock.get(url, status=status, content=b"\xff\xd8synthetic-jpeg\xff\xd9")
    assert await async_get_mjpeg_frame(async_get_clientsession(hass), url) is None


async def test_cached_inventory_uses_actual_read_only_mjpeg_health_check(
    hass, entry, client, camera, aioclient_mock, inventory_store
):
    # No mjpeg_frame/make_coordinator fixture here: the real reader and real
    # coordinator run together, with only the remote HTTP response replaced.
    coordinator = DomylandCoordinator(hass, entry, client, True)
    await coordinator.async_initialize()
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    await coordinator.async_restore_cameras(11, [camera])
    aioclient_mock.get(camera["streamURL"], content=b"HTTP 200, but no JPEG")
    data = await coordinator._async_update_data()
    assert data.buildings[11].cameras == {}
    assert (await inventory_store().async_load())["buildings"]["11"]["cameras"]["31"] == camera

    # The stream is only read. Recovery must never send a door-open request.
    client.open_door.assert_not_awaited()
    assert aioclient_mock.call_count == 1
