"""Helper utilities for MyHOME web endpoints."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
import re

from ..const import (
    CONF_BUS_INTERFACE,
    CONF_DEVICE_CLASS,
    CONF_DEVICE_MODEL,
    CONF_ENTITY,
    CONF_MANUFACTURER,
    CONF_UNIT_SCALE,
    CONF_PLATFORMS,
    CONF_WHERE,
    CONF_WHO,
    CONF_ZONE,
    DOMAIN,
)
from ..validate import format_mac

LIGHT_PLATFORM = "light"
COVER_PLATFORM = "cover"
CLIMATE_PLATFORM = "climate"
SENSOR_PLATFORM = "sensor"
CONFIG_PLATFORMS = {LIGHT_PLATFORM, COVER_PLATFORM, CLIMATE_PLATFORM, SENSOR_PLATFORM}
SENSOR_CLASSES = {"power", "power_energy", "temperature", "energy", "water", "illuminance"}
SENSOR_UNIT_SCALES = {"base", "kilo"}
_SAFE_KEY_PATTERN = re.compile(r"[^a-z0-9_]+")


def to_bool(value: Any, default: bool) -> bool:
    """Convert user payload values to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def to_int(value: Any, default: int) -> int:
    """Convert user payload values to integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sanitize_key(value: str) -> str:
    """Sanitize a string to a valid device key."""
    clean = _SAFE_KEY_PATTERN.sub("_", str(value).strip().lower())
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean or "device"


def resolve_gateway_from_payload(configured_gateways, requested_gateway):
    """Resolve and validate gateway from request payload."""
    if not configured_gateways:
        return None, "No MyHOME gateways are configured.", HTTPStatus.NOT_FOUND

    if requested_gateway is None:
        return next(iter(configured_gateways.keys())), None, None

    gateway = format_mac(requested_gateway)
    if gateway is None:
        return None, f"Invalid gateway `{requested_gateway}`.", HTTPStatus.BAD_REQUEST
    if gateway not in configured_gateways:
        return None, f"Gateway `{gateway}` was not found.", HTTPStatus.NOT_FOUND
    return gateway, None, None


def entry_for_gateway(hass, gateway: str):
    """Get config entry for a gateway MAC."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get("mac") == gateway:
            return entry
    return None


async def reload_gateway_entry(hass, gateway: str) -> bool:
    """Reload a gateway config entry.

    Returns True when the target entry is found and reload succeeds.
    Raises RuntimeError when the entry is missing or reload fails.
    """
    entry = entry_for_gateway(hass, gateway)
    if entry is None:
        raise RuntimeError(f"No config entry found for gateway {gateway}")

    reloaded = await hass.config_entries.async_reload(entry.entry_id)
    if not reloaded:
        raise RuntimeError(
            f"Failed to reload config entry {entry.entry_id} for gateway {gateway}"
        )

    return True


def device_from_payload(platform: str, payload: dict[str, Any]) -> tuple[str | None, dict | None, str | None]:
    """Build device config from request payload with validation."""
    name = str(payload.get("name") or "").strip()
    if platform in (LIGHT_PLATFORM, COVER_PLATFORM, SENSOR_PLATFORM):
        where = str(payload.get("where") or "").strip()
        if not where:
            return None, None, "Field `where` is required."
        if not name:
            name = f"{platform.capitalize()} {where}"
        if platform == LIGHT_PLATFORM:
            return where, {
                "where": where,
                "name": name,
                "dimmable": to_bool(payload.get("dimmable"), False),
            }, None
        if platform == COVER_PLATFORM:
            return where, {"where": where, "name": name}, None
        sensor_class = str(payload.get("class") or "power").strip().lower()
        if sensor_class not in SENSOR_CLASSES:
            return None, None, f"Invalid sensor class `{sensor_class}`."
        unit_scale = str(payload.get("unit_scale") or "base").strip().lower()
        if unit_scale not in SENSOR_UNIT_SCALES:
            return None, None, f"Invalid unit scale `{unit_scale}`."
        return where, {
            "where": where,
            "name": name,
            "class": sensor_class,
            "unit_scale": unit_scale,
        }, None

    zone = str(payload.get("zone") or "").strip()
    if not zone:
        return None, None, "Field `zone` is required."
    if not name:
        name = f"Climate {zone}"
    return zone, {
        "zone": zone,
        "name": name,
        "heat": to_bool(payload.get("heat"), True),
        "cool": to_bool(payload.get("cool"), True),
        "fan": to_bool(payload.get("fan"), True),
        "standalone": to_bool(payload.get("standalone"), True),
    }, None


