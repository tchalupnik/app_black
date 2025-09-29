from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, assert_never

from busio import I2C

from boneio.config import (
    AdcConfig,
    BinarySensorConfig,
    Config,
    EventConfig,
    GpioOutputConfig,
    McpOutputConfig,
    MockOutputConfig,
    ModbusDeviceConfig,
    OutputConfigKinds,
    PcaOutputConfig,
    PcfOutputConfig,
    SensorConfig,
    TemperatureConfig,
)
from boneio.const import (
    BINARY_SENSOR,
    EVENT_ENTITY,
    LM75,
    MCP_TEMP_9808,
    NONE,
    SENSOR,
)
from boneio.events import EventBus
from boneio.helper import (
    I2CError,
    StateManager,
    ha_adc_sensor_availabilty_message,
    ha_binary_sensor_availabilty_message,
    ha_event_availabilty_message,
    ha_sensor_temp_availabilty_message,
    refresh_wrapper,
)
from boneio.helper.ha_discovery import (
    ha_sensor_availability_message,
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
from boneio.sensor import DallasSensorDS2482, GpioADCSensor
from boneio.sensor.serial_number import SerialNumberSensor
from boneio.sensor.temp.dallas import DallasSensorW1

if TYPE_CHECKING:
    from boneio.gpio import GpioEventButtonsAndSensors
    from boneio.gpio_manager import GpioManager
    from boneio.manager import Manager
    from boneio.sensor.temp.lm75 import LM75Sensor
    from boneio.sensor.temp.mcp9808 import MCP9808Sensor

_LOGGER = logging.getLogger(__name__)


def create_adc(
    manager: Manager,
    message_bus: MessageBus,
    topic_prefix: str,
    adc: list[AdcConfig],
):
    """Create ADC sensor."""

    for gpio in adc:
        id = gpio.id.replace(" ", "")
        try:
            sensor = GpioADCSensor(
                id=id,
                pin=gpio.pin,
                name=gpio.id,
                message_bus=message_bus,
                topic_prefix=topic_prefix,
                filters=gpio.filters,
            )
            manager.append_task(
                refresh_wrapper(sensor.update, gpio.update_interval), sensor.name
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
) -> LM75Sensor | MCP9808Sensor:
    """Create LM sensor in manager."""
    if sensor_type == LM75:
        from boneio.sensor import LM75Sensor as TempSensor
    elif sensor_type == MCP_TEMP_9808:
        from boneio.sensor import MCP9808Sensor as TempSensor
    else:
        raise ValueError(f"No {sensor_type} temperature sensor type.")
    name = config.id
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
            ha_type="sensor",
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
) -> SerialNumberSensor:
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
        availability_msg_func=ha_sensor_availability_message,
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
        id = entry.identifier()
        try:
            modbus_coordinators[id] = ModbusCoordinator(
                device_config=entry,
                manager=manager,
                message_bus=message_bus,
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
    output_config: OutputConfigKinds,
    event_bus: EventBus,
) -> BasicRelay:
    """Configure kind of relay. Most common MCP."""
    restored_state = (
        state_manager.state.relay.get(relay_id, False)
        if output_config.restore_state
        else False
    )
    if (
        output_config.output_type == NONE
        and state_manager.state.relay.get(relay_id) is not None
    ):
        state_manager.remove_relay_from_state(relay_id)
        restored_state = False

    if isinstance(output_config.interlock_group, str):
        output_config.interlock_group = [output_config.interlock_group]

    if isinstance(output_config, MockOutputConfig):
        from boneio.relay.mock import MockRelay

        expander_id = "mock"
        if expander_id not in manager.grouped_outputs_by_expander:
            manager.grouped_outputs_by_expander[expander_id] = {}

        relay = MockRelay(
            id=relay_id,
            pin_id=output_config.pin,
            expander_id=expander_id,
            topic_prefix=topic_prefix,
            message_bus=message_bus,
            event_bus=event_bus,
            name=output_config.id,
            output_type=output_config.output_type,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
        )
    elif isinstance(output_config, GpioOutputConfig):
        from boneio.gpio import GpioRelay

        expander_id = "gpio"
        if expander_id not in manager.grouped_outputs_by_expander:
            manager.grouped_outputs_by_expander[expander_id] = {}
        relay = GpioRelay(
            gpio_manager=manager.gpio_manager,
            id=relay_id,
            pin_id=output_config.pin,
            expander_id=expander_id,
            topic_prefix=topic_prefix,
            message_bus=message_bus,
            event_bus=event_bus,
            name=output_config.id,
            output_type=output_config.output_type,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
        )
    elif isinstance(output_config, McpOutputConfig):
        expander_id = output_config.mcp_id
        mcp = manager.mcp.get(expander_id)
        if mcp is None:
            _LOGGER.error("No such MCP configured!")
            return None
        relay = MCPRelay(
            mcp=mcp,
            id=relay_id,
            pin_id=output_config.pin,
            expander_id=output_config.mcp_id,
            topic_prefix=topic_prefix,
            message_bus=message_bus,
            event_bus=event_bus,
            name=output_config.id,
            output_type=output_config.output_type,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
        )
    elif isinstance(output_config, PcaOutputConfig):
        expander_id = output_config.pca_id
        pca = manager.pca.get(expander_id)
        if pca is None:
            _LOGGER.error("No such PCA configured!")
            return None
        relay = PWMPCA(
            pca=pca,
            id=relay_id,
            pin_id=output_config.pin,
            expander_id=expander_id,
            topic_prefix=topic_prefix,
            message_bus=message_bus,
            event_bus=event_bus,
            name=output_config.id,
            output_type=output_config.output_type,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
            percentage_default_brightness=output_config.percentage_default_brightness,
        )
    elif isinstance(output_config, PcfOutputConfig):
        expander_id = output_config.pcf_id
        pcf = manager.pcf.get(expander_id)
        if not pcf:
            _LOGGER.error("No such PCF configured!")
            return None
        relay = PCFRelay(
            pcf=pcf,
            id=relay_id,
            pin_id=output_config.pin,
            expander_id=expander_id,
            topic_prefix=topic_prefix,
            message_bus=message_bus,
            event_bus=event_bus,
            name=output_config.id,
            output_type=output_config.output_type,
            restored_state=restored_state,
            interlock_manager=manager.interlock_manager,
            interlock_groups=output_config.interlock_group,
        )
    else:
        assert_never(output_config.kind)

    manager.interlock_manager.register(relay, output_config.interlock_group)
    manager.grouped_outputs_by_expander[expander_id][relay_id] = relay
    if relay.is_virtual_power:
        manager.send_ha_autodiscovery(
            id=f"{relay_id}_virtual_power",
            relay_id=relay_id,
            name=f"{output_config.id} Virtual Power",
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
            name=f"{output_config.id} Virtual Energy",
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
            name=f"{output_config.id} Virtual Volume Flow Rate",
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
            name=f"{output_config.id} Virtual consumption",
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
    event_config: EventConfig,
    gpio_manager: GpioManager,
    manager_press_callback: Callable,
    event_bus: EventBus,
    send_ha_autodiscovery: Callable,
    input: GpioEventButtonsAndSensors | None = None,
) -> GpioEventButtonsAndSensors:
    """Configure input sensor or button."""
    from boneio.gpio import GpioEventButtonNew, GpioEventButtonOld

    if input:
        GpioEventButtonClass = (
            GpioEventButtonNew
            if event_config.detection_type == "new"
            else GpioEventButtonOld
        )
        if not isinstance(input, GpioEventButtonClass):
            _LOGGER.warning(
                "You reconfigured type of input. It's forbidden. Please restart boneIO."
            )
            return input
        input.actions = event_config.actions
    else:
        if event_config.detection_type == "new":
            input = GpioEventButtonNew(
                config=event_config,
                manager_press_callback=manager_press_callback,
                event_bus=event_bus,
                gpio_manager=gpio_manager,
            )
        else:
            input = GpioEventButtonOld(
                config=event_config,
                manager_press_callback=manager_press_callback,
                event_bus=event_bus,
                gpio_manager=gpio_manager,
            )
    if event_config.show_in_ha:
        send_ha_autodiscovery(
            id=event_config.pin,
            name=event_config.identifier(),
            ha_type=EVENT_ENTITY,
            device_class=event_config.device_class,
            availability_msg_func=ha_event_availabilty_message,
        )
    return input


