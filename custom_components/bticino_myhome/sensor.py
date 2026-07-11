"""Support for MyHome sensors (power/energy, temperature, illuminance)."""

from datetime import timedelta

from voluptuous import (
    Optional,
    Coerce,
    All,
    Range,
)

from homeassistant.components.sensor import DOMAIN as PLATFORM
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_ENTITIES,
    CONF_NAME,
    CONF_MAC,
    LIGHT_LUX,
    UnitOfPower,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from .OWNd.message import (
    MESSAGE_TYPE_ACTIVE_POWER,
    MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION,
    MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION,
    MESSAGE_TYPE_ENERGY_TOTALIZER,
    MESSAGE_TYPE_ILLUMINANCE,
    MESSAGE_TYPE_MAIN_TEMPERATURE,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    OWNEnergyCommand,
    OWNEnergyEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNLightingCommand,
    OWNLightingEvent,
)

from .const import (
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_DEVICE_CLASS,
    CONF_UNIT_SCALE,
    CONF_DEVICE_MODEL,
    CONF_MANUFACTURER,
    CONF_WHERE,
    CONF_WHO,
    DOMAIN,
    LOGGER,
)
from .gateway import MyHOMEGatewayHandler
from .helpers.sensor_helpers import (
    get_required_entities,
    is_energy_sensor,
    is_illuminance_sensor,
    is_power_class,
    is_temperature_sensor,
    is_water_sensor,
)
from .myhome_device import MyHOMEEntity

SCAN_INTERVAL = timedelta(seconds=60)

SERVICE_SEND_INSTANT_POWER = "start_sending_instant_power"

