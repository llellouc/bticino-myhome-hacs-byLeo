"""Web UI endpoints and panel registration for MyHOME discovery."""

from __future__ import annotations

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
    def _load_hourly_daily_totals(
        hass,
        recorder_statistics,
        statistic_id: str,
        start_day: date,
        end_day: date,
    ) -> dict[date, dict[str, float]]:
        """Return per-day totals inferred from hourly sums for a statistic."""
        stats_during_period = getattr(recorder_statistics, "statistics_during_period", None)
        if stats_during_period is None:
            return {}

        start_dt = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end_day, time.min, tzinfo=timezone.utc)

        try:
            data = stats_during_period(
                hass,
                start_time=start_dt,
                end_time=end_dt,
                statistic_ids=[statistic_id],
                period="hour",
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
                    False,
                )
            except Exception:  # pylint: disable=broad-except
                return {}
        except Exception:  # pylint: disable=broad-except
            return {}

        rows = data.get(statistic_id) if isinstance(data, dict) else None
        if not rows:
            return {}

        by_day: dict[date, list[float]] = {}
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
                day = row_start.date()
                by_day.setdefault(day, []).append(float(row_sum))
            except Exception:  # pylint: disable=broad-except
                continue

        result: dict[date, dict[str, float]] = {}
        for day, sums in by_day.items():
            if len(sums) < 3:
                # Too few points to reliably represent a detailed hourly day.
                continue
            min_sum = min(sums)
            max_sum = max(sums)
            if max_sum < min_sum:
                continue
            result[day] = {
                "value": max_sum - min_sum,
                "end_sum": max_sum,
                "points": float(len(sums)),
            }
        return result

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
                    False,
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
        overwrite = to_bool(payload.get("overwrite"), False)
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
                statistic_id = entity_statistic_id or fallback_statistic_id
                unit = _unit_for_sensor(target["class"], target["unit_scale"])

                # Non-destructive strategy: we upsert rows for imported days only.
                # This preserves any older rows outside the imported window.
                if overwrite:
                    LOGGER.debug(
                        "%s Overwrite requested for %s: applying window upsert without global delete.",
                        gateway_handler.log_id,
                        statistic_id,
                    )

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

                today = date.today()
                source_rows = sorted(rows, key=lambda item: item["date"])
                filtered_rows = [row for row in source_rows if row["date"] < today]

                skipped_partial_days = len(source_rows) - len(filtered_rows)
                skipped_hourly_days = 0

                if filtered_rows:
                    first_day = filtered_rows[0]["date"]
                    last_day = filtered_rows[-1]["date"]
                    try:
                        hourly_day_totals = await recorder_instance.async_add_executor_job(
                            self._load_hourly_daily_totals,
                            hass,
                            recorder_statistics,
                            statistic_id,
                            first_day,
                            last_day,
                        )
                    except Exception as err:  # pylint: disable=broad-except
                        errors.append(
                            f"{where}: failed to read existing hourly statistics ({type(err).__name__}: {err})"
                        )
                        hourly_day_totals = {}
                else:
                    hourly_day_totals = {}

                rows_to_import: list[tuple[date, float]] = []
                day_values: list[tuple[date, float]] = []
                for row in filtered_rows:
                    day = row["date"]
                    value = float(row["value"])
                    if target["unit_scale"] == "kilo":
                        value = value / 1000.0

                    day_values.append((day, value))

                    hourly_day = hourly_day_totals.get(day)
                    if hourly_day is not None and self._is_close_daily_value(
                        imported_value=value,
                        hourly_value=float(hourly_day["value"]),
                    ):
                        skipped_hourly_days += 1
                        continue

                    rows_to_import.append((day, value))

                sum_alignment_offset = 0.0
                sum_aligned_to_existing = False
                imported_cumulative_by_day: dict[date, float] = {}
                running_imported_total = 0.0
                for day, value in day_values:
                    running_imported_total += value
                    imported_cumulative_by_day[day] = running_imported_total

                if entity_statistic_id and len(day_values) > 0:
                    offset_candidates: list[float] = []
                    for day, value in day_values:
                        hourly_day = hourly_day_totals.get(day)
                        if hourly_day is None:
                            continue
                        if not self._is_close_daily_value(
                            imported_value=value,
                            hourly_value=float(hourly_day["value"]),
                        ):
                            continue
                        end_sum = hourly_day.get("end_sum")
                        imported_cumulative = imported_cumulative_by_day.get(day)
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
                        first_import_start = datetime.combine(
                            rows_to_import[0][0],
                            time.min,
                            tzinfo=timezone.utc,
                        )
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
                            last_import_start = datetime.combine(
                                rows_to_import[-1][0],
                                time.min,
                                tzinfo=timezone.utc,
                            )
                            if first_existing_start > last_import_start:
                                imported_total = sum(value for _day, value in rows_to_import)
                                sum_alignment_offset = first_existing_value - imported_total
                                sum_aligned_to_existing = True

                statistics_rows = []
                for day, value in rows_to_import:
                    running_sum = sum_alignment_offset + imported_cumulative_by_day[day]

                    start_at = datetime.combine(day, time.min, tzinfo=timezone.utc)
                    statistics_rows.append(
                        StatisticData(
                            start=start_at,
                            state=value,
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
                await recorder_instance.async_block_till_done()
                for imported_result, statistic_id, statistics_rows in persistence_checks:
                    try:
                        persisted_rows = await recorder_instance.async_add_executor_job(
                            self._persisted_statistics_count,
                            hass,
                            recorder_statistics,
                            statistic_id,
                            statistics_rows,
                        )
                    except Exception as err:  # pylint: disable=broad-except
                        errors.append(
                            f"{imported_result['where']}: failed to verify persisted statistics "
                            f"({type(err).__name__}: {err})"
                        )
                        imported_result["rows"] = 0
                        continue

                    imported_result["persisted_rows"] = persisted_rows
                    expected_rows = len(statistics_rows)
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
                    "overwrite": overwrite,
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
