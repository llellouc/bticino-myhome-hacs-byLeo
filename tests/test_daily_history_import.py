"""End-to-end tests for daily energy and water history imports."""

from __future__ import annotations

from functools import partial
import json
from datetime import date, datetime, timedelta, timezone

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


def _import_point_start(hass, day: date) -> datetime:
    """Compute the expected import write timestamp for a given calendar day.

    Mirrors web.py's own day-shift + local-timezone logic (the reconstructed
    cumulative point for day D is only known at the start of local day D+1,
    converted to UTC) so tests stay in sync with production behavior instead
    of re-deriving/hardcoding the same math separately.
    """
    tz = MyHOMEImportDailyEnergyHistoryView._local_tzinfo(hass)
    return MyHOMEImportDailyEnergyHistoryView._day_end_utc(day, tz)


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
            "allow_external_fallback": True,
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
        _import_point_start(hass, history_rows[0]["date"]) - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )

    rows = persisted[statistic_id]
    assert [row["state"] for row in rows] == [
        expected_values[0],
        expected_values[0] + expected_values[1],
    ]
    assert [row["sum"] for row in rows] == [
        expected_values[0],
        expected_values[0] + expected_values[1],
    ]
    metadata = await _statistic_metadata(hass, statistic_id)
    assert metadata[statistic_id][1]["unit_of_measurement"] == expected_unit


async def test_import_never_overwrites_day_with_partial_existing_hourly_data(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """A day with even a single pre-existing real hourly point must be skipped.

    Regression test: previously, days with fewer than 3 existing hourly
    statistics points were treated as if they had no real data at all,
    so the daily import would still write its own reconstructed point for
    that day. When that point's timestamp coincided with an already
    existing real hourly statistic (e.g. a boundary day where live
    collection had only just started), the upsert silently replaced the
    real value with our reconstruction, producing a visible spike/drop
    in the entity's history graph.
    """
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
        async_wait_recording_done,
    )

    await async_setup_recorder_instance(hass)
    view, _gateway_handler, config = configured_import_view
    config["sensor"]["test_sensor"]["class"] = "energy"

    statistic_id = f"{DOMAIN}:{sanitize_key(f'daily_{GATEWAY_MAC}_energy_51')}"
    first_day = history_rows[0]["date"]
    # Exact collision scenario: a real hourly point already sits at the
    # precise timestamp our own import would write to for first_day (the
    # start of first_day's local next day, converted to UTC).
    existing_start = _import_point_start(hass, first_day)
    real_existing_state = 999999.0

    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_mean=False,
            has_sum=True,
            name="Test counter daily import",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class="energy",
            unit_of_measurement="Wh",
        ),
        [
            StatisticData(
                start=existing_start,
                state=real_existing_state,
                sum=real_existing_state,
            )
        ],
    )
    await async_wait_recording_done(hass)

    request = import_request(
        {
            "gateway": GATEWAY_MAC,
            "sensor_key": "test_sensor",
            "allow_external_fallback": True,
        }
    )
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["errors"] == []
    # Only the second day should have been imported; the first day already
    # has (partial) real hourly data and must be preserved untouched.
    assert body["imported"][0]["rows"] == 1
    assert body["imported"][0]["skipped_hourly_days"] == 1

    await async_recorder_block_till_done(hass)
    persisted = await _statistics_rows(
        hass,
        statistic_id,
        existing_start - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )
    rows = persisted[statistic_id]

    # Only two hourly rows should exist in this window: the untouched
    # pre-existing real point (first) and our reconstructed import for the
    # second day. The real point's state must be preserved unchanged.
    assert len(rows) == 2
    assert rows[0]["state"] == real_existing_state
    assert rows[0]["sum"] == real_existing_state


async def test_import_can_force_override_hourly_data_when_flag_disabled(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """Unchecking "dont_override_hourly" bypasses the hourly-collision guard.

    Same setup as test_import_never_overwrites_day_with_partial_existing_hourly_data,
    but with dont_override_hourly=False: the import must now write over the
    existing real hourly point instead of skipping that day.
    """
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
        async_wait_recording_done,
    )

    await async_setup_recorder_instance(hass)
    view, _gateway_handler, config = configured_import_view
    config["sensor"]["test_sensor"]["class"] = "energy"

    statistic_id = f"{DOMAIN}:{sanitize_key(f'daily_{GATEWAY_MAC}_energy_51')}"
    first_day = history_rows[0]["date"]
    existing_start = _import_point_start(hass, first_day)
    real_existing_state = 999999.0

    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_mean=False,
            has_sum=True,
            name="Test counter daily import",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class="energy",
            unit_of_measurement="Wh",
        ),
        [
            StatisticData(
                start=existing_start,
                state=real_existing_state,
                sum=real_existing_state,
            )
        ],
    )
    await async_wait_recording_done(hass)

    request = import_request(
        {
            "gateway": GATEWAY_MAC,
            "sensor_key": "test_sensor",
            "allow_external_fallback": True,
            "dont_override_hourly": False,
        }
    )
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["errors"] == []
    # Both days should be imported now: the guard is bypassed when the flag
    # is disabled, so the first day's pre-existing point gets overwritten.
    assert body["imported"][0]["rows"] == 2
    assert body["imported"][0]["skipped_hourly_days"] == 0
    assert body["dont_override_hourly"] is False

    await async_recorder_block_till_done(hass)
    persisted = await _statistics_rows(
        hass,
        statistic_id,
        existing_start - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )
    rows = persisted[statistic_id]

    assert len(rows) == 2
    # The first day's real point must now be overwritten by our reconstruction.
    assert rows[0]["state"] != real_existing_state
    assert rows[0]["sum"] != real_existing_state


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
        _import_point_start(hass, history_rows[0]["date"]) - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )
    assert [row["state"] for row in persisted[entity_id]] == [1500.0, 4000.0]


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