ATTR_DURATION = "duration"
ATTR_DATE = "date"
ATTR_MONTH = "month"
ATTR_DAY = "day"


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _sensors = []
    _configured_sensors = hass.data[DOMAIN][config_entry.data[CONF_MAC]][
        CONF_PLATFORMS
    ][PLATFORM]
    _power_devices_configured = False

    for _sensor in _configured_sensors.keys():
        _sensor_config = _configured_sensors[_sensor]
        _device_class = _sensor_config[CONF_DEVICE_CLASS]

        if is_energy_sensor(_device_class):
            _required_entities = get_required_entities(_sensor_config)

            if is_power_class(_device_class):
                _power_devices_configured = True

                ent_reg = er.async_get(hass)
                existing_entity_id = ent_reg.async_get_entity_id(
                    "sensor", DOMAIN, _sensor
                )
                if existing_entity_id is not None:
                    LOGGER.warning(
                        "Sensor %s: %s will be migrated to %s-%s",
                        _sensor,
                        existing_entity_id,
                        _sensor,
                        SensorDeviceClass.POWER,
                    )
                    ent_reg.async_update_entity(
                        entity_id=existing_entity_id,
                        new_unique_id=f"{_sensor}-{SensorDeviceClass.POWER}",
                    )

                _sensors.append(
                    MyHOMEPowerSensor(
                        hass=hass,
                        device_id=_sensor,
                        who=_sensor_config[CONF_WHO],
                        where=_sensor_config[CONF_WHERE],
                        name=_sensor_config[CONF_NAME],
                        device_class=_device_class,
                        manufacturer=_sensor_config[CONF_MANUFACTURER],
                        model=_sensor_config[CONF_DEVICE_MODEL],
                        unit_scale=_sensor_config.get(CONF_UNIT_SCALE, "base"),
                        gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][
                            CONF_ENTITY
                        ],
                    )
                )
                if SensorDeviceClass.POWER in _required_entities:
                    _required_entities.remove(SensorDeviceClass.POWER)

            for entity_specific_id in _required_entities:
                _sensors.append(
                    MyHOMEEnergySensor(
                        hass=hass,
                        device_id=_sensor,
                        who=_sensor_config[CONF_WHO],
                        where=_sensor_config[CONF_WHERE],
                        name=_sensor_config[CONF_NAME],
                        entity_specific_id=entity_specific_id,
                        device_class=SensorDeviceClass.ENERGY,
                        unit_scale=_sensor_config.get(CONF_UNIT_SCALE, "base"),
                        manufacturer=_sensor_config[CONF_MANUFACTURER],
                        model=_sensor_config[CONF_DEVICE_MODEL],
                        gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][
                            CONF_ENTITY
                        ],
                    )
                )

        elif is_water_sensor(_device_class):
            _power_devices_configured = True
            _required_entities = get_required_entities(_sensor_config)

            _sensors.append(
                MyHOMEWaterFlowSensor(
                    hass=hass,
                    device_id=_sensor,
                    who=_sensor_config[CONF_WHO],
                    where=_sensor_config[CONF_WHERE],
                    name=_sensor_config[CONF_NAME],
                    unit_scale=_sensor_config.get(CONF_UNIT_SCALE, "base"),
                    manufacturer=_sensor_config[CONF_MANUFACTURER],
                    model=_sensor_config[CONF_DEVICE_MODEL],
                    gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][
                        CONF_ENTITY
                    ],
                )
            )
            if SensorDeviceClass.WATER in _required_entities:
                _required_entities.remove(SensorDeviceClass.WATER)

            for entity_specific_id in _required_entities:
                _sensors.append(
                    MyHOMEWaterVolumeSensor(
                        hass=hass,
                        device_id=_sensor,
                        who=_sensor_config[CONF_WHO],
                        where=_sensor_config[CONF_WHERE],
                        name=_sensor_config[CONF_NAME],
                        entity_specific_id=entity_specific_id,
                        unit_scale=_sensor_config.get(CONF_UNIT_SCALE, "base"),
                        manufacturer=_sensor_config[CONF_MANUFACTURER],
                        model=_sensor_config[CONF_DEVICE_MODEL],
                        gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][
                            CONF_ENTITY
                        ],
                    )
                )

        elif is_temperature_sensor(_device_class):
            _sensors.append(
                MyHOMETemperatureSensor(
                    hass=hass,
                    device_id=_sensor,
                    who=_sensor_config[CONF_WHO],
                    where=_sensor_config[CONF_WHERE],
                    name=_sensor_config[CONF_NAME],
                    device_class=_device_class,
                    manufacturer=_sensor_config[CONF_MANUFACTURER],
                    model=_sensor_config[CONF_DEVICE_MODEL],
                    gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
                )
            )

        elif is_illuminance_sensor(_device_class):
            _sensors.append(
                MyHOMEIlluminanceSensor(
                    hass=hass,
                    device_id=_sensor,
                    who=_sensor_config[CONF_WHO],
                    where=_sensor_config[CONF_WHERE],
                    name=_sensor_config[CONF_NAME],
                    device_class=_device_class,
                    manufacturer=_sensor_config[CONF_MANUFACTURER],
                    model=_sensor_config[CONF_DEVICE_MODEL],
                    gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
                )
            )

    if _power_devices_configured:
        platform = entity_platform.current_platform.get()

        platform.async_register_entity_service(
            SERVICE_SEND_INSTANT_POWER,
            {Optional(ATTR_DURATION): All(Coerce(int), Range(min=1, max=255))},
            "start_sending_instant_power",
        )

    async_add_entities(_sensors)


async def async_unload_entry(hass, config_entry):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _configured_sensors = hass.data[DOMAIN][config_entry.data[CONF_MAC]][
        CONF_PLATFORMS
    ][PLATFORM]

    for _sensor in _configured_sensors.keys():
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][
            _sensor
        ]


