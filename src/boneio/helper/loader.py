from __future__ import annotations

import logging
import typing
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from busio import I2C

from boneio.config import (
    AdcConfig,
    BinarySensorActionTypes,
    BinarySensorConfig,
    Config,
    CoverConfig,
    EventActionTypes,
    EventConfig,
    Ina219Config,
    ModbusDeviceConfig,
    OutputConfig,
    SensorConfig,
    TemperatureConfig,
)
from boneio.const import (
    BINARY_SENSOR,
    COVER,
    EVENT_ENTITY,
    GPIO,
    INPUT,
    INPUT_SENSOR,
    LM75,
    MCP_TEMP_9808,
    NONE,
    RELAY,
    SENSOR,
)
from boneio.cover import PreviousCover, TimeBasedCover, VenetianCover
from boneio.gpio import (
    GpioEventButtonNew,
    GpioEventButtonOld,
    GpioEventButtonsAndSensors,
    GpioInputBinarySensorNew,
    GpioInputBinarySensorOld,
    GpioRelay,
)
from boneio.gpio_manager import GpioManager
from boneio.helper import (
    CoverConfigurationError,
    GPIOInputException,
    I2CError,
    StateManager,
    ha_adc_sensor_availabilty_message,
    ha_binary_sensor_availabilty_message,
    ha_event_availabilty_message,
    ha_sensor_ina_availabilty_message,
    ha_sensor_temp_availabilty_message,
)
from boneio.helper.events import EventBus
from boneio.helper.ha_discovery import (
    ha_cover_availabilty_message,
    ha_cover_with_tilt_availabilty_message,
    ha_sensor_availabilty_message,
    ha_virtual_energy_sensor_discovery_message,
)
from boneio.helper.onewire import (
    DS2482,
    DS2482_ADDRESS,
    AsyncBoneIOW1ThermSensor,
    OneWireAddress,
    OneWireBus,
)
from boneio.message_bus.basic import MessageBus
from boneio.modbus.client import Modbus
from boneio.modbus.coordinator import ModbusCoordinator
from boneio.relay import PWMPCA, MCPRelay, PCFRelay
from boneio.relay.basic import BasicRelay
from boneio.sensor import DallasSensorDS2482, GpioADCSensor, initialize_adc
from boneio.sensor.ina219 import INA219
from boneio.sensor.serial_number import SerialNumberSensor
from boneio.sensor.temp.dallas import DallasSensorW1

if TYPE_CHECKING:
    from ..manager import Manager

_LOGGER = logging.getLogger(__name__)


def create_adc(
    manager: Manager,
    message_bus: MessageBus,
    topic_prefix: str,
    adc: list[AdcConfig],
):
    """Create ADC sensor."""

    if adc:
        initialize_adc()

    # TODO: find what exception can ADC gpio throw.
    for gpio in adc:
        id = gpio.id.replace(" ", "")
        try:
            GpioADCSensor(
                id=id,
                pin=gpio.pin,
                name=gpio.id,
                manager=manager,
                message_bus=message_bus,
                topic_prefix=topic_prefix,
                update_interval=gpio.update_interval,
                filters=gpio.filters,
            )
            if gpio.show_in_ha:
                manager.send_ha_autodiscovery(
                    id=id,
                    name=gpio.id,
                    ha_type=SENSOR,
                    availability_msg_func=ha_adc_sensor_availabilty_message,
                )
        except I2CError as err:
            _LOGGER.error("Can't configure ADC sensor %s. %s", id, err)


def create_temp_sensor(
    manager: Manager,
    message_bus: MessageBus,
    topic_prefix: str,
    sensor_type: str,
    i2cbusio: I2C,
    config: TemperatureConfig,
):
    """Create LM sensor in manager."""
    if sensor_type == LM75:
        from boneio.sensor import LM75Sensor as TempSensor
    elif sensor_type == MCP_TEMP_9808:
        from boneio.sensor import MCP9808Sensor as TempSensor
    else:
        return None
    name = config.id
    if name is None:
        return None
    id = name.replace(" ", "")
    try:
        temp_sensor = TempSensor(
            id=id,
            name=name,
            i2c=i2cbusio,
            address=config.address,
            manager=manager,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            update_interval=config.update_interval,
            filters=config.filters,
            unit_of_measurement=config.unit_of_measurement,
        )
        manager.send_ha_autodiscovery(
            id=id,
            name=name,
            ha_type=SENSOR,
            availability_msg_func=ha_sensor_temp_availabilty_message,
            unit_of_measurement=temp_sensor.unit_of_measurement,
        )
        return temp_sensor
    except I2CError as err:
        _LOGGER.error("Can't configure Temp sensor. %s", err)