async def test_import_reports_missing_entity_id_when_fallback_disabled(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
):
    """Import fails explicitly when no matching entity statistic id is found."""
    await async_setup_recorder_instance(hass)
    view, _gateway_handler, config = configured_import_view
    config["sensor"]["test_sensor"]["class"] = "power_energy"

    request = import_request({"gateway": GATEWAY_MAC, "sensor_key": "test_sensor"})
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 500
    assert body["ok"] is False
    assert len(body["errors"]) == 1
    assert "entity statistic id not found" in body["errors"][0]
    assert body["imported"][0]["rows"] == 0
    assert body["imported"][0]["statistic_id"] is None


async def test_import_skips_zero_daily_values(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """Import ignores zero-value days to keep graphs readable."""
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
    )

    await async_setup_recorder_instance(hass)
    view, gateway_handler, config = configured_import_view
    config["sensor"]["test_sensor"]["class"] = "energy"
    gateway_handler.fetch_daily_history.return_value = [
        history_rows[0],
        {"date": history_rows[1]["date"] + timedelta(days=1), "value": 0.0},
        history_rows[1],
    ]

    request = import_request(
        {
            "gateway": GATEWAY_MAC,
            "sensor_key": "test_sensor",
            "allow_external_fallback": True,
        }
    )
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["ok"] is True
    assert body["errors"] == []
    assert body["imported"][0]["rows"] == 2
    assert body["imported"][0]["skipped_zero_days"] == 1

    await async_recorder_block_till_done(hass)
    statistic_id = f"{DOMAIN}:{sanitize_key(f'daily_{GATEWAY_MAC}_energy_51')}"
    persisted = await _statistics_rows(
        hass,
        statistic_id,
        _import_point_start(hass, history_rows[0]["date"]) - timedelta(hours=1),
        _import_point_start(hass, history_rows[1]["date"]) + timedelta(hours=1),
    )
    assert [row["state"] for row in persisted[statistic_id]] == [1500.0, 4000.0]


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
        _import_point_start(hass, history_rows[0]["date"]) - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )
    assert [row["state"] for row in persisted[entity_id]] == [1500.0, 4000.0]


def _hourly_point_start(hass, day: date, hour: int) -> datetime:
    """Compute the expected write timestamp for one imported hourly point."""
    tz = MyHOMEImportDailyEnergyHistoryView._local_tzinfo(hass)
    return MyHOMEImportDailyEnergyHistoryView._local_hour_utc(day, hour, tz)


def _hourly_rows_for(day: date, values: list[float]) -> list[dict[str, object]]:
    """Build gateway hourly rows (one per hour) for a single local day."""
    return [
        {"date": day, "hour": hour, "value": value}
        for hour, value in enumerate(values)
    ]


async def test_import_uses_hourly_detail_when_available(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """Hourly detail produces one point per hour, aligned on HA hour buckets.

    The gateway reports both a per-day total (dimensions 513/514) and, for
    roughly the last year, the 24 hourly values of a day (dimension 511).
    Hourly points land on exactly the same buckets Home Assistant uses for
    real statistics, so they must be preferred when available.
    """
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
    )

    await async_setup_recorder_instance(hass)
    view, gateway_handler, _config = configured_import_view

    first_day = history_rows[0]["date"]
    # 24 hourly values summing exactly to that day's daily total (1500),
    # mirroring what a real F454 returns.
    hourly_values = [100.0, 200.0, 300.0, 400.0, 500.0] + [0.0] * 19
    gateway_handler.fetch_hourly_history.return_value = _hourly_rows_for(
        first_day, hourly_values
    )

    request = import_request(
        {
            "gateway": GATEWAY_MAC,
            "sensor_key": "test_sensor",
            "allow_external_fallback": True,
            "months_back": 24,
            "query_delay_ms": 0,
        }
    )
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["errors"] == []
    assert body["imported"][0]["hourly_detail_days"] == 1
    # 24 hourly points for the first day + 1 daily point for the second.
    assert body["imported"][0]["rows"] == 25

    await async_recorder_block_till_done(hass)

    statistic_id = f"{DOMAIN}:{sanitize_key(f'daily_{GATEWAY_MAC}_energy_51')}"
    persisted = await _statistics_rows(
        hass,
        statistic_id,
        _hourly_point_start(hass, first_day, 0) - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )
    rows = persisted[statistic_id]

    assert len(rows) == 25
    # Each hourly point must sit on its own local hour bucket.
    assert rows[0]["start"] == _hourly_point_start(hass, first_day, 0).timestamp()
    assert rows[1]["start"] == _hourly_point_start(hass, first_day, 1).timestamp()
    # The running sum accumulates hour by hour, then adds the next day's total.
    assert [row["sum"] for row in rows[:5]] == [100.0, 300.0, 600.0, 1000.0, 1500.0]
    assert rows[-1]["sum"] == 1500.0 + 2500.0