def devices_for_ui(gateway_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Format configured devices for web panel UI."""
    devices: dict[str, list[dict[str, Any]]] = {
        LIGHT_PLATFORM: [],
        COVER_PLATFORM: [],
        CLIMATE_PLATFORM: [],
        SENSOR_PLATFORM: [],
    }
    for platform in CONFIG_PLATFORMS:
        platform_data = gateway_payload.get(platform, {})
        if not isinstance(platform_data, dict):
            continue
        for key, value in sorted(platform_data.items()):
            if not isinstance(value, dict):
                continue
            entry = {
                "key": key,
                "name": value.get("name"),
                "where": value.get("where"),
                "zone": value.get("zone"),
                "who": value.get(CONF_WHO),
                "interface": value.get(CONF_BUS_INTERFACE),
                "manufacturer": value.get(CONF_MANUFACTURER),
                "model": value.get(CONF_DEVICE_MODEL),
            }
            if platform == LIGHT_PLATFORM:
                entry["dimmable"] = bool(value.get("dimmable", False))
            if platform == SENSOR_PLATFORM:
                entry["class"] = value.get("class")
                entry["unit_scale"] = value.get(CONF_UNIT_SCALE, "base")
            if platform == CLIMATE_PLATFORM:
                entry["heat"] = bool(value.get("heat", True))
                entry["cool"] = bool(value.get("cool", False))
                entry["fan"] = bool(value.get("fan", False))
                entry["standalone"] = bool(value.get("standalone", False))
            devices[platform].append(entry)
    return devices


def configured_discovery_endpoints(hass, gateway: str) -> dict[str, set[str]]:
    """Return already configured endpoints from runtime config."""
    gateway_data = hass.data.get(DOMAIN, {}).get(gateway, {})
    platforms = gateway_data.get(CONF_PLATFORMS, {})

    light_where = {
        str(device_data.get(CONF_WHERE))
        for device_data in platforms.get(LIGHT_PLATFORM, {}).values()
        if device_data.get(CONF_WHERE) is not None
    }
    cover_where = {
        str(device_data.get(CONF_WHERE))
        for device_data in platforms.get(COVER_PLATFORM, {}).values()
        if device_data.get(CONF_WHERE) is not None
    }
    climate_zone = {
        str(device_data.get(CONF_ZONE))
        for device_data in platforms.get(CLIMATE_PLATFORM, {}).values()
        if device_data.get(CONF_ZONE) is not None
    }
    power_where = set()
    for device_data in platforms.get(SENSOR_PLATFORM, {}).values():
        where = device_data.get(CONF_WHERE)
        if where is None:
            continue
        device_class = str(device_data.get(CONF_DEVICE_CLASS, "")).lower().split(".")[-1]
        if device_class in ("power", "power_energy", "energy", "water"):
            power_where.add(str(where))

    return {
        "light": light_where,
        "cover": cover_where,
        "climate": climate_zone,
        "power": power_where,
    }


def mapped_results(items: list[str], configured: set[str]) -> tuple[list[str], list[str]]:
    """Split results between already configured and new endpoints."""
    mapped = [str(item) for item in items if str(item) in configured]
    new = [str(item) for item in items if str(item) not in configured]
    return mapped, new


def merge_discovery_results(
    left: dict[str, list[str]],
    right: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Merge two discovery result dictionaries."""
    merged: dict[str, list[str]] = {}
    for kind in ("light", "cover", "climate", "power"):
        values = {str(item) for item in left.get(kind, [])}
        values.update({str(item) for item in right.get(kind, [])})
        merged[kind] = sorted(values)
    return merged


def is_valid_discovery_climate(where_raw: str) -> bool:
    """Check if a climate zone address is valid for discovery."""
    where = str(where_raw)
    if not where or where == "*":
        return False

    parts = [part for part in where.split("#") if part]
    if not parts:
        return False

    if parts[0] == "0" and len(parts) >= 2:
        zone = parts[1]
    else:
        zone = parts[0]

    return zone.isdigit() and int(zone) > 0


def build_discovery_snippet(
    light_results: list[str],
    cover_results: list[str],
    climate_results: list[str] | None = None,
    power_results: list[str] | None = None,
    mapped: dict[str, set[str]] | None = None,
) -> str:
    """Build a YAML snippet from discovery results."""
    snippet_lines: list[str] = []
    mapped = mapped or {"light": set(), "cover": set(), "climate": set(), "power": set()}

    if light_results:
        snippet_lines.append("light:")
        for where in light_results:
            suffix = "  # already_configured" if str(where) in mapped["light"] else ""
            snippet_lines.append(f"  discovered_light_{where}:{suffix}")
            snippet_lines.append(f"    where: '{where}'")
            snippet_lines.append(f"    name: Light {where}")
            snippet_lines.append("    dimmable: false")

    if cover_results:
        snippet_lines.append("cover:")
        for where in cover_results:
            suffix = "  # already_configured" if str(where) in mapped["cover"] else ""
            snippet_lines.append(f"  discovered_cover_{where}:{suffix}")
            snippet_lines.append(f"    where: '{where}'")
            snippet_lines.append(f"    name: Cover {where}")

    if climate_results:
        snippet_lines.append("climate:")
        for zone in climate_results:
            suffix = "  # already_configured" if str(zone) in mapped["climate"] else ""
            snippet_lines.append(f"  discovered_climate_{zone}:{suffix}")
            snippet_lines.append(f"    zone: '{zone}'")
            snippet_lines.append(f"    name: Climate {zone}")
            snippet_lines.append("    heat: true")
            snippet_lines.append("    cool: true")
            snippet_lines.append("    fan: true")

    if power_results:
        snippet_lines.append("sensor:")
        for where in power_results:
            suffix = "  # already_configured" if str(where) in mapped["power"] else ""
            snippet_lines.append(f"  discovered_power_{where}:{suffix}")
            snippet_lines.append(f"    where: '{where}'")
            snippet_lines.append(f"    name: Power+Energy {where}")
            snippet_lines.append("    class: power_energy")

    if not snippet_lines:
        snippet_lines.append("# No devices found in scanned range")

    return "\n".join(snippet_lines)