class MyHOMEPowerSensor(MyHOMEEntity, SensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        device_id: str,
        who: str,
        where: str,
        device_class: str,
        unit_scale: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ) -> None:
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._entity_specific_name = "Power"
        self._attr_name = f"{name} {self._entity_specific_name}"

        self._attr_device_class = device_class
        self._unit_scale = unit_scale
        self._attr_unique_id = (
            f"{gateway.mac}-{self._device_id}-{self._attr_device_class}"
        )
        self._attr_native_unit_of_measurement = (
            UnitOfPower.KILO_WATT
            if self._unit_scale == "kilo"
            else UnitOfPower.WATT
        )
        self._attr_state_class = SensorStateClass.MEASUREMENT

        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "Sensor": f"({self._where[0]}){self._where[1:]}"
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
            self._platform
        ][self._device_id][CONF_ENTITIES][self._attr_device_class] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if (
            self._attr_device_class
            in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES]
        ):
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES][self._attr_device_class]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        # await self.start_sending_instant_power(255)

    def handle_event(self, message: OWNEnergyEvent):
        """Handle an event message."""
        if message.message_type not in [MESSAGE_TYPE_ACTIVE_POWER]:
            return True

        LOGGER.debug(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )
        self._attr_native_value = (
            round(message.active_power / 1000, 3)
            if self._unit_scale == "kilo"
            else message.active_power
        )
        self.async_schedule_update_ha_state()

    async def start_sending_instant_power(self, duration):
        """Request automatic instant power."""
        await self._gateway_handler.send(
            OWNEnergyCommand.start_sending_instant_power(self._where, duration)
        )


class MyHOMEEnergySensor(MyHOMEEntity, SensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        device_id: str,
        who: str,
        where: str,
        entity_specific_id: str,
        device_class: str,
        unit_scale: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ) -> None:
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._entity_specific_id = entity_specific_id
        if self._entity_specific_id == "daily-energy":
            self._entity_specific_name = "Energy (today)"
            self._attr_entity_registry_enabled_default = False
        elif self._entity_specific_id == "monthly-energy":
            self._entity_specific_name = "Energy (current month)"
            self._attr_entity_registry_enabled_default = False
        elif self._entity_specific_id == "total-energy":
            self._entity_specific_name = "Energy"
            self._attr_entity_registry_enabled_default = True
        self._attr_name = f"{name} {self._entity_specific_name}"

        self._attr_unique_id = (
            f"{gateway.mac}-{self._device_id}-{self._entity_specific_id}"
        )
        self._attr_device_class = device_class
        self._unit_scale = unit_scale
        self._attr_native_unit_of_measurement = (
            UnitOfEnergy.KILO_WATT_HOUR
            if self._unit_scale == "kilo"
            else UnitOfEnergy.WATT_HOUR
        )
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_should_poll = True
        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "Sensor": f"({self._where[0]}){self._where[1:]}"
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
            self._platform
        ][self._device_id][CONF_ENTITIES][self._entity_specific_id] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if (
            self._entity_specific_id
            in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES]
        ):
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES][self._entity_specific_id]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        if self._entity_specific_id == "total-energy":
            await self._gateway_handler.send_status_request(
                OWNEnergyCommand.get_total_consumption(self._where)
            )
        elif self._entity_specific_id == "monthly-energy":
            await self._gateway_handler.send_status_request(
                OWNEnergyCommand.get_partial_monthly_consumption(self._where)
            )
        elif self._entity_specific_id == "daily-energy":
            await self._gateway_handler.send_status_request(
                OWNEnergyCommand.get_partial_daily_consumption(self._where)
            )

    def handle_event(self, message: OWNEnergyEvent):
        """Handle an event message."""
        if message.message_type not in [
            MESSAGE_TYPE_ENERGY_TOTALIZER,
            MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION,
            MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION,
        ]:
            return True

        if (
            self._entity_specific_id == "total-energy"
            and message.message_type == MESSAGE_TYPE_ENERGY_TOTALIZER
        ):
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            value = message.total_consumption
            self._attr_native_value = (
                round(value / 1000, 3) if self._unit_scale == "kilo" else value
            )
        elif (
            self._entity_specific_id == "monthly-energy"
            and message.message_type == MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION
        ):
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            value = message.current_month_partial_consumption
            self._attr_native_value = (
                round(value / 1000, 3) if self._unit_scale == "kilo" else value
            )
        elif (
            self._entity_specific_id == "daily-energy"
            and message.message_type == MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION
        ):
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            value = message.current_day_partial_consumption
            self._attr_native_value = (
                round(value / 1000, 3) if self._unit_scale == "kilo" else value
            )
        self.async_schedule_update_ha_state()