def create_serial_number_sensor(
    manager: Manager,
    message_bus: MessageBus,
    topic_prefix: str,
):
    """Create Serial number sensor in manager."""
    sensor = SerialNumberSensor(
        id="serial_number",
        name="Serial number",
        manager=manager,
        message_bus=message_bus,
        topic_prefix=topic_prefix,
    )
    manager.send_ha_autodiscovery(
        id="serial_number",
        name="Serial number",
        ha_type=SENSOR,
        entity_category="diagnostic",
        availability_msg_func=ha_sensor_availabilty_message,
    )
    return sensor


def create_modbus_coordinators(
    manager: Manager,
    message_bus: MessageBus,
    event_bus: EventBus,
    entries: list[ModbusDeviceConfig],
    modbus: Modbus,
    config: Config,
) -> dict[str, ModbusCoordinator]:
    """Create Modbus sensor for each device."""

    modbus_coordinators = {}
    for entry in entries:
        id = entry.id.replace(" ", "")
        try:
            modbus_coordinators[id.lower()] = ModbusCoordinator(
                address=entry.address,
                id=id,
                name=entry.id,
                manager=manager,
                model=entry.model,
                message_bus=message_bus,
                update_interval=entry.update_interval,
                sensors_filters=entry.sensor_filters,
                additional_data=entry.data,
                modbus=modbus,
                event_bus=event_bus,
                config=config,
            )
        except FileNotFoundError as err:
            _LOGGER.error(
                "Can't configure Modbus sensor %s. %s. No such model in database.",
                id,
                err,
            )
    return modbus_coordinators


