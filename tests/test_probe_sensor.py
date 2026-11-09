"""Probe-сенсор: сырые ответы в атрибутах, ошибки эндпоинтов не роняют обновление."""

from custom_components.domyland.api import DomylandError
from custom_components.domyland.sensor import PROBE_ENDPOINTS, DomylandProbeSensor


async def test_probe_sensor_collects_ok_and_error(
    make_coordinator, client, refresh
):
    coordinator = await make_coordinator()
    buildings = await refresh(coordinator)
    assert 11 in buildings

    sensor = DomylandProbeSensor(coordinator, 11)

    async def probe_get(path, place_id=None, building_id=None):
        assert (place_id, building_id) == (101, 11)
        if path == "/meteringdata/dashboard":
            return {"success": True, "data": {"meters": [{"id": 1, "value": 42}]}}
        raise DomylandError(f"boom {path}")

    client.probe_get.side_effect = probe_get
    await sensor.async_update()

    assert sensor.native_value == f"ok (1/{len(PROBE_ENDPOINTS)})"
    attrs = sensor.extra_state_attributes
    assert attrs["/meteringdata/dashboard"]["status"] == "ok"
    assert '"value": 42' in attrs["/meteringdata/dashboard"]["data"]
    for path in PROBE_ENDPOINTS:
        if path != "/meteringdata/dashboard":
            assert attrs[path]["status"] == "error"
            assert attrs[path]["error"].startswith("boom")


async def test_probe_sensor_truncates_large_responses(make_coordinator, client, refresh):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    sensor = DomylandProbeSensor(coordinator, 11)

    client.probe_get.return_value = {"blob": "x" * 10_000}
    await sensor.async_update()

    blob = sensor.extra_state_attributes["/meteringdata/dashboard"]["data"]
    assert blob.endswith("…(truncated)")
    assert len(blob) < 4100