def configure_binary_sensor(
    sensor_config: BinarySensorConfig,
    manager_press_callback: Callable,
    event_bus: EventBus,
    send_ha_autodiscovery: Callable,
    gpio_manager: GpioManager,
    input: GpioEventButtonsAndSensors | None = None,
) -> GpioEventButtonsAndSensors:
    """Configure input sensor or button."""
    from boneio.gpio import GpioInputBinarySensorNew, GpioInputBinarySensorOld

    if input:
        GpioInputBinarySensorClass = (
            GpioInputBinarySensorNew
            if sensor_config.detection_type == "new"
            else GpioInputBinarySensorOld
        )
        if not isinstance(input, GpioInputBinarySensorClass):
            _LOGGER.warning(
                "You preconfigured type of input. It's forbidden. Please restart boneIO."
            )
            return input
        input.actions = sensor_config.actions
    else:
        if sensor_config.detection_type == "new":
            input = GpioInputBinarySensorNew(
                config=sensor_config,
                manager_press_callback=manager_press_callback,
                event_bus=event_bus,
                gpio_manager=gpio_manager,
            )
        else:
            input = GpioInputBinarySensorOld(
                config=sensor_config,
                manager_press_callback=manager_press_callback,
                event_bus=event_bus,
                gpio_manager=gpio_manager,
            )

    if sensor_config.show_in_ha:
        send_ha_autodiscovery(
            id=sensor_config.pin,
            name=sensor_config.identifier(),
            ha_type=BINARY_SENSOR,
            device_class=sensor_config.device_class,
            availability_msg_func=ha_binary_sensor_availabilty_message,
        )
    return input


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
