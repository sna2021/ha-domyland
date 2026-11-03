"""Exercise HA's real options manager with the real import coordinator."""

import json
from copy import deepcopy

import pytest
from homeassistant.data_entry_flow import FlowResultType


async def test_options_form_keeps_backup_optional_and_multiline(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults == {"enable_cameras": True, "camera_backup": ""}
    marker = next(
        field for field in result["data_schema"].schema if field.schema == "camera_backup"
    )
    selector = result["data_schema"].schema[marker]
    assert selector.config["multiline"] is True


@pytest.mark.parametrize(
    "invalid_backup",
    [
        "{broken json",
        "null",
        "[]",
        "{}",
        '{"building_id":true,"cameras":[]}',
        '{"building_id":11,"cameras":"not a list"}',
        '{"building_id":11,"cameras":[null]}',
        '{"building_id":11,"cameras":[{"id":31,"title":"Synthetic camera","streamURL":"https://example.invalid/synthetic"}]}',
    ],
    ids=[
        "invalid-json", "null", "array", "missing-fields", "boolean-building",
        "invalid-collection", "invalid-camera", "coordinator-semantic-rejection",
    ],
)
async def test_invalid_backup_preserves_text_and_does_not_save_changed_options(
    invalid_backup, hass, entry, make_coordinator, refresh, inventory_store
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    before = deepcopy(await inventory_store().async_load())
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        user_input={"enable_cameras": False, "camera_backup": invalid_backup},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"camera_backup": "invalid_camera_backup"}
    assert result["data_schema"]({}) == {
        "enable_cameras": False,
        "camera_backup": invalid_backup,
    }
    assert dict(entry.options) == {"enable_cameras": True}
    assert await inventory_store().async_load() == before


async def test_valid_backup_saves_sources_but_never_backup_text_in_options(
    hass, entry, make_coordinator, refresh, inventory_store, camera
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        user_input={
            "enable_cameras": False,
            "camera_backup": json.dumps({"building_id": 11, "cameras": [camera]}),
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"enable_cameras": False}
    assert dict(entry.options) == {"enable_cameras": False}
    assert (await inventory_store().async_load())["buildings"]["11"]["cameras"] == {
        "31": camera
    }
    # Reopening options must not reflect confidential URLs from inventory.
    reopened = await hass.config_entries.options.async_init(entry.entry_id)
    assert reopened["data_schema"]({}) == {
        "enable_cameras": False,
        "camera_backup": "",
    }


async def test_invalid_import_can_be_corrected_within_same_options_flow(
    hass, entry, make_coordinator, refresh, inventory_store, camera
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    invalid = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        user_input={"enable_cameras": False, "camera_backup": "not json"},
    )
    assert invalid["type"] is FlowResultType.FORM
    corrected = await hass.config_entries.options.async_configure(
        invalid["flow_id"],
        user_input={
            "enable_cameras": True,
            "camera_backup": json.dumps({"building_id": 11, "cameras": [camera]}),
        },
    )
    assert corrected["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"enable_cameras": True}
    assert (await inventory_store().async_load())["buildings"]["11"]["cameras"]["31"] == camera


@pytest.mark.parametrize("backup", [None, ""])
async def test_normal_camera_option_change_needs_no_backup(
    backup, hass, entry, inventory_store
):
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {"enable_cameras": False}
    if backup is not None:
        user_input["camera_backup"] = backup
    result = await hass.config_entries.options.async_configure(
        initial["flow_id"], user_input=user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"enable_cameras": False}
    assert await inventory_store().async_load() is None
