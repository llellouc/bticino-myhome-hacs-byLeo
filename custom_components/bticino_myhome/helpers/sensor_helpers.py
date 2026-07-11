"""Helper utilities for MyHOME sensor setup and management."""

from homeassistant.components.sensor import SensorDeviceClass

from ..const import CONF_ENTITIES


def is_energy_sensor(device_class) -> bool:
    """Check if sensor is power/energy type."""
    return device_class in (
        SensorDeviceClass.POWER,
        SensorDeviceClass.ENERGY,
        "power_energy",
    )


def is_water_sensor(device_class) -> bool:
    """Check if sensor is water type."""
    return device_class == SensorDeviceClass.WATER


def is_temperature_sensor(device_class) -> bool:
    """Check if sensor is temperature type."""
    return device_class == SensorDeviceClass.TEMPERATURE


def is_illuminance_sensor(device_class) -> bool:
    """Check if sensor is illuminance type."""
    return device_class == SensorDeviceClass.ILLUMINANCE


def has_power_device_capability(device_class) -> bool:
    """Check if sensor can provide instant power/flow data."""
    return device_class in (
        SensorDeviceClass.POWER,
        "power_energy",
        SensorDeviceClass.WATER,
    )


def get_required_entities(sensor_config: dict) -> list:
    """Extract required entity IDs from sensor config."""
    return list(sensor_config.get(CONF_ENTITIES, {}).keys())


def is_power_class(device_class) -> bool:
    """Check if device_class is specifically POWER."""
    return device_class in (SensorDeviceClass.POWER, "power_energy")
