"""Сенсоры счётчиков и счёта ЖКХ: парсинг значений, единицы, приватность."""

from custom_components.domyland.sensor import (
    DomylandInvoiceSensor,
    DomylandMeterSensor,
    _parse_number,
)


def test_parse_number():
    assert _parse_number("Показание 59.86 м³") == 59.86
    assert _parse_number("12 135,70 ₽") == 12135.70
    assert _parse_number("12\xa0135,70 ₽") == 12135.70
    assert _parse_number(None) is None
    assert _parse_number("Показаний нет") is None


def _meter_device():
    return {
        "id": 35858,
        "title": "Счётчик холодной воды",
        "signalName": "m3",
        "isMetering": True,
        "deviceName": "Счетчик воды электронный Пульсар",
        "indicators": [{"value": "Показание 59.86 м³", "icon": None}],
    }


async def test_meter_sensor_value_and_units(make_coordinator, client, refresh):
    client.get_place_management.return_value = {"devices": [_meter_device()]}
    coordinator = await make_coordinator()
    await refresh(coordinator)

    sensor = DomylandMeterSensor(coordinator, 11, 35858)
    assert sensor.available
    assert sensor.native_value == 59.86
    assert sensor.native_unit_of_measurement == "m³"
    assert sensor.device_class == "water"
    assert sensor.name == "Счётчик холодной воды"
    assert sensor.extra_state_attributes["device_name"] == (
        "Счетчик воды электронный Пульсар"
    )


async def test_meter_sensor_unavailable_without_device(
    make_coordinator, client, refresh
):
    client.get_place_management.return_value = {"devices": []}
    coordinator = await make_coordinator()
    await refresh(coordinator)

    sensor = DomylandMeterSensor(coordinator, 11, 35858)
    assert not sensor.available
    assert sensor.native_value is None


async def test_heat_meter_unit_gcal(make_coordinator, client, refresh):
    device = {**_meter_device(), "signalName": "gcal", "indicators": [
        {"value": "Показание 3.5 Гкал", "icon": None}
    ]}
    client.get_place_management.return_value = {"devices": [device]}
    coordinator = await make_coordinator()
    await refresh(coordinator)

    sensor = DomylandMeterSensor(coordinator, 11, 35858)
    assert sensor.native_value == 3.5
    assert sensor.native_unit_of_measurement == "Гкал"
    assert sensor.device_class is None


async def test_invoice_sensor_value_and_no_payment_tokens(
    make_coordinator, client, refresh
):
    client.get_payment_widget.return_value = {
        "invoicesCount": 1,
        "title": "У вас 1 счёт за 1 помещение",
        "amountText": "12 135,70 ₽",
        "action": {"paymentContext": "SECRET-CONTEXT"},
        "paymentLink": "https://pay.domyland.ru/SECRET",
    }
    coordinator = await make_coordinator()
    await refresh(coordinator)

    sensor = DomylandInvoiceSensor(coordinator, 11)
    assert sensor.native_value == 12135.70
    assert sensor.native_unit_of_measurement == "₽"
    assert sensor.extra_state_attributes == {
        "invoices_count": 1,
        "title": "У вас 1 счёт за 1 помещение",
    }
    blob = str(sensor.extra_state_attributes)
    assert "SECRET" not in blob


async def test_orders_sensor_active_only(make_coordinator, client, refresh):
    client.get_orders_dispatcher.return_value = [
        {
            "id": 5998086,
            "title": "Гарантия",
            "orderStatusTitle": "В работе",
            "createdAtFormatted": "29 июля в 13:37",
            "hasStatusUpdate": True,
            "unreadCustomerMessagesCount": 0,
        }
    ]
    coordinator = await make_coordinator()
    await refresh(coordinator)

    from custom_components.domyland.sensor import DomylandOrdersSensor

    sensor = DomylandOrdersSensor(coordinator, 11)
    assert sensor.native_value == 1
    attrs = sensor.extra_state_attributes
    assert attrs["orders"][0]["title"] == "Гарантия"
    assert attrs["orders"][0]["status"] == "В работе"
    assert attrs["has_status_updates"] is True


async def test_orders_sensor_empty(make_coordinator, client, refresh):
    coordinator = await make_coordinator()
    await refresh(coordinator)

    from custom_components.domyland.sensor import DomylandOrdersSensor

    sensor = DomylandOrdersSensor(coordinator, 11)
    assert sensor.native_value == 0
    assert sensor.extra_state_attributes["has_status_updates"] is False


async def test_passes_sensor_counts(make_coordinator, client, refresh):
    client.get_guest_passes.return_value = [{"id": 1, "title": "Гость"}]
    coordinator = await make_coordinator()
    await refresh(coordinator)

    from custom_components.domyland.sensor import DomylandPassesSensor

    sensor = DomylandPassesSensor(coordinator, 11)
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["passes"][0]["title"] == "Гость"


async def test_notifications_sensor_unread_count(make_coordinator, client, refresh):
    client.get_notifications.return_value = [
        {"id": 1, "title": "Долг", "preview": "Вы в списке должников",
         "label": "31 октября", "isViewed": False},
        {"id": 2, "title": "Новость", "preview": "Текст",
         "label": "1 октября", "isViewed": True},
    ]
    coordinator = await make_coordinator()
    await refresh(coordinator)

    from custom_components.domyland.sensor import DomylandNotificationsSensor

    sensor = DomylandNotificationsSensor(coordinator, 11)
    assert sensor.native_value == 1
    items = sensor.extra_state_attributes["notifications"]
    assert items[0]["title"] == "Долг"
    assert items[1]["is_viewed"] is True
