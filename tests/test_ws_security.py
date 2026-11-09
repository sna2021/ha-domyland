"""WS-команды: требование admin и выбор дома."""

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import Unauthorized

from custom_components.domyland.__init__ import _first_building
from custom_components.domyland.manual import ws_list


class _Conn:
    def __init__(self, admin):
        self.user = SimpleNamespace(is_admin=admin)
        self.result = None
        self.error = None

    def send_result(self, mid, result=None):
        self.result = result

    def send_error(self, mid, code, message):
        self.error = (code, message)


async def test_manual_readings_list_requires_admin(hass):
    conn = _Conn(admin=False)
    with pytest.raises(Unauthorized):
        ws_list(hass, conn, {"id": 1})
    assert conn.result is None


async def test_manual_readings_list_allows_admin(hass):
    conn = _Conn(admin=True)
    ws_list(hass, conn, {"id": 1})
    await hass.async_block_till_done()
    assert conn.error is None
    assert conn.result == {}


async def test_first_building_without_entries(hass):
    coordinator, building = _first_building(hass, None)
    assert coordinator is None and building is None


async def test_first_building_unknown_id_returns_none(hass):
    coordinator, building = _first_building(hass, 999999)
    assert coordinator is None and building is None