def configure_relay(
    manager: Manager,
    message_bus: MessageBus,
    state_manager: StateManager,
    topic_prefix: str,
    relay_id: str,
    name: str,
    output_config: OutputConfig,
    event_bus: EventBus,
    restore_state: bool = False,
) -> BasicRelay | None:
    """Configure kind of relay. Most common MCP."""
    restored_state = (
        state_manager.get(attr_type=RELAY, attr=relay_id, default_value=False)
        if restore_state
        else False
    )
    if output_config.output_type == NONE and state_manager.get(
        attr_type=RELAY, attr=relay_id
    ):
        state_manager.del_attribute(attr_type=RELAY, attribute=relay_id)
        restored_state = False

    if isinstance(output_config.interlock_group, str):
        output_config.interlock_group = [output_config.interlock_group]

    if output_config.kind == "gpio":
        expander_id = output_config.id
        if GPIO not in manager.grouped_outputs_by_expander:
            manager.grouped_outputs_by_expander[GPIO] = {}
        relay = GpioRelay(
            pin_id=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
        )
    elif output_config.kind == "mcp":
        if output_config.mcp_id is None:
            _LOGGER.error("No MCP id configured!")
            return None
        expander_id = output_config.mcp_id
        mcp = manager.mcp.get(expander_id)
        if not mcp:
            _LOGGER.error("No such MCP configured!")
            return None
        relay = MCPRelay(
            pin=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
            mcp=mcp,
            output_type=output_config.output_type,
        )
    elif output_config.kind == "pca":
        if output_config.pca_id is None:
            _LOGGER.error("No PCA id configured!")
            return None
        expander_id = output_config.pca_id
        pca = manager.pca.get(expander_id)
        if not pca:
            _LOGGER.error("No such PCA configured!")
            return None
        relay = PWMPCA(
            pin=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
            pca=pca,
            pca_id=output_config.pca_id,
            output_type=output_config.output_type,
        )
    elif output_config.kind == "pcf":
        if output_config.pcf_id is None:
            _LOGGER.error("No PCF id configured!")
            return None
        expander_id = output_config.pcf_id
        expander = manager.pcf.get(expander_id)
        if not expander:
            _LOGGER.error("No such PCF configured!")
            return None
        relay = PCFRelay(
            pin=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
            output_type=output_config.output_type,
            expander=expander,
        )
    else:
        _LOGGER.error("Output kind: %s is not configured", output_config.kind)
        return None

    manager.interlock_manager.register(relay, output_config.interlock_group)
    manager.grouped_outputs_by_expander[expander_id][relay_id] = relay
    if relay.is_virtual_power:
        manager.send_ha_autodiscovery(
            id=f"{relay_id}_virtual_power",
            relay_id=relay_id,
            name=f"{name} Virtual Power",
            ha_type="sensor",
            device_type="energy",
            availability_msg_func=ha_virtual_energy_sensor_discovery_message,
            unit_of_measurement="W",
            device_class="power",
            state_class="measurement",
            value_template="{{ value_json.power }}",
        )
        manager.send_ha_autodiscovery(
            id=f"{relay_id}_virtual_energy",
            relay_id=relay_id,
            name=f"{name} Virtual Energy",
            ha_type="sensor",
            device_type="energy",
            availability_msg_func=ha_virtual_energy_sensor_discovery_message,
            unit_of_measurement="Wh",
            device_class="energy",
            state_class="total_increasing",
            value_template="{{ value_json.energy }}",
        )
    if relay.is_virtual_volume_flow_rate:
        manager.send_ha_autodiscovery(
            id=f"{relay_id}_virtual_volume_flow_rate",
            relay_id=relay_id,
            name=f"{name} Virtual Volume Flow Rate",
            ha_type="sensor",
            device_type="energy",
            availability_msg_func=ha_virtual_energy_sensor_discovery_message,
            unit_of_measurement="L/h",
            device_class="volume_flow_rate",
            state_class="measurement",
            value_template="{{ value_json.volume_flow_rate }}",
        )
        manager.send_ha_autodiscovery(
            id=f"{relay_id}_virtual_consumption",
            relay_id=relay_id,
            name=f"{name} Virtual consumption",
            ha_type="sensor",
            device_type="energy",
            availability_msg_func=ha_virtual_energy_sensor_discovery_message,
            unit_of_measurement="L",
            device_class="water",
            state_class="total_increasing",
            value_template="{{ value_json.water }}",
        )
    return relay


def configure_event_sensor(
    gpio: EventConfig,
    gpio_manager: GpioManager,
    manager_press_callback: Callable,
    event_bus: EventBus,
    send_ha_autodiscovery: Callable,
    actions: dict[
        EventActionTypes | BinarySensorActionTypes, list[dict[str, typing.Any]]
    ],
    input: GpioEventButtonsAndSensors | None = None,
) -> GpioEventButtonsAndSensors:
    """Configure input sensor or button."""
    name = gpio.id or gpio.pin
    if input:
        GpioEventButtonClass = (
            GpioEventButtonNew if gpio.detection_type == "new" else GpioEventButtonOld
        )
        if not isinstance(input, GpioEventButtonClass):
            _LOGGER.warning(
                "You reconfigured type of input. It's forbidden. Please restart boneIO."
            )
            return input
        input.actions = actions
    else:
        try:
            if gpio.detection_type == "new":
                input = GpioEventButtonNew(
                    pin=gpio.pin,
                    name=name,
                    input_type=INPUT,
                    empty_message_after=gpio.clear_message,
                    actions=actions,
                    manager_press_callback=manager_press_callback,
                    event_bus=event_bus,
                    gpio_manager=gpio_manager,
                )
            else:
                input = GpioEventButtonOld(
                    pin=gpio.pin,
                    name=name,
                    input_type=INPUT,
                    empty_message_after=gpio.clear_message,
                    actions=actions,
                    manager_press_callback=manager_press_callback,
                    event_bus=event_bus,
                    gpio_manager=gpio_manager,
                )
        except GPIOInputException as err:
            _LOGGER.error("This PIN %s can't be configured. %s", gpio.pin, err)
            raise
    if gpio.show_in_ha:
        send_ha_autodiscovery(
            id=gpio.pin,
            name=name,
            ha_type=EVENT_ENTITY,
            device_class=gpio.device_class,
            availability_msg_func=ha_event_availabilty_message,
        )
    return input


