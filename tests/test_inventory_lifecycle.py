"""Removing an account also removes only that account's private camera URLs."""

from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.domyland.const import DOMAIN


async def test_removing_config_entry_deletes_only_its_inventory(
    hass, entry, make_coordinator, refresh, inventory_store, camera
):
    coordinator = await make_coordinator()
    await refresh(coordinator)
    await coordinator.async_restore_cameras(11, [camera])
    assert await inventory_store().async_load() is not None

    other = MockConfigEntry(domain=DOMAIN, unique_id="synthetic-other-account")
    other.add_to_hass(hass)
    other_key = f"domyland.{other.entry_id}.inventory"
    other_snapshot = {"buildings": {"11": {"doors": {}, "cameras": {"31": camera}}}}
    await Store(hass, 1, other_key, private=True).async_save(other_snapshot)

    await hass.config_entries.async_remove(entry.entry_id)

    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert await inventory_store().async_load() is None
    assert await Store(hass, 1, other_key, private=True).async_load() == other_snapshot