class MyHOMEWaterFlowSensor(MyHOMEEntity, SensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        device_id: str,
        who: str,
        where: str,
        unit_scale: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ) -> None:
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._entity_specific_name = "Flow"
        self._attr_name = f"{name} {self._entity_specific_name}"

        self._attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
        self._unit_scale = unit_scale
        self._attr_unique_id = (
            f"{gateway.mac}-{self._device_id}-{SensorDeviceClass.WATER}"
        )
        self._attr_native_unit_of_measurement = (
            getattr(UnitOfVolumeFlowRate, "CUBIC_METERS_PER_HOUR", "m3/h")
            if self._unit_scale == "kilo"
            else UnitOfVolumeFlowRate.LITERS_PER_HOUR
        )
        self._attr_state_class = SensorStateClass.MEASUREMENT

        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "Sensor": f"({self._where[0]}){self._where[1:]}"
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
            self._platform
        ][self._device_id][CONF_ENTITIES][SensorDeviceClass.WATER] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if (
            SensorDeviceClass.WATER
            in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES]
        ):
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES][SensorDeviceClass.WATER]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """

    def handle_event(self, message: OWNEnergyEvent):
        """Handle an event message."""
        if message.message_type not in [MESSAGE_TYPE_ACTIVE_POWER]:
            return True

        LOGGER.debug(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )
        self._attr_native_value = (
            round(message.active_power / 1000, 4)
            if self._unit_scale == "kilo"
            else message.active_power
        )
        self.async_schedule_update_ha_state()

    async def start_sending_instant_power(self, duration):
        """Request automatic instant flow data."""
        await self._gateway_handler.send(
            OWNEnergyCommand.start_sending_instant_power(self._where, duration)
        )


class MyHOMEWaterVolumeSensor(MyHOMEEntity, SensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        device_id: str,
        who: str,
        where: str,
        entity_specific_id: str,
        unit_scale: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ) -> None:
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._entity_specific_id = entity_specific_id
        if self._entity_specific_id == "daily-water":
            self._entity_specific_name = "Volume (today)"
            self._attr_entity_registry_enabled_default = False
        elif self._entity_specific_id == "monthly-water":
            self._entity_specific_name = "Volume (current month)"
            self._attr_entity_registry_enabled_default = False
        elif self._entity_specific_id == "total-water":
            self._entity_specific_name = "Volume"
            self._attr_entity_registry_enabled_default = True
        self._attr_name = f"{name} {self._entity_specific_name}"

        self._attr_unique_id = (
            f"{gateway.mac}-{self._device_id}-{self._entity_specific_id}"
        )
        self._attr_device_class = SensorDeviceClass.WATER
        self._unit_scale = unit_scale
        self._attr_native_unit_of_measurement = (
            UnitOfVolume.CUBIC_METERS
            if self._unit_scale == "kilo"
            else UnitOfVolume.LITERS
        )
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_should_poll = True
        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "Sensor": f"({self._where[0]}){self._where[1:]}"
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
            self._platform
        ][self._device_id][CONF_ENTITIES][self._entity_specific_id] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if (
            self._entity_specific_id
            in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES]
        ):
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES][self._entity_specific_id]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        if self._entity_specific_id == "total-water":
            await self._gateway_handler.send_status_request(
                OWNEnergyCommand.get_total_consumption(self._where)
            )
        elif self._entity_specific_id == "monthly-water":
            await self._gateway_handler.send_status_request(
                OWNEnergyCommand.get_partial_monthly_consumption(self._where)
            )
        elif self._entity_specific_id == "daily-water":
            await self._gateway_handler.send_status_request(
                OWNEnergyCommand.get_partial_daily_consumption(self._where)
            )

    def handle_event(self, message: OWNEnergyEvent):
        """Handle an event message."""
        if message.message_type not in [
            MESSAGE_TYPE_ENERGY_TOTALIZER,
            MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION,
            MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION,
        ]:
            return True

        if (
            self._entity_specific_id == "total-water"
            and message.message_type == MESSAGE_TYPE_ENERGY_TOTALIZER
        ):
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            value = message.total_consumption
            self._attr_native_value = (
                round(value / 1000, 4) if self._unit_scale == "kilo" else value
            )
        elif (
            self._entity_specific_id == "monthly-water"
            and message.message_type == MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION
        ):
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            value = message.current_month_partial_consumption
            self._attr_native_value = (
                round(value / 1000, 4) if self._unit_scale == "kilo" else value
            )
        elif (
            self._entity_specific_id == "daily-water"
            and message.message_type == MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION
        ):
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            value = message.current_day_partial_consumption
            self._attr_native_value = (
                round(value / 1000, 4) if self._unit_scale == "kilo" else value
            )
        self.async_schedule_update_ha_state()


class MyHOMETemperatureSensor(MyHOMEEntity, SensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        device_id: str,
        who: str,
        where: str,
        device_class: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ) -> None:
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._entity_specific_name = "Temperature"
        self._attr_name = f"{name} {self._entity_specific_name}"

        self._attr_device_class = device_class
        self._attr_unique_id = (
            f"{gateway.mac}-{self._device_id}-{self._attr_device_class}"
        )
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_should_poll = True
        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "Sensor": f"({self._where[0]}){self._where[1:]}"
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
            self._platform
        ][self._device_id][CONF_ENTITIES][self._attr_device_class] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if (
            self._attr_device_class
            in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES]
        ):
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES][self._attr_device_class]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._gateway_handler.send_status_request(
            OWNHeatingCommand.get_temperature(self._where)
        )

    def handle_event(self, message: OWNHeatingEvent):
        """Handle an event message."""
        if message.message_type not in [
            MESSAGE_TYPE_MAIN_TEMPERATURE,
            MESSAGE_TYPE_SECONDARY_TEMPERATURE,
        ]:
            return True

        if message.message_type == MESSAGE_TYPE_MAIN_TEMPERATURE:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._attr_native_value = message.main_temperature
            self.async_schedule_update_ha_state()
        elif message.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._attr_native_value = message.secondary_temperature[1]
            self.async_schedule_update_ha_state()


class MyHOMEIlluminanceSensor(MyHOMEEntity, SensorEntity):
    def __init__(
        self,
        hass,
        name: str,
        device_id: str,
        who: str,
        where: str,
        device_class: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ) -> None:
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._entity_specific_name = "Illuminance"
        self._attr_name = f"{name} {self._entity_specific_name}"

        self._attr_device_class = device_class
        self._attr_unique_id = (
            f"{gateway.mac}-{self._device_id}-{self._attr_device_class}"
        )
        self._attr_native_unit_of_measurement = LIGHT_LUX
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "A": where[: len(where) // 2],
            "PL": where[len(where) // 2 :],
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
            self._platform
        ][self._device_id][CONF_ENTITIES][self._attr_device_class] = self
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if (
            self._attr_device_class
            in self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES]
        ):
            del self._hass.data[DOMAIN][self._gateway_handler.mac][CONF_PLATFORMS][
                self._platform
            ][self._device_id][CONF_ENTITIES][self._attr_device_class]

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._gateway_handler.send_status_request(
            OWNLightingCommand.get_illuminance(self._where)
        )

    def handle_event(self, message: OWNLightingEvent):
        """Handle an event message."""
        if message.message_type not in [MESSAGE_TYPE_ILLUMINANCE]:
            return True

        LOGGER.debug(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )
        self._attr_native_value = message.illuminance
        self.async_schedule_update_ha_state()