def configure_binary_sensor(
    gpio: BinarySensorConfig,
    manager_press_callback: Callable,
    event_bus: EventBus,
    send_ha_autodiscovery: Callable,
    gpio_manager: GpioManager,
    actions: dict[
        EventActionTypes | BinarySensorActionTypes, list[dict[str, typing.Any]]
    ],
    input: GpioEventButtonsAndSensors | None = None,
) -> GpioEventButtonsAndSensors:
    """Configure input sensor or button."""
    name = gpio.id or gpio.pin
    if input:
        GpioInputBinarySensorClass = (
            GpioInputBinarySensorNew
            if gpio.detection_type == "new"
            else GpioInputBinarySensorOld
        )
        if not isinstance(input, GpioInputBinarySensorClass):
            _LOGGER.warning(
                "You preconfigured type of input. It's forbidden. Please restart boneIO."
            )
            return input
        input.actions = actions
    else:
        try:
            if gpio.detection_type == "new":
                input = GpioInputBinarySensorNew(
                    pin=gpio.pin,
                    name=name,
                    actions=actions,
                    input_type=INPUT_SENSOR,
                    empty_message_after=gpio.clear_message,
                    manager_press_callback=manager_press_callback,
                    event_bus=event_bus,
                    gpio=gpio,
                    gpio_manager=gpio_manager,
                )
            else:
                input = GpioInputBinarySensorOld(
                    pin=gpio.pin,
                    name=name,
                    actions=actions,
                    input_type=INPUT_SENSOR,
                    empty_message_after=gpio.clear_message,
                    manager_press_callback=manager_press_callback,
                    event_bus=event_bus,
                    gpio=gpio,
                    gpio_manager=gpio_manager,
                )
        except GPIOInputException as err:
            _LOGGER.error("This PIN %s can't be configured. %s", gpio.pin, err)
            raise

    if gpio.show_in_ha:
        send_ha_autodiscovery(
            id=gpio.pin,
            name=name,
            ha_type=BINARY_SENSOR,
            device_class=gpio.device_class,
            availability_msg_func=ha_binary_sensor_availabilty_message,
        )
    return input


def configure_cover(
    message_bus: MessageBus,
    cover_id: str,
    state_manager: StateManager,
    send_ha_autodiscovery: Callable,
    config: CoverConfig,
    open_relay: BasicRelay,
    close_relay: BasicRelay,
    event_bus: EventBus,
    topic_prefix: str,
) -> PreviousCover | TimeBasedCover | VenetianCover:
    platform = config.platform or "previous"

    def state_save(value: dict[str, int]):
        if config.restore_state:
            state_manager.save_attribute(
                attr_type=COVER,
                attribute=cover_id,
                value=value,
            )

    if platform == "venetian":
        if not config.tilt_duration:
            raise CoverConfigurationError(
                "Tilt duration must be configured for tilt cover."
            )
        _LOGGER.debug("Configuring tilt cover %s", cover_id)
        restored_state: dict = state_manager.get(
            attr_type=COVER,
            attr=cover_id,
            default_value={"position": 100, "tilt_position": 100},
        )
        if isinstance(restored_state, (float, int)):
            restored_state = {"position": restored_state, "tilt_position": 100}
        cover = VenetianCover(
            id=cover_id,
            state_save=state_save,
            message_bus=message_bus,
            restored_state=restored_state,
            tilt_duration=config.tilt_duration,
            actuator_activation_duration=config.actuator_activation_duration,
            open_relay=open_relay,
            close_relay=close_relay,
            open_time=config.open_time,
            close_time=config.close_time,
            event_bus=event_bus,
            topic_prefix=topic_prefix,
        )
        availability_msg_func = ha_cover_with_tilt_availabilty_message
    elif platform == "time_based":
        _LOGGER.debug("Configuring time-based cover %s", cover_id)
        restored_state: dict = state_manager.get(
            attr_type=COVER, attr=cover_id, default_value={"position": 100}
        )
        if isinstance(restored_state, (float, int)):
            restored_state = {"position": restored_state}
        cover = TimeBasedCover(
            id=cover_id,
            state_save=state_save,
            message_bus=message_bus,
            restored_state=restored_state,
            open_relay=open_relay,
            close_relay=close_relay,
            open_time=config.open_time,
            close_time=config.close_time,
            event_bus=event_bus,
            topic_prefix=topic_prefix,
        )
        availability_msg_func = ha_cover_availabilty_message
    else:
        _LOGGER.debug("Configuring previous cover %s", cover_id)
        restored_state: dict = state_manager.get(
            attr_type=COVER, attr=cover_id, default_value={"position": 100}
        )
        if isinstance(restored_state, (float, int)):
            restored_state = {"position": restored_state}
        cover = PreviousCover(
            id=cover_id,
            state_save=state_save,
            message_bus=message_bus,
            restored_state=restored_state,
            open_relay=open_relay,
            close_relay=close_relay,
            open_time=config.open_time,
            close_time=config.close_time,
            event_bus=event_bus,
            topic_prefix=topic_prefix,
        )
        availability_msg_func = ha_cover_availabilty_message
    if config.show_in_ha:
        send_ha_autodiscovery(
            id=cover.id,
            name=cover.name,
            ha_type=COVER,
            device_class=config.device_class,
            availability_msg_func=availability_msg_func,
        )
    _LOGGER.debug("Configured cover %s", cover_id)
    return cover


