"""Ручные показания счётчиков: сохранение/чтение через Store."""

from custom_components.domyland.manual import _load, async_save_reading


async def test_manual_readings_set_and_list(hass):
    readings = await async_save_reading(hass, "meter_35858", 59.86)
    assert readings["meter_35858"]["value"] == 59.86
    assert readings["meter_35858"]["updated_at"] > 0

    loaded = await _load(hass)
    assert loaded["meter_35858"]["value"] == 59.86


async def test_manual_readings_overwrite(hass):
    await async_save_reading(hass, "meter_35858", 60.0)
    readings = await async_save_reading(hass, "meter_35858", 61.5)
    assert readings["meter_35858"]["value"] == 61.5


async def test_manual_readings_independent_keys(hass):
    await async_save_reading(hass, "meter_35858", 59.86)
    readings = await async_save_reading(hass, "ukmeter_3001813_t1", 100.0)
    assert readings["meter_35858"]["value"] == 59.86
    assert readings["ukmeter_3001813_t1"]["value"] == 100.0
