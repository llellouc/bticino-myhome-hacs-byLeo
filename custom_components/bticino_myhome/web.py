"""Web UI endpoints and panel registration for MyHOME discovery."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from http import HTTPStatus
from json import JSONDecodeError
from math import isclose
from pathlib import Path
from typing import Any

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.const import CONF_MAC
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_CLASS,
    CONF_ENTITY,
    CONF_PLATFORMS,
    CONF_UNIT_SCALE,
    CONF_WHERE,
    CONF_ZONE,
    DISCOVERY_DEFAULT_AREA_END,
    DISCOVERY_DEFAULT_AREA_START,
    DISCOVERY_DEFAULT_DURATION,
    DISCOVERY_DEFAULT_POINT_END,
    DISCOVERY_DEFAULT_POINT_START,
    DOMAIN,
    LOGGER,
)
from .config_store import (
    async_clear_activation_discovery_results,
    async_get_activation_discovery_results,
    async_get_gateway_config,
    async_set_activation_discovery_results,
    async_set_gateway_config,
)
from .validate import config_schema, format_mac
from .helpers.web_helpers import (
    LIGHT_PLATFORM,
    COVER_PLATFORM,
    CLIMATE_PLATFORM,
    SENSOR_PLATFORM,
    CONFIG_PLATFORMS,
    to_bool,
    to_int,
    sanitize_key,
    resolve_gateway_from_payload,
    reload_gateway_entry,
    device_from_payload,
    devices_for_ui,
    configured_discovery_endpoints,
    mapped_results,
    merge_discovery_results,
    is_valid_discovery_climate,
    build_discovery_snippet,
)

PANEL_URL_PATH = "bticino-myhome-discovery"
PANEL_WEBCOMPONENT_NAME = "bticino-myhome-discovery-panel"
PANEL_TITLE = "bticino MyHome Unofficial Integration"
PANEL_ICON = "mdi:radar"
PANEL_STATIC_URL_PATH = "/api/bticino_myhome/panel"
PANEL_MODULE_URL = f"{PANEL_STATIC_URL_PATH}/bticino-myhome-discovery-main.js"
WEB_RUNTIME_DATA = f"{DOMAIN}_web_runtime"


def _runtime_data(hass) -> dict[str, Any]:
    """Return mutable runtime data for web resources."""
    return hass.data.setdefault(
        WEB_RUNTIME_DATA,
        {
            "api_registered": False,
            "panel_registered": False,
            "entry_count": 0,
        },
    )


async def _safe_get_gateway_config(hass, gateway: str) -> dict[str, Any]:
    """Read gateway config with explicit error propagation."""
    try:
        payload = await async_get_gateway_config(hass, gateway)
    except Exception as err:  # pylint: disable=broad-except
        raise RuntimeError(
            f"Storage read failed for gateway {gateway}: {type(err).__name__}: {err}"
        ) from err
    return payload or {CONF_MAC: gateway}


async def _safe_set_gateway_config(hass, gateway: str, payload: dict[str, Any]) -> None:
    """Persist gateway config with explicit error propagation."""
    try:
        await async_set_gateway_config(hass, gateway, payload)
    except Exception as err:  # pylint: disable=broad-except
        raise RuntimeError(
            f"Storage write failed for gateway {gateway}: {type(err).__name__}: {err}"
        ) from err


async def _safe_reload_gateway_entry(hass, gateway: str) -> None:
    """Reload gateway entry with explicit error propagation."""
    try:
        await reload_gateway_entry(hass, gateway)
    except Exception as err:  # pylint: disable=broad-except
        raise RuntimeError(
            f"Gateway reload failed for {gateway}: {type(err).__name__}: {err}"
        ) from err


async def _safe_get_activation_discovery_results(hass, gateway: str) -> dict[str, list[str]]:
    """Load activation discovery snapshot with explicit error propagation."""
    try:
        return await async_get_activation_discovery_results(hass, gateway)
    except Exception as err:  # pylint: disable=broad-except
        raise RuntimeError(
            "Activation discovery read failed "
            f"for gateway {gateway}: {type(err).__name__}: {err}"
        ) from err


async def _safe_set_activation_discovery_results(
    hass,
    gateway: str,
    snapshot: dict[str, Any],
) -> None:
    """Persist activation discovery snapshot with explicit error propagation."""
    try:
        await async_set_activation_discovery_results(hass, gateway, snapshot)
    except Exception as err:  # pylint: disable=broad-except
        raise RuntimeError(
            "Activation discovery write failed "
            f"for gateway {gateway}: {type(err).__name__}: {err}"
        ) from err


async def _safe_clear_activation_discovery_results(hass, gateway: str) -> None:
    """Clear activation discovery snapshot with explicit error propagation."""
    try:
        await async_clear_activation_discovery_results(hass, gateway)
    except Exception as err:  # pylint: disable=broad-except
        raise RuntimeError(
            "Activation discovery clear failed "
            f"for gateway {gateway}: {type(err).__name__}: {err}"
        ) from err


class MyHOMEGatewaysView(HomeAssistantView):
    """Return configured gateways for panel UI."""

    url = "/api/bticino_myhome/gateways"
    name = "api:bticino_myhome:gateways"
    requires_auth = True

    async def get(self, request):
        """Handle gateway list requests."""
        hass = request.app["hass"]
        gateways = []

        for mac, gateway_data in hass.data.get(DOMAIN, {}).items():
            gateway_handler = gateway_data.get(CONF_ENTITY)
            if gateway_handler is None:
                continue

            gateways.append(
                {
                    "mac": mac,
                    "name": gateway_handler.name,
                    "host": gateway_handler.gateway.host,
                    "discovery_by_activation": gateway_handler.discovery_by_activation,
                }
            )

        gateways.sort(key=lambda gateway: gateway["mac"])
        return self.json({"gateways": gateways})


class MyHOMEConfigurationView(HomeAssistantView):
    """Read/write configured devices from panel UI."""

    url = "/api/bticino_myhome/configuration"
    name = "api:bticino_myhome:configuration"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = resolve_gateway_from_payload(
            configured_gateways,
            request.query.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        try:
            gateway_payload = await _safe_get_gateway_config(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json(
            {
                "gateway": gateway,
                "devices": devices_for_ui(gateway_payload),
            }
        )


class MyHOMEConfigurationDeviceView(HomeAssistantView):
    """Upsert a single configured device from panel UI."""

    url = "/api/bticino_myhome/configuration/device"
    name = "api:bticino_myhome:configuration:device"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = resolve_gateway_from_payload(
            configured_gateways,
            payload.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        platform = str(payload.get("platform") or "").strip().lower()
        if platform not in CONFIG_PLATFORMS:
            return self.json_message(
                f"Invalid platform `{platform}`.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        address, device, device_error = device_from_payload(platform, payload)
        if device_error:
            return self.json_message(device_error, status_code=HTTPStatus.BAD_REQUEST)

        provided_key = payload.get("key")
        raw_key = (
            str(provided_key).strip()
            if provided_key is not None and str(provided_key).strip()
            else f"manual_{platform}_{address}"
        )
        key = sanitize_key(raw_key)

        try:
            gateway_payload = await _safe_get_gateway_config(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
        platform_payload = gateway_payload.setdefault(platform, {})
        if not isinstance(platform_payload, dict):
            platform_payload = {}
            gateway_payload[platform] = platform_payload
        platform_payload[key] = device

        try:
            config_schema({gateway: gateway_payload})
        except Exception as err:  # pylint: disable=broad-except
            return self.json_message(
                f"Invalid configuration: {err}",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            await _safe_set_gateway_config(hass, gateway, gateway_payload)
            await _safe_reload_gateway_entry(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json(
            {
                "ok": True,
                "gateway": gateway,
                "platform": platform,
                "key": key,
                "devices": devices_for_ui(gateway_payload),
            }
        )


class MyHOMEConfigurationDeleteView(HomeAssistantView):
    """Delete a configured device from panel UI."""

    url = "/api/bticino_myhome/configuration/device_delete"
    name = "api:bticino_myhome:configuration:device_delete"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = resolve_gateway_from_payload(
            configured_gateways,
            payload.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        platform = str(payload.get("platform") or "").strip().lower()
        key = str(payload.get("key") or "").strip()
        if platform not in CONFIG_PLATFORMS or not key:
            return self.json_message(
                "Both `platform` and `key` are required.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            gateway_payload = await _safe_get_gateway_config(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
        platform_payload = gateway_payload.get(platform, {})
        if isinstance(platform_payload, dict):
            platform_payload.pop(key, None)
            if len(platform_payload) == 0:
                gateway_payload.pop(platform, None)

        try:
            await _safe_set_gateway_config(hass, gateway, gateway_payload)
            await _safe_reload_gateway_entry(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json({"ok": True, "gateway": gateway, "devices": devices_for_ui(gateway_payload)})


class MyHOMEConfigurationImportDiscoveryView(HomeAssistantView):
    """Import discovered devices into persistent configuration."""

    url = "/api/bticino_myhome/configuration/import_discovery"
    name = "api:bticino_myhome:configuration:import_discovery"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = resolve_gateway_from_payload(
            configured_gateways,
            payload.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        try:
            gateway_payload = await _safe_get_gateway_config(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

        imported = {"light": 0, "cover": 0, "climate": 0, "power": 0}

        for where in payload.get("lights", []) or []:
            where = str(where)
            light_payload = gateway_payload.get(LIGHT_PLATFORM)
            if not isinstance(light_payload, dict):
                light_payload = {}
                gateway_payload[LIGHT_PLATFORM] = light_payload
            key = sanitize_key(f"discovered_light_{where}")
            if key not in light_payload:
                light_payload[key] = {"where": where, "name": f"Light {where}", "dimmable": False}
                imported["light"] += 1

        for where in payload.get("covers", []) or []:
            where = str(where)
            cover_payload = gateway_payload.get(COVER_PLATFORM)
            if not isinstance(cover_payload, dict):
                cover_payload = {}
                gateway_payload[COVER_PLATFORM] = cover_payload
            key = sanitize_key(f"discovered_cover_{where}")
            if key not in cover_payload:
                cover_payload[key] = {"where": where, "name": f"Cover {where}"}
                imported["cover"] += 1

        for zone in payload.get("climates", []) or []:
            zone = str(zone)
            climate_payload = gateway_payload.get(CLIMATE_PLATFORM)
            if not isinstance(climate_payload, dict):
                climate_payload = {}
                gateway_payload[CLIMATE_PLATFORM] = climate_payload
            key = sanitize_key(f"discovered_climate_{zone}")
            if key not in climate_payload:
                climate_payload[key] = {
                    "zone": zone,
                    "name": f"Climate {zone}",
                    "heat": True,
                    "cool": True,
                    "fan": True,
                    "standalone": True,
                }
                imported["climate"] += 1

        for where in payload.get("powers", []) or []:
            where = str(where)
            sensor_payload = gateway_payload.get(SENSOR_PLATFORM)
            if not isinstance(sensor_payload, dict):
                sensor_payload = {}
                gateway_payload[SENSOR_PLATFORM] = sensor_payload
            key = sanitize_key(f"discovered_power_{where}")
            if key not in sensor_payload:
                sensor_payload[key] = {"where": where, "name": f"Power+Energy {where}", "class": "power_energy"}
                imported["power"] += 1

        # Keep payload schema-compliant: empty platform sections are invalid.
        for platform in CONFIG_PLATFORMS:
            platform_payload = gateway_payload.get(platform)
            if isinstance(platform_payload, dict) and len(platform_payload) == 0:
                gateway_payload.pop(platform, None)

        try:
            config_schema({gateway: gateway_payload})
        except Exception as err:  # pylint: disable=broad-except
            return self.json_message(
                f"Invalid configuration: {err}",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            await _safe_set_gateway_config(hass, gateway, gateway_payload)
            await _safe_reload_gateway_entry(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

        return self.json(
            {
                "ok": True,
                "gateway": gateway,
                "imported": imported,
                "devices": devices_for_ui(gateway_payload),
            }
        )


class MyHOMEDiscoveryView(HomeAssistantView):
    """Run MyHOME discovery from the web panel."""

    url = "/api/bticino_myhome/discovery"
    name = "api:bticino_myhome:discovery"
    requires_auth = True

    async def post(self, request):
        """Handle discovery requests."""
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        if not configured_gateways:
            return self.json_message(
                "No MyHOME gateways are configured.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        requested_gateway = payload.get("gateway")
        if requested_gateway is None:
            gateway = next(iter(configured_gateways.keys()))
        else:
            formatted_gateway = format_mac(requested_gateway)
            if formatted_gateway is None:
                return self.json_message(
                    f"Invalid gateway `{requested_gateway}`.",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            gateway = formatted_gateway

        gateway_data = configured_gateways.get(gateway)
        if gateway_data is None:
            return self.json_message(
                f"Gateway `{gateway}` was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        gateway_handler = gateway_data[CONF_ENTITY]
        scan_lights = to_bool(payload.get("scan_lights"), True)
        scan_covers = to_bool(payload.get("scan_covers"), True)
        scan_climate = to_bool(payload.get("scan_climate"), True)
        scan_power = to_bool(payload.get("scan_power"), True)
        area_start = to_int(payload.get("area_start"), DISCOVERY_DEFAULT_AREA_START)
        area_end = to_int(payload.get("area_end"), DISCOVERY_DEFAULT_AREA_END)
        point_start = to_int(payload.get("point_start"), DISCOVERY_DEFAULT_POINT_START)
        point_end = to_int(payload.get("point_end"), DISCOVERY_DEFAULT_POINT_END)
        duration = to_int(payload.get("duration"), DISCOVERY_DEFAULT_DURATION)

        LOGGER.info(
            "%s Discovery requested via web panel (lights=%s, covers=%s, climate=%s, power=%s, area=%s-%s, point=%s-%s, duration=%ss).",
            gateway_handler.log_id,
            scan_lights,
            scan_covers,
            scan_climate,
            scan_power,
            area_start,
            area_end,
            point_start,
            point_end,
            duration,
        )

        try:
            results = await gateway_handler.discover_devices(
                scan_lights=scan_lights,
                scan_covers=scan_covers,
                scan_climate=scan_climate,
                scan_power=scan_power,
                area_start=area_start,
                area_end=area_end,
                point_start=point_start,
                point_end=point_end,
                duration=duration,
            )
        except RuntimeError as runtime_error:
            return self.json_message(
                str(runtime_error),
                status_code=HTTPStatus.CONFLICT,
            )
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.exception(
                "%s Discovery failed from web panel: %s",
                gateway_handler.log_id,
                err,
            )
            return self.json_message(
                "Unexpected discovery failure.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        light_results = results.get("light", [])
        cover_results = results.get("cover", [])
        climate_results = [
            str(item)
            for item in results.get("climate", [])
            if is_valid_discovery_climate(str(item))
        ]
        power_results = results.get("power", [])
        configured = configured_discovery_endpoints(hass, gateway)
        mapped_light, new_light = mapped_results(light_results, configured["light"])
        mapped_cover, new_cover = mapped_results(cover_results, configured["cover"])
        mapped_climate, new_climate = mapped_results(
            climate_results,
            configured["climate"],
        )
        mapped_power, new_power = mapped_results(power_results, configured["power"])
        return self.json(
            {
                "kind": "active_discovery",
                "gateway": gateway,
                "light": [str(item) for item in light_results],
                "cover": [str(item) for item in cover_results],
                "climate": climate_results,
                "power": [str(item) for item in power_results],
                "mapped_light": mapped_light,
                "mapped_cover": mapped_cover,
                "mapped_climate": mapped_climate,
                "mapped_power": mapped_power,
                "new_light": new_light,
                "new_cover": new_cover,
                "new_climate": new_climate,
                "new_power": new_power,
                "total_light": len(light_results),
                "total_cover": len(cover_results),
                "total_climate": len(climate_results),
                "total_power": len(power_results),
                "snippet": build_discovery_snippet(
                    [str(item) for item in light_results],
                    [str(item) for item in cover_results],
                    [str(item) for item in climate_results],
                    [str(item) for item in power_results],
                    {
                        "light": set(mapped_light),
                        "cover": set(mapped_cover),
                        "climate": set(mapped_climate),
                        "power": set(mapped_power),
                    },
                ),
            }
        )


class MyHOMEImportDailyEnergyHistoryView(HomeAssistantView):
    """Import daily energy/water history into HA long-term statistics."""

    url = "/api/bticino_myhome/energy/import_daily"
    name = "api:bticino_myhome:energy:import_daily"
    requires_auth = True

    _active_gateways: set[str] = set()

    @staticmethod
    def _target_entity_suffix(sensor_class: str) -> str:
        """Return the entity unique-id suffix for total counters."""
        return "total-water" if sensor_class == "water" else "total-energy"

    @staticmethod
    def _resolve_entity_statistic_id(hass, gateway: str, sensor_key: str, sensor_class: str, where: str = None) -> str | None:
        """Resolve the recorder statistic id used by the HA entity.
        
        Try current schema first, then fall back to old schema using WHO and WHERE.
        """
        entity_registry = er.async_get(hass)
        suffix = MyHOMEImportDailyEnergyHistoryView._target_entity_suffix(sensor_class)
        
        # Try current schema: {gateway}-{sensor_key}-{suffix}
        unique_id = f"{gateway}-{sensor_key}-{suffix}"
        entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            return entity_id
        
        # Fall back to old schema: {gateway}-{who}-{where}-{suffix}
        # WHO is typically "18" for power/energy sensors, "16" for water
        if where:
            who = "18" if sensor_class in ("power", "power_energy", "energy") else "16"
            old_unique_id = f"{gateway}-{who}-{where}-{suffix}"
            entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, old_unique_id)
            if entity_id:
                return entity_id
        
        return None

    @staticmethod
    def _local_tzinfo(hass) -> Any:
        """Resolve the timezone HA is configured with (falls back to UTC).

        The OpenWebNet protocol's daily_consumption message (dimension 511)
        reports a calendar day with no timezone marker at all - it reflects
        whichever local clock the gateway itself is configured with (F454,
        MH200N, or any other OWN central unit). This is a protocol-wide
        characteristic, not specific to one gateway model. HA's own
        configured time_zone is the closest reliable proxy for "the user's
        local time" without requiring extra configuration, and matches the
        gateway's clock in the vast majority of installations (same
        country/region for both).
        """
        time_zone_name = getattr(hass.config, "time_zone", None)
        if time_zone_name:
            try:
                tz = dt_util.get_time_zone(time_zone_name)
            except Exception:  # pylint: disable=broad-except
                tz = None
            if tz is not None:
                return tz
        return dt_util.DEFAULT_TIME_ZONE or timezone.utc

    @staticmethod
    def _day_end_utc(day: date, tz: Any) -> datetime:
        """Return the UTC timestamp for the end of a local calendar day.

        Our reconstructed point represents "the meter's cumulative total
        once this day's consumption is complete", a value only known at
        the very start of the *next* local calendar day - not this day's
        own local midnight. Converting to UTC here (rather than treating
        local midnight as if it were UTC midnight) avoids a day-shift and
        several-hour offset that previously misplaced imported points
        against real hourly statistics.
        """
        local_next_day_start = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
        return local_next_day_start.astimezone(timezone.utc)

    @staticmethod
    def _local_hour_utc(day: date, hour: int, tz: Any) -> datetime:
        """Return the UTC timestamp of a given local hour of a local day.

        OWN hourly consumption (dimension 511) is reported against the
        gateway's own local clock, while Home Assistant stores statistics in
        UTC-aligned hour buckets. Converting here makes each imported hourly
        point land on exactly the same bucket a real hourly statistic would
        occupy for that hour.
        """
        local_start = datetime.combine(day, time.min, tzinfo=tz) + timedelta(hours=hour)
        return local_start.astimezone(timezone.utc)

    @staticmethod
    def _load_hourly_daily_totals(
        hass,
        recorder_statistics,
        statistic_id: str,
        start_day: date,
        end_day: date,
        tz: Any,
    ) -> tuple[dict[date, dict[str, float]], set[datetime]]:
        """Return per-day totals and occupied slots inferred from hourly sums.

        The second element is the set of exact UTC timestamps that already
        hold a real statistic row, used to avoid overwriting genuine data
        with reconstructed history.
        """
        stats_during_period = getattr(recorder_statistics, "statistics_during_period", None)
        if stats_during_period is None:
            return {}, set()

        # Query with a one-day buffer on each side: local calendar days don't
        # align with UTC day boundaries once a timezone offset is applied, so
        # widening the UTC window guarantees every real hourly row belonging
        # to a local day inside [start_day, end_day] is actually returned.
        start_dt = datetime.combine(start_day, time.min, tzinfo=tz).astimezone(timezone.utc) - timedelta(days=1)
        end_dt = datetime.combine(end_day, time.min, tzinfo=tz).astimezone(timezone.utc) + timedelta(days=2)

        try:
            data = stats_during_period(
                hass,
                start_time=start_dt,
                end_time=end_dt,
                statistic_ids=[statistic_id],
                period="hour",
                units=None,
                types={"sum"},
            )
        except TypeError:
            try:
                data = stats_during_period(
                    hass,
                    start_dt,
                    end_dt,
                    [statistic_id],
                    "hour",
                    None,
                    {"sum"},
                )
            except Exception:  # pylint: disable=broad-except
                return {}, set()
        except Exception:  # pylint: disable=broad-except
            return {}, set()

        rows = data.get(statistic_id) if isinstance(data, dict) else None
        if not rows:
            return {}, set()

        by_day: dict[date, list[float]] = {}
        midnight_occupied: dict[date, bool] = {}
        occupied_starts: set[datetime] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_start = row.get("start")
            row_sum = row.get("sum")
            if row_start is None or row_sum is None:
                continue
            try:
                if isinstance(row_start, (int, float)):
                    row_start = datetime.fromtimestamp(float(row_start), tz=timezone.utc)
                occupied_starts.add(row_start.astimezone(timezone.utc))
                # Real hourly statistics must be attributed to their LOCAL
                # calendar day (matching the gateway's own daily_consumption
                # reporting), not the UTC date of their storage timestamp.
                local_start = row_start.astimezone(tz)
                day = local_start.date()
                by_day.setdefault(day, []).append(float(row_sum))
                if local_start.time() == time.min:
                    # A real row sitting exactly at local midnight is the end
                    # of the *previous* local day (see _day_end_utc): that is
                    # the exact timestamp our own import would write to for
                    # that previous day, so flag a collision on it, not on
                    # the day this row's own local date falls into.
                    midnight_occupied[day - timedelta(days=1)] = True
            except Exception:  # pylint: disable=broad-except
                continue

        result: dict[date, dict[str, float]] = {}
        # Iterate the union of both keysets: "midnight_occupied" is recorded
        # against the PREVIOUS day (the day our own import would collide on),
        # which may not itself have any other real hourly point (e.g. the
        # very first hour of live collection landing exactly on local
        # midnight) and therefore may be absent from "by_day".
        for day in set(by_day) | set(midnight_occupied):
            sums = by_day.get(day)
            if sums:
                # A day is included here whenever it has at least one existing
                # hourly point, purely to feed the cumulative-offset alignment
                # estimate below (subject to _is_close_daily_value's tolerance
                # check, which naturally rejects unrepresentative single-hour
                # totals). Whether a day is safe to *import into* is a separate
                # question decided by "midnight_occupied" below: our own import
                # always writes a single point at the end of the local day
                # (converted to UTC), and HA's hourly statistics compiler always
                # aligns real hourly rows to exact hour boundaries, so checking
                # for an existing row at exactly that timestamp reliably detects
                # a real collision without needing any time-window tolerance.
                min_sum = min(sums)
                max_sum = max(sums)
                if max_sum < min_sum:
                    continue
                result[day] = {
                    "value": max_sum - min_sum,
                    "end_sum": max_sum,
                    "points": float(len(sums)),
                    "midnight_occupied": 1.0 if midnight_occupied.get(day) else 0.0,
                }
            else:
                # No real hourly point is itself attributed to this day, but
                # a real point exists at exactly the timestamp our import
                # would write to for it - still a genuine collision to skip,
                # even without a "value"/"end_sum" to offer for alignment.
                result[day] = {
                    "value": 0.0,
                    "end_sum": None,
                    "points": 0.0,
                    "midnight_occupied": 1.0,
                }
        return result, occupied_starts

    @staticmethod
    def _is_close_daily_value(imported_value: float, hourly_value: float) -> bool:
        """Return True when two daily values are close enough to prefer hourly detail."""
        abs_tolerance = max(1.0, imported_value * 0.10)
        return abs(imported_value - hourly_value) <= abs_tolerance

    @staticmethod
    def _validate_recorder_payload(
        *,
        entity_statistic_id: str | None,
        metadata,
        statistics_rows,
    ) -> str | None:
        """Validate recorder payload before enqueueing import jobs."""
        statistic_id = metadata["statistic_id"]
        source = metadata["source"]

        if entity_statistic_id:
            if ":" in statistic_id:
                return "entity statistic_id must not contain ':'"
            if source != "recorder":
                return "entity statistic_id requires source='recorder'"
        else:
            if ":" not in statistic_id:
                return "external statistic_id must contain ':'"
            domain, _object_id = statistic_id.split(":", 1)
            if source != domain:
                return f"external source '{source}' must match statistic domain '{domain}'"

        for statistic in statistics_rows:
            start = statistic["start"]
            if start.minute != 0 or start.second != 0 or start.microsecond != 0:
                return f"invalid start timestamp {start.isoformat()} (must be top of hour)"

        return None

    @staticmethod
    def _find_first_existing_sum_from(
        hass,
        recorder_statistics,
        statistic_id: str,
        start_at: datetime,
    ) -> dict[str, Any] | None:
        """Find first existing sum row at or after start_at for a statistic."""
        stats_during_period = getattr(recorder_statistics, "statistics_during_period", None)
        if stats_during_period is None:
            return None

        try:
            data = stats_during_period(
                hass,
                start_time=start_at,
                end_time=None,
                statistic_ids=[statistic_id],
                period="hour",
                units=None,
                types={"sum"},
            )
        except TypeError:
            try:
                data = stats_during_period(
                    hass,
                    start_at,
                    None,
                    [statistic_id],
                    "hour",
                    None,
                    {"sum"},
                )
            except Exception:  # pylint: disable=broad-except
                return None
        except Exception:  # pylint: disable=broad-except
            return None

        rows = data.get(statistic_id) if isinstance(data, dict) else None
        if not rows:
            return None

        best_start: datetime | None = None
        best_sum: float | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_start = row.get("start")
            row_sum = row.get("sum")
            if row_start is None or row_sum is None:
                continue
            try:
                if isinstance(row_start, (int, float)):
                    row_start = datetime.fromtimestamp(float(row_start), tz=timezone.utc)
                row_sum = float(row_sum)
            except Exception:  # pylint: disable=broad-except
                continue

            if best_start is None or row_start < best_start:
                best_start = row_start
                best_sum = row_sum

        if best_start is None or best_sum is None:
            return None

        return {"start": best_start, "sum": best_sum}

    @staticmethod
    def _persisted_statistics_count(
        hass,
        recorder_statistics,
        statistic_id: str,
        statistics_rows,
    ) -> int:
        """Count imported rows that Recorder persisted with their expected state."""
        if not statistics_rows:
            return 0

        start_at = min(row["start"] for row in statistics_rows)
        end_at = max(row["start"] for row in statistics_rows) + timedelta(hours=1)
        try:
            data = recorder_statistics.statistics_during_period(
                hass,
                start_time=start_at,
                end_time=end_at,
                statistic_ids=[statistic_id],
                period="hour",
                units=None,
                types={"state"},
            )
        except TypeError:
            data = recorder_statistics.statistics_during_period(
                hass,
                start_at,
                end_at,
                [statistic_id],
                "hour",
                None,
                {"state"},
            )
        persisted_rows = data.get(statistic_id) if isinstance(data, dict) else None
        if not persisted_rows:
            return 0

        expected_by_start = {
            row["start"]: float(row["state"])
            for row in statistics_rows
        }
        matched_starts: set[datetime] = set()
        for row in persisted_rows:
            if not isinstance(row, dict):
                continue
            row_start = row.get("start")
            row_state = row.get("state")
            if isinstance(row_start, (int, float)):
                row_start = datetime.fromtimestamp(float(row_start), tz=timezone.utc)
            if row_start not in expected_by_start or row_state is None:
                continue
            if isclose(float(row_state), expected_by_start[row_start], rel_tol=1e-9, abs_tol=1e-9):
                matched_starts.add(row_start)
        return len(matched_starts)

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = resolve_gateway_from_payload(
            configured_gateways,
            payload.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        gateway_data = configured_gateways.get(gateway)
        if gateway_data is None:
            return self.json_message(
                f"Gateway `{gateway}` was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        try:
            from homeassistant.components.recorder import get_instance as recorder_get_instance
            from homeassistant.components.recorder import statistics as recorder_statistics
            from homeassistant.components.recorder.models import (
                StatisticData,
                StatisticMeanType,
                StatisticMetaData,
            )
        except Exception as err:  # pylint: disable=broad-except
            return self.json_message(
                f"Recorder statistics API unavailable: {err}",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        add_external_stats = getattr(recorder_statistics, "async_add_external_statistics", None)
        add_imported_stats = getattr(recorder_statistics, "async_import_statistics", None)
        recorder_instance = recorder_get_instance(hass)
        if add_external_stats is None:
            return self.json_message(
                "Recorder function async_add_external_statistics is not available.",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        if gateway in self._active_gateways:
            return self.json_message(
                "Un import est déjà en cours pour cette gateway.",
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
            )

        months_back = to_int(payload.get("months_back"), 24)
        months_back = max(1, min(24, months_back))
        # Pre-checked by default: protects existing real hourly statistics
        # from being collided with/overwritten by the coarse daily
        # reconstruction. Unchecking it forces the import to write every
        # requested day regardless of existing hourly data (previous
        # "overwrite" behavior).
        dont_override_hourly = to_bool(payload.get("dont_override_hourly"), True)
        allow_external_fallback = to_bool(payload.get("allow_external_fallback"), False)
        # Hourly detail (OWN dimension 511) is far more accurate than the
        # daily reconstruction because each point lands on the exact hour
        # bucket Home Assistant uses for real statistics. The gateway only
        # keeps ~12 months at that granularity (its frames carry no year), so
        # older days still come from daily history.
        use_hourly_detail = to_bool(payload.get("use_hourly_detail"), True)
        hourly_days_back = to_int(payload.get("hourly_days_back"), 365)
        hourly_days_back = max(0, min(365, hourly_days_back))
        query_delay_ms = to_int(payload.get("query_delay_ms"), 200)
        query_delay_ms = max(0, min(2000, query_delay_ms))
        query_delay = query_delay_ms / 1000.0
        sensor_key_filter = str(payload.get("sensor_key") or "").strip()

        try:
            gateway_payload = await _safe_get_gateway_config(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
        sensor_payload = gateway_payload.get(SENSOR_PLATFORM)
        if not isinstance(sensor_payload, dict) or len(sensor_payload) == 0:
            return self.json_message(
                "No configured sensors found for this gateway.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        targets: list[dict[str, Any]] = []
        for _key, device in sensor_payload.items():
            if not isinstance(device, dict):
                continue
            if sensor_key_filter and _key != sensor_key_filter:
                continue
            sensor_class = str(device.get("class") or "").strip().lower()
            if sensor_class not in ("power", "power_energy", "energy", "water"):
                continue
            where = str(device.get("where") or "").strip()
            if not where:
                continue
            targets.append(
                {
                    "sensor_key": _key,
                    "where": where,
                    "name": str(device.get("name") or f"Sensor {where}"),
                    "class": sensor_class,
                    "unit_scale": str(device.get(CONF_UNIT_SCALE) or "base").strip().lower(),
                }
            )

        if len(targets) == 0:
            return self.json_message(
                "Aucun capteur power/energy/water trouvé pour cette clé.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        def _unit_for_sensor(sensor_class: str, unit_scale: str) -> str:
            if sensor_class == "water":
                return "m³" if unit_scale == "kilo" else "L"
            return "kWh" if unit_scale == "kilo" else "Wh"

        def _unit_class_for_sensor(sensor_class: str) -> str:
            if sensor_class == "water":
                return "volume"
            return "energy"

        gateway_handler = gateway_data[CONF_ENTITY]
        imported: list[dict[str, Any]] = []
        errors: list[str] = []
        persistence_checks: list[tuple[dict[str, Any], str, list[Any]]] = []

        self._active_gateways.add(gateway)
        try:
            for target in targets:
                where = target["where"]
                try:
                    rows = await gateway_handler.fetch_daily_history(
                        where=where,
                        months_back=months_back,
                        query_delay=query_delay,
                    )
                except Exception as err:  # pylint: disable=broad-except
                    errors.append(
                        f"{where}: failed to fetch gateway history ({type(err).__name__}: {err})"
                    )
                    continue

                hourly_rows: list[dict[str, Any]] = []
                if use_hourly_detail and hourly_days_back > 0:
                    try:
                        hourly_rows = await gateway_handler.fetch_hourly_history(
                            where=where,
                            days_back=min(hourly_days_back, months_back * 31),
                            query_delay=min(query_delay, 0.05),
                        )
                    except Exception as err:  # pylint: disable=broad-except
                        # Hourly detail is an accuracy improvement, not a
                        # requirement: fall back to daily-only rather than
                        # failing the whole import for this endpoint.
                        errors.append(
                            f"{where}: failed to fetch hourly detail, falling back to daily "
                            f"({type(err).__name__}: {err})"
                        )
                        hourly_rows = []

                if len(rows) == 0:
                    imported.append(
                        {
                            "sensor_key": target["sensor_key"],
                            "where": where,
                            "class": target["class"],
                            "rows": 0,
                            "statistic_id": None,
                        }
                    )
                    continue

                entity_statistic_id = self._resolve_entity_statistic_id(
                    hass,
                    gateway,
                    target["sensor_key"],
                    target["class"],
                    target["where"],
                )
                statistic_suffix = sanitize_key(f"daily_{gateway}_{target['class']}_{where}")
                fallback_statistic_id = f"{DOMAIN}:{statistic_suffix}"
                if entity_statistic_id is None and not allow_external_fallback:
                    errors.append(
                        f"{where}: entity statistic id not found for sensor key "
                        f"'{target['sensor_key']}' (expected unique_id suffix "
                        f"'{self._target_entity_suffix(target['class'])}'). Import skipped."
                    )
                    imported.append(
                        {
                            "sensor_key": target["sensor_key"],
                            "where": where,
                            "class": target["class"],
                            "rows": 0,
                            "statistic_id": None,
                            "entity_statistic_id": None,
                            "fallback_statistic_id": fallback_statistic_id,
                        }
                    )
                    continue
                statistic_id = entity_statistic_id or fallback_statistic_id
                unit = _unit_for_sensor(target["class"], target["unit_scale"])

                # Non-destructive strategy: we upsert rows for imported days only.
                # This preserves any older rows outside the imported window.
                if not dont_override_hourly:
                    LOGGER.debug(
                        "%s dont_override_hourly disabled for %s: hourly-collision "
                        "guards are skipped and every requested day is imported.",
                        gateway_handler.log_id,
                        statistic_id,
                    )

                # OWN daily_consumption messages carry no timezone marker -
                # the gateway reports the calendar day of its own local
                # clock. HA's configured time_zone is used as the reliable
                # local-time reference for all day-boundary math below.
                local_tz = self._local_tzinfo(hass)

                metadata = StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_mean=False,
                    has_sum=True,
                    name=f"{target['name']} daily import",
                    source="recorder" if entity_statistic_id else DOMAIN,
                    statistic_id=statistic_id,
                    unit_class=_unit_class_for_sensor(target["class"]),
                    unit_of_measurement=unit,
                )

                today = dt_util.now(local_tz).date()
                source_rows = sorted(rows, key=lambda item: item["date"])
                filtered_rows = [row for row in source_rows if row["date"] < today]

                # Hourly detail, indexed by local day, takes precedence over
                # that day's single daily value whenever it is available.
                hourly_by_day: dict[date, dict[int, float]] = {}
                for hourly_row in hourly_rows:
                    hourly_day_date = hourly_row.get("date")
                    if hourly_day_date is None or hourly_day_date >= today:
                        continue
                    hour = int(hourly_row.get("hour", -1))
                    if not 0 <= hour <= 23:
                        continue
                    hourly_by_day.setdefault(hourly_day_date, {})[hour] = float(
                        hourly_row.get("value", 0)
                    )

                skipped_partial_days = len(source_rows) - len(filtered_rows)
                skipped_hourly_days = 0
                skipped_zero_days = 0
                skipped_partial_hourly_days = 0
                hourly_detail_days = 0

                if filtered_rows:
                    first_day = filtered_rows[0]["date"]
                    last_day = filtered_rows[-1]["date"]
                    try:
                        (
                            hourly_day_totals,
                            occupied_starts,
                        ) = await recorder_instance.async_add_executor_job(
                            self._load_hourly_daily_totals,
                            hass,
                            recorder_statistics,
                            statistic_id,
                            first_day,
                            last_day,
                            local_tz,
                        )
                    except Exception as err:  # pylint: disable=broad-except
                        errors.append(
                            f"{where}: failed to read existing hourly statistics ({type(err).__name__}: {err})"
                        )
                        hourly_day_totals = {}
                        occupied_starts = set()
                else:
                    hourly_day_totals = {}
                    occupied_starts = set()

                scale = 1000.0 if target["unit_scale"] == "kilo" else 1.0

                # Every point is a consumption delta stamped with the exact UTC
                # instant it belongs to: one point per hour when hourly detail
                # is available, otherwise a single end-of-day point.
                rows_to_import: list[tuple[datetime, float]] = []
                day_values: list[tuple[date, float]] = []
                cumulative_at_day_end: dict[date, float] = {}
                running_imported_total = 0.0

                for row in filtered_rows:
                    day = row["date"]
                    value = float(row["value"]) / scale
                    if isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-9):
                        # A zero daily total means the gateway has no data for
                        # that day rather than genuinely zero consumption.
                        skipped_zero_days += 1
                        continue

                    day_hours = hourly_by_day.get(day)
                    if day_hours and len(day_hours) == 24:
                        hourly_detail_days += 1
                        day_points = [
                            (
                                self._local_hour_utc(day, hour, local_tz),
                                day_hours[hour] / scale,
                            )
                            for hour in sorted(day_hours)
                        ]
                        # Trust the daily total as the day's reference value:
                        # it is what the alignment tolerance check compares
                        # against, and both sources agree on real hardware.
                        day_values.append((day, sum(v for _start, v in day_points)))
                    else:
                        # Only complete days (all 24 hours retrieved) are
                        # imported at hourly detail. A truncated day would both
                        # under-count that day's energy and, on a re-import,
                        # leave its missing hours carrying a previous run's
                        # cumulative offset - a day-wide step in the graph.
                        # The single end-of-day point is always consistent.
                        if day_hours:
                            skipped_partial_hourly_days += 1
                        day_points = [(self._day_end_utc(day, local_tz), value)]
                        day_values.append((day, value))

                    for start_at, delta in day_points:
                        running_imported_total += delta
                        # Real statistics always win: HA aligns hourly rows to
                        # exact hour boundaries, and so do our imported points,
                        # so an exact timestamp match is a genuine collision.
                        if dont_override_hourly and start_at in occupied_starts:
                            skipped_hourly_days += 1
                            continue
                        rows_to_import.append((start_at, running_imported_total))

                    cumulative_at_day_end[day] = running_imported_total

                sum_alignment_offset = 0.0
                sum_aligned_to_existing = False

                if entity_statistic_id and len(day_values) > 0:
                    offset_candidates: list[float] = []
                    for day, value in day_values:
                        hourly_day = hourly_day_totals.get(day)
                        if hourly_day is None:
                            continue
                        # A day's existing hourly total is only used as an
                        # anchor for the cumulative-offset alignment when it
                        # closely matches our reconstructed value (tolerance
                        # check below). This naturally rejects unrepresentative
                        # partial-day totals (e.g. a boundary day where live
                        # collection just started) without any arbitrary
                        # minimum-point-count threshold. Like the skip guard
                        # above, this closeness filter only applies when
                        # dont_override_hourly is active; when disabled, any
                        # existing hourly total is trusted as-is.
                        if dont_override_hourly and not self._is_close_daily_value(
                            imported_value=value,
                            hourly_value=float(hourly_day["value"]),
                        ):
                            continue
                        end_sum = hourly_day.get("end_sum")
                        imported_cumulative = cumulative_at_day_end.get(day)
                        if end_sum is None or imported_cumulative is None:
                            continue
                        offset_candidates.append(float(end_sum) - float(imported_cumulative))

                    if len(offset_candidates) > 0:
                        sorted_candidates = sorted(offset_candidates)
                        middle = len(sorted_candidates) // 2
                        if len(sorted_candidates) % 2 == 0:
                            sum_alignment_offset = (
                                sorted_candidates[middle - 1] + sorted_candidates[middle]
                            ) / 2.0
                        else:
                            sum_alignment_offset = sorted_candidates[middle]
                        sum_aligned_to_existing = True
                    elif len(rows_to_import) > 0:
                        # Fallback when no reliable overlap anchor exists.
                        first_import_start = rows_to_import[0][0]
                        try:
                            first_existing_sum = await recorder_instance.async_add_executor_job(
                                self._find_first_existing_sum_from,
                                hass,
                                recorder_statistics,
                                statistic_id,
                                first_import_start,
                            )
                        except Exception as err:  # pylint: disable=broad-except
                            errors.append(
                                f"{where}: failed to read first existing sum ({type(err).__name__}: {err})"
                            )
                            first_existing_sum = None

                        if first_existing_sum is not None:
                            first_existing_start = first_existing_sum["start"]
                            first_existing_value = float(first_existing_sum["sum"])
                            last_import_start = rows_to_import[-1][0]
                            if first_existing_start > last_import_start:
                                imported_total = running_imported_total
                                sum_alignment_offset = first_existing_value - imported_total
                                sum_aligned_to_existing = True
                        else:
                            # No recorder statistics at all (before or after the
                            # imported window): anchor on the entity's current
                            # live reading and reconstruct history backward from
                            # "today's cumulative total minus each imported day's
                            # consumption" instead of starting the series near 0.
                            live_state = hass.states.get(entity_statistic_id)
                            live_value: float | None = None
                            if live_state is not None:
                                try:
                                    live_value = float(live_state.state)
                                except (TypeError, ValueError):
                                    live_value = None
                            if live_value is not None:
                                sum_alignment_offset = live_value - running_imported_total
                                sum_aligned_to_existing = True

                # The written "state" must represent the reconstructed cumulative
                # meter reading (matching how the live entity's real hourly
                # statistics are stored), not the raw consumption delta. Writing
                # the delta as "state" creates a visible drop/spike against the
                # surrounding real hourly readings.
                statistics_rows = []
                for start_at, cumulative in rows_to_import:
                    running_sum = sum_alignment_offset + cumulative
                    statistics_rows.append(
                        StatisticData(
                            start=start_at,
                            state=running_sum,
                            sum=running_sum,
                        )
                    )

                if len(statistics_rows) == 0:
                    imported.append(
                        {
                            "sensor_key": target["sensor_key"],
                            "where": where,
                            "class": target["class"],
                            "rows": 0,
                            "statistic_id": statistic_id,
                            "entity_statistic_id": entity_statistic_id,
                            "fallback_statistic_id": fallback_statistic_id,
                            "skipped_partial_days": skipped_partial_days,
                            "skipped_hourly_days": skipped_hourly_days,
                            "skipped_zero_days": skipped_zero_days,
                            "skipped_partial_hourly_days": skipped_partial_hourly_days,
                            "hourly_detail_days": hourly_detail_days,
                            "sum_aligned_to_existing": sum_aligned_to_existing,
                            "sum_alignment_offset": round(sum_alignment_offset, 6),
                        }
                    )
                    continue

                try:
                    validation_error = self._validate_recorder_payload(
                        entity_statistic_id=entity_statistic_id,
                        metadata=metadata,
                        statistics_rows=statistics_rows,
                    )
                    if validation_error is not None:
                        raise ValueError(validation_error)

                    if entity_statistic_id:
                        if add_imported_stats is None:
                            raise RuntimeError(
                                "Recorder function async_import_statistics is not available for entity statistics."
                            )
                        add_imported_stats(hass, metadata, statistics_rows)
                    else:
                        add_external_stats(hass, metadata, statistics_rows)
                    imported_result = {
                        "sensor_key": target["sensor_key"],
                        "where": where,
                        "class": target["class"],
                        "rows": len(statistics_rows),
                        "statistic_id": statistic_id,
                        "entity_statistic_id": entity_statistic_id,
                        "fallback_statistic_id": fallback_statistic_id,
                        "skipped_partial_days": skipped_partial_days,
                        "skipped_hourly_days": skipped_hourly_days,
                        "skipped_zero_days": skipped_zero_days,
                        "skipped_partial_hourly_days": skipped_partial_hourly_days,
                        "hourly_detail_days": hourly_detail_days,
                        "sum_aligned_to_existing": sum_aligned_to_existing,
                        "sum_alignment_offset": round(sum_alignment_offset, 6),
                    }
                    imported.append(imported_result)
                    persistence_checks.append(
                        (imported_result, statistic_id, statistics_rows)
                    )
                except Exception as err:  # pylint: disable=broad-except
                    errors.append(
                        f"{where}: failed to import statistics ({type(err).__name__}: {err})"
                    )

            if persistence_checks:
                # ImportStatisticsTask (queued by async_import_statistics() /
                # async_add_external_statistics()) is wrapped by Recorder's
                # @retryable_database_job: if the database is transiently busy
                # it returns False and *re-queues itself* to run again later
                # (see homeassistant/components/recorder/tasks.py). A single
                # async_block_till_done() call inserts one WaitTask sentinel at
                # the tail of the queue; if the import re-queues itself after
                # that sentinel was already enqueued, block_till_done() returns
                # before the retried import has actually run/committed,
                # producing a false-negative "Recorder persisted 0/N" error.
                #
                # A fixed number of drain cycles never fully rules this out
                # (a requeue can always land right after the last one), and
                # large imports (hundreds/thousands of rows) can legitimately
                # take a while to fully commit under load. Use exponential
                # backoff (1s, 2s, 4s, ...) instead, bounded by a total
                # verification budget, re-draining and re-checking on each
                # step until every row matches or the budget runs out.
                max_verify_seconds = 30.0

                for imported_result, statistic_id, statistics_rows in persistence_checks:
                    expected_rows = len(statistics_rows)
                    persisted_rows = 0
                    verification_error: Exception | None = None
                    elapsed = 0.0
                    delay = 1.0
                    while True:
                        await recorder_instance.async_block_till_done()
                        try:
                            persisted_rows = await recorder_instance.async_add_executor_job(
                                self._persisted_statistics_count,
                                hass,
                                recorder_statistics,
                                statistic_id,
                                statistics_rows,
                            )
                            verification_error = None
                        except Exception as err:  # pylint: disable=broad-except
                            verification_error = err
                            persisted_rows = 0

                        if verification_error is None and persisted_rows == expected_rows:
                            break
                        if elapsed >= max_verify_seconds:
                            break
                        sleep_for = min(delay, max_verify_seconds - elapsed)
                        await asyncio.sleep(sleep_for)
                        elapsed += sleep_for
                        delay = min(delay * 2, max_verify_seconds)

                    if verification_error is not None:
                        errors.append(
                            f"{imported_result['where']}: failed to verify persisted statistics "
                            f"({type(verification_error).__name__}: {verification_error})"
                        )
                        imported_result["rows"] = 0
                        continue

                    imported_result["persisted_rows"] = persisted_rows
                    if persisted_rows != expected_rows:
                        errors.append(
                            f"{imported_result['where']}: Recorder persisted "
                            f"{persisted_rows}/{expected_rows} statistics rows for {statistic_id}"
                        )
                        imported_result["rows"] = persisted_rows

            response_status = HTTPStatus.OK if len(errors) == 0 else HTTPStatus.INTERNAL_SERVER_ERROR
            return self.json(
                {
                    "ok": len(errors) == 0,
                    "gateway": gateway,
                    "months_back": months_back,
                    "dont_override_hourly": dont_override_hourly,
                    "allow_external_fallback": allow_external_fallback,
                    "query_delay_ms": query_delay_ms,
                    "imported": imported,
                    "errors": errors,
                },
                status_code=response_status,
            )
        finally:
            self._active_gateways.discard(gateway)


class MyHOMEDiscoveryByActivationView(HomeAssistantView):
    """Keep discovery-by-activation enabled from panel UI."""

    url = "/api/bticino_myhome/discovery_by_activation"
    name = "api:bticino_myhome:discovery_by_activation"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        if not configured_gateways:
            return self.json_message(
                "No MyHOME gateways are configured.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        requested_gateway = payload.get("gateway")
        if requested_gateway is None:
            gateway = next(iter(configured_gateways.keys()))
        else:
            gateway = format_mac(requested_gateway)
            if gateway is None:
                return self.json_message(
                    f"Invalid gateway `{requested_gateway}`.",
                    status_code=HTTPStatus.BAD_REQUEST,
                )

        gateway_data = configured_gateways.get(gateway)
        if gateway_data is None:
            return self.json_message(
                f"Gateway `{gateway}` was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        gateway_handler = gateway_data[CONF_ENTITY]
        gateway_handler.set_discovery_by_activation(True)

        return self.json(
            {
                "gateway": gateway,
                "enabled": gateway_handler.discovery_by_activation,
            }
        )


class MyHOMEActivationDiscoveryResultsView(HomeAssistantView):
    """Return activation discovery results from panel UI."""

    url = "/api/bticino_myhome/activation_discovery"
    name = "api:bticino_myhome:activation_discovery"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        if not configured_gateways:
            return self.json_message(
                "No MyHOME gateways are configured.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        requested_gateway = payload.get("gateway")
        if requested_gateway is None:
            gateway = next(iter(configured_gateways.keys()))
        else:
            gateway = format_mac(requested_gateway)
            if gateway is None:
                return self.json_message(
                    f"Invalid gateway `{requested_gateway}`.",
                    status_code=HTTPStatus.BAD_REQUEST,
                )

        gateway_data = configured_gateways.get(gateway)
        if gateway_data is None:
            return self.json_message(
                f"Gateway `{gateway}` was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        clear = to_bool(payload.get("clear"), False)
        gateway_handler = gateway_data[CONF_ENTITY]
        gateway_handler.set_discovery_by_activation(True)

        runtime_results = gateway_handler.get_activation_discovery_results(clear=False)
        try:
            stored_results = await _safe_get_activation_discovery_results(hass, gateway)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
        results = merge_discovery_results(runtime_results, stored_results)
        results["climate"] = [
            str(item)
            for item in results.get("climate", [])
            if is_valid_discovery_climate(str(item))
        ]

        if clear:
            gateway_handler.clear_activation_discovery_results()
            try:
                await _safe_clear_activation_discovery_results(hass, gateway)
            except RuntimeError as err:
                return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
            results = {kind: [] for kind in ("light", "cover", "climate", "power")}
        else:
            try:
                await _safe_set_activation_discovery_results(hass, gateway, results)
            except RuntimeError as err:
                return self.json_message(str(err), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

        light_results = results.get("light", [])
        cover_results = results.get("cover", [])
        climate_results = results.get("climate", [])
        power_results = results.get("power", [])
        configured = configured_discovery_endpoints(hass, gateway)
        mapped_light, new_light = mapped_results(light_results, configured["light"])
        mapped_cover, new_cover = mapped_results(cover_results, configured["cover"])
        mapped_climate, new_climate = mapped_results(
            climate_results,
            configured["climate"],
        )
        mapped_power, new_power = mapped_results(power_results, configured["power"])

        return self.json(
            {
                "kind": "activation_discovery",
                "gateway": gateway,
                "enabled": gateway_handler.discovery_by_activation,
                "light": [str(item) for item in light_results],
                "cover": [str(item) for item in cover_results],
                "climate": [str(item) for item in climate_results],
                "power": [str(item) for item in power_results],
                "mapped_light": mapped_light,
                "mapped_cover": mapped_cover,
                "mapped_climate": mapped_climate,
                "mapped_power": mapped_power,
                "new_light": new_light,
                "new_cover": new_cover,
                "new_climate": new_climate,
                "new_power": new_power,
                "total_light": len(light_results),
                "total_cover": len(cover_results),
                "total_climate": len(climate_results),
                "total_power": len(power_results),
                "snippet": build_discovery_snippet(
                    [str(item) for item in light_results],
                    [str(item) for item in cover_results],
                    [str(item) for item in climate_results],
                    [str(item) for item in power_results],
                    {
                        "light": set(mapped_light),
                        "cover": set(mapped_cover),
                        "climate": set(mapped_climate),
                        "power": set(mapped_power),
                    },
                ),
                "cleared": clear,
            }
        )


async def async_setup_web(hass) -> None:
    """Set up MyHOME web resources and register panel when needed."""
    runtime_data = _runtime_data(hass)

    if not runtime_data["api_registered"]:
        panel_directory = Path(__file__).parent / "frontend"
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(PANEL_STATIC_URL_PATH, str(panel_directory), False)]
            )
            hass.http.register_view(MyHOMEGatewaysView)
            hass.http.register_view(MyHOMEConfigurationView)
            hass.http.register_view(MyHOMEConfigurationDeviceView)
            hass.http.register_view(MyHOMEConfigurationDeleteView)
            hass.http.register_view(MyHOMEConfigurationImportDiscoveryView)
            hass.http.register_view(MyHOMEImportDailyEnergyHistoryView)
            hass.http.register_view(MyHOMEDiscoveryView)
            hass.http.register_view(MyHOMEDiscoveryByActivationView)
            hass.http.register_view(MyHOMEActivationDiscoveryResultsView)
        except Exception as err:  # pylint: disable=broad-except
            raise RuntimeError(
                f"Failed to register MyHOME web API/panel assets: {type(err).__name__}: {err}"
            ) from err
        runtime_data["api_registered"] = True

    runtime_data["entry_count"] += 1
    if runtime_data["panel_registered"]:
        return

    try:
        await panel_custom.async_register_panel(
            hass=hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_WEBCOMPONENT_NAME,
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            module_url=PANEL_MODULE_URL,
            require_admin=True,
        )
    except Exception as err:  # pylint: disable=broad-except
        raise RuntimeError(
            f"Failed to register MyHOME panel: {type(err).__name__}: {err}"
        ) from err
    runtime_data["panel_registered"] = True


def async_unload_web(hass) -> None:
    """Unload MyHOME panel when last entry is removed."""
    runtime_data = _runtime_data(hass)
    runtime_data["entry_count"] = max(runtime_data["entry_count"] - 1, 0)

    if runtime_data["entry_count"] != 0 or not runtime_data["panel_registered"]:
        return

    frontend.async_remove_panel(
        hass=hass,
        frontend_url_path=PANEL_URL_PATH,
        warn_if_unknown=False,
    )
    runtime_data["panel_registered"] = False