def configure_ds2482(i2cbusio: I2C, address: str = DS2482_ADDRESS) -> OneWireBus:
    ds2482 = DS2482(i2c=i2cbusio, address=address)
    ow_bus = OneWireBus(ds2482=ds2482)
    return ow_bus


def configure_dallas() -> type[AsyncBoneIOW1ThermSensor]:
    return AsyncBoneIOW1ThermSensor


def find_onewire_devices(
    ow_bus: OneWireBus | AsyncBoneIOW1ThermSensor,
    bus_id: str,
    bus_type: Literal["ds2482", "dallas"],
) -> dict[int, OneWireAddress]:
    out: dict[int, OneWireAddress] = {}
    try:
        devices = ow_bus.scan()
        for device in devices:
            _addr: int = device.int_address
            _LOGGER.debug("Found device on bus %s with address %s", bus_id, hex(_addr))
            out[_addr] = device
    except RuntimeError as err:
        _LOGGER.error("Problem with scanning %s bus. %s", bus_type, err)
    return out


def create_dallas_sensor(
    manager: Manager,
    message_bus: MessageBus,
    address: OneWireAddress,
    config: SensorConfig,
    topic_prefix: str,
    bus: OneWireBus | None = None,
) -> DallasSensorDS2482 | DallasSensorW1:
    name = config.id or hex(address)
    id = name.replace(" ", "")
    cls = DallasSensorDS2482 if bus else DallasSensorW1
    sensor = cls(
        manager=manager,
        message_bus=message_bus,
        address=address,
        id=id,
        name=name,
        update_interval=config.update_interval,
        filters=config.filters,
        topic_prefix=topic_prefix,
        bus=bus,
    )
    if config.show_in_ha:
        manager.send_ha_autodiscovery(
            id=sensor.id,
            name=sensor.name,
            ha_type=SENSOR,
            availability_msg_func=ha_sensor_temp_availabilty_message,
            unit_of_measurement=config.unit_of_measurement,
        )
    return sensor


def create_ina219_sensor(
    manager: Manager,
    message_bus: MessageBus,
    topic_prefix: str,
    config: Ina219Config,
) -> INA219:
    """Create INA219 sensor in manager."""
    ina219 = INA219(
        manager=manager,
        message_bus=message_bus,
        topic_prefix=topic_prefix,
        config=config,
    )

    for sensor in ina219.sensors.values():
        manager.send_ha_autodiscovery(
            id=sensor.id,
            name=sensor.name,
            ha_type=SENSOR,
            availability_msg_func=ha_sensor_ina_availabilty_message,
            unit_of_measurement=sensor.unit_of_measurement,
            device_class=sensor.device_class,
        )
    return ina219