async def test_import_skips_only_colliding_hours(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """With hourly detail, only the exact colliding hour is skipped.

    The daily import used to skip a whole day as soon as any real hourly
    statistic existed for it. With hour-level points the guard becomes
    precise: a real row only blocks the single hour bucket it occupies.
    """
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
        async_wait_recording_done,
    )

    await async_setup_recorder_instance(hass)
    view, gateway_handler, _config = configured_import_view

    first_day = history_rows[0]["date"]
    hourly_values = [100.0, 200.0, 300.0, 400.0, 500.0] + [0.0] * 19
    gateway_handler.fetch_hourly_history.return_value = _hourly_rows_for(
        first_day, hourly_values
    )

    statistic_id = f"{DOMAIN}:{sanitize_key(f'daily_{GATEWAY_MAC}_energy_51')}"
    collision_start = _hourly_point_start(hass, first_day, 2)
    real_existing_state = 999999.0

    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_mean=False,
            has_sum=True,
            name="Test counter daily import",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class="energy",
            unit_of_measurement="Wh",
        ),
        [
            StatisticData(
                start=collision_start,
                state=real_existing_state,
                sum=real_existing_state,
            )
        ],
    )
    await async_wait_recording_done(hass)

    request = import_request(
        {
            "gateway": GATEWAY_MAC,
            "sensor_key": "test_sensor",
            "allow_external_fallback": True,
            "months_back": 24,
            "query_delay_ms": 0,
        }
    )
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["errors"] == []
    # 25 candidate points minus the single colliding hour.
    assert body["imported"][0]["rows"] == 24
    assert body["imported"][0]["skipped_hourly_days"] == 1

    await async_recorder_block_till_done(hass)

    persisted = await _statistics_rows(
        hass,
        statistic_id,
        _hourly_point_start(hass, first_day, 0) - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )
    rows = persisted[statistic_id]
    by_start = {row["start"]: row for row in rows}

    # The real value must survive untouched...
    assert by_start[collision_start.timestamp()]["sum"] == real_existing_state
    # ...while the surrounding hours are still imported normally.
    assert by_start[_hourly_point_start(hass, first_day, 1).timestamp()]["sum"] == 300.0
    assert by_start[_hourly_point_start(hass, first_day, 3).timestamp()]["sum"] == 1000.0


async def test_import_falls_back_to_daily_point_for_incomplete_hourly_day(
    async_setup_recorder_instance,
    hass,
    configured_import_view,
    history_rows,
):
    """A day with fewer than 24 hourly values must not be imported hourly.

    The gateway can go quiet mid-reply under load and return only part of a
    day's 24 hourly values. Importing such a truncated day both under-counts
    its energy and, on a re-import, leaves the missing hours holding the
    previous run's cumulative offset - which appears as a day-wide step in
    the energy graph. The day's single, always-consistent daily total is
    used instead.
    """
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
    )

    await async_setup_recorder_instance(hass)
    view, gateway_handler, _config = configured_import_view

    first_day = history_rows[0]["date"]
    # Only 5 of the 24 hourly values came back, as during a flaky bulk fetch.
    gateway_handler.fetch_hourly_history.return_value = _hourly_rows_for(
        first_day, [100.0, 200.0, 300.0, 400.0, 500.0]
    )

    request = import_request(
        {
            "gateway": GATEWAY_MAC,
            "sensor_key": "test_sensor",
            "allow_external_fallback": True,
            "months_back": 24,
            "query_delay_ms": 0,
        }
    )
    request.app["hass"] = hass

    response = await view.post(request)
    body = json.loads(response.text)

    assert response.status == 200, body
    assert body["errors"] == []
    # The truncated day is reported, not silently accepted.
    assert body["imported"][0]["hourly_detail_days"] == 0
    assert body["imported"][0]["skipped_partial_hourly_days"] == 1
    # One end-of-day point per day instead of 24 hourly points + 1.
    assert body["imported"][0]["rows"] == 2

    await async_recorder_block_till_done(hass)

    statistic_id = f"{DOMAIN}:{sanitize_key(f'daily_{GATEWAY_MAC}_energy_51')}"
    persisted = await _statistics_rows(
        hass,
        statistic_id,
        _import_point_start(hass, first_day) - timedelta(hours=1),
        _import_point_start(hass, history_rows[-1]["date"]) + timedelta(hours=1),
    )
    rows = persisted[statistic_id]

    # The full daily total is used, not the 1500 partial sum of the 5 hours.
    assert [row["sum"] for row in rows] == [1500.0, 1500.0 + 2500.0]
