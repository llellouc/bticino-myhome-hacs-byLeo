"""End-to-end tests for daily energy and water history imports."""

from __future__ import annotations

from functools import partial
import json
from datetime import date, datetime, timezone

import pytest

from custom_components.bticino_myhome.const import DOMAIN
from custom_components.bticino_myhome.helpers.web_helpers import sanitize_key
from custom_components.bticino_myhome.web import MyHOMEImportDailyEnergyHistoryView

from .conftest import GATEWAY_MAC, import_request


async def _statistics_rows(hass, statistic_id: str, start: datetime, end: datetime):
    """Read persisted Recorder statistics outside Home Assistant's event loop."""
    from homeassistant.components.recorder import statistics

    return await hass.async_add_executor_job(
        statistics.statistics_during_period,
        hass,
        start,
        end,
        [statistic_id],
        "hour",
        None,
        {"state", "sum"},
    )


async def _statistic_metadata(hass, statistic_id: str):
    """Read persisted Recorder metadata outside Home Assistant's event loop."""
    from homeassistant.components.recorder import statistics

    return await hass.async_add_executor_job(
        partial(statistics.get_metadata, hass, statistic_ids={statistic_id}),
    )


@pytest.mark.parametrize(
    ("sensor_class", "unit_scale", "expected_unit", "expected_values"),
    [
        ("energy", "base", "Wh", [1500.0, 2500.0]),
        ("energy", "kilo", "kWh", [1.5, 2.5]),
        ("water", "base", "L", [1500.0, 2500.0]),
        ("water", "kilo", "m³", [1.5, 2.5]),
    ],
)
async def test_import_persists_scaled_daily_statistics(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
    sensor_class,
    unit_scale,
    expected_unit,
    expected_values,
):
    """Import writes actual Recorder rows with scaled values and running sums."""
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
    )

    await async_setup_recorder_instance(hass)
    view, gateway_handler, config = configured_import_view
    config["sensor"]["test_sensor"]["class"] = sensor_class
    config["sensor"]["test_sensor"]["unit_scale"] = unit_scale

    request = import_request(
        {
            "gateway": GATEWAY_MAC,
            "sensor_key": "test_sensor",
            "months_back": 24,
            "query_delay_ms": 0,
        }
    )
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["ok"] is True
    assert body["errors"] == []
    assert body["imported"][0]["rows"] == 2
    assert gateway_handler.fetch_daily_history.await_count == 1

    await async_recorder_block_till_done(hass)

    statistic_id = (
        f"{DOMAIN}:{sanitize_key(f'daily_{GATEWAY_MAC}_{sensor_class}_51')}"
    )
    persisted = await _statistics_rows(
        hass,
        statistic_id,
        datetime.combine(history_rows[0]["date"], datetime.min.time(), timezone.utc),
        datetime.combine(history_rows[-1]["date"], datetime.max.time(), timezone.utc),
    )

    rows = persisted[statistic_id]
    assert [row["state"] for row in rows] == expected_values
    assert [row["sum"] for row in rows] == [
        expected_values[0],
        expected_values[0] + expected_values[1],
    ]
    metadata = await _statistic_metadata(hass, statistic_id)
    assert metadata[statistic_id][1]["unit_of_measurement"] == expected_unit


async def test_power_energy_import_targets_existing_energy_entity(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """Import historical rows into the existing total-energy entity statistic."""
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
    )

    await async_setup_recorder_instance(hass)
    view, _gateway_handler, config = configured_import_view
    config["sensor"]["test_sensor"]["class"] = "power_energy"
    entity_id = "sensor.test_counter_energy"
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{GATEWAY_MAC}-test_sensor-total-energy",
        suggested_object_id="test_counter_energy",
    )
    assert entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{GATEWAY_MAC}-test_sensor-total-energy",
    ) == entity_id

    request = import_request({"gateway": GATEWAY_MAC, "sensor_key": "test_sensor"})
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["errors"] == []
    assert body["imported"][0]["statistic_id"] == entity_id
    assert body["imported"][0]["entity_statistic_id"] == entity_id
    assert body["imported"][0]["persisted_rows"] == 2

    await async_recorder_block_till_done(hass)
    persisted = await _statistics_rows(
        hass,
        entity_id,
        datetime.combine(history_rows[0]["date"], datetime.min.time(), timezone.utc),
        datetime.combine(history_rows[-1]["date"], datetime.max.time(), timezone.utc),
    )
    assert [row["state"] for row in persisted[entity_id]] == [1500.0, 2500.0]


async def test_import_reports_gateway_failure_without_writing_statistics(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
):
    """Gateway failures are returned by the API and do not create statistics."""
    await async_setup_recorder_instance(hass)
    view, gateway_handler, _config = configured_import_view
    gateway_handler.fetch_daily_history.side_effect = ConnectionError("F454 unavailable")

    request = import_request({"gateway": GATEWAY_MAC, "sensor_key": "test_sensor"})
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 500
    assert body["ok"] is False
    assert body["imported"] == []
    assert body["errors"] == ["51: failed to fetch gateway history (ConnectionError: F454 unavailable)"]


def test_recorder_payload_rejects_invalid_external_statistic_source():
    """Payload validation catches rejected Recorder metadata before enqueueing."""
    metadata = {"statistic_id": "bticino_myhome:daily_counter", "source": "recorder"}
    statistic = {
        "start": datetime(2024, 1, 10, tzinfo=timezone.utc),
    }

    assert MyHOMEImportDailyEnergyHistoryView._validate_recorder_payload(
        entity_statistic_id=None,
        metadata=metadata,
        statistics_rows=[statistic],
    ) == "external source 'recorder' must match statistic domain 'bticino_myhome'"


async def test_power_energy_import_legacy_entity_naming_fallback(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """Import resolves legacy entity unique_id pattern when new pattern not found."""
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
    )

    await async_setup_recorder_instance(hass)
    view, _gateway_handler, config = configured_import_view
    config["sensor"]["test_sensor"]["class"] = "power_energy"
    entity_id = "sensor.legacy_energy"
    entity_registry = er.async_get(hass)
    
    # Create entity with legacy naming scheme: {gateway}-{who}-{where}-total-energy
    where = "51"
    legacy_unique_id = f"{GATEWAY_MAC}-18-{where}-total-energy"
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        legacy_unique_id,
        suggested_object_id="legacy_energy",
    )
    assert entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        legacy_unique_id,
    ) == entity_id

    request = import_request({"gateway": GATEWAY_MAC, "sensor_key": "test_sensor"})
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["errors"] == []
    # Fallback resolution should find the legacy entity
    assert body["imported"][0]["statistic_id"] == entity_id
    assert body["imported"][0]["entity_statistic_id"] == entity_id
    assert body["imported"][0]["persisted_rows"] == 2

    await async_recorder_block_till_done(hass)
    persisted = await _statistics_rows(
        hass,
        entity_id,
        datetime.combine(history_rows[0]["date"], datetime.min.time(), timezone.utc),
        datetime.combine(history_rows[-1]["date"], datetime.max.time(), timezone.utc),
    )
    assert [row["state"] for row in persisted[entity_id]] == [1500.0, 2500.0]
