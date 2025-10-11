from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, assert_never

from busio import I2C

from boneio.config import (
    AdcConfig,
    Config,
    GpioOutputConfig,
    McpOutputConfig,
    MockOutputConfig,
    ModbusDeviceConfig,
    OutputConfigKinds,
    PcaOutputConfig,
    PcfOutputConfig,
    SensorConfig,
)
from boneio.events import EventBus
from boneio.helper import (
    I2CError,
    StateManager,
    ha_adc_sensor_availabilty_message,
    ha_sensor_temp_availabilty_message,
    refresh_wrapper,
)
from boneio.helper.filter import Filter
from boneio.helper.ha_discovery import ha_virtual_energy_sensor_discovery_message
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
from boneio.sensor.temp.dallas import DallasSensorW1

if TYPE_CHECKING:
    from boneio.manager import Manager

_LOGGER = logging.getLogger(__name__)


def create_adc(
    manager: Manager,
    message_bus: MessageBus,
    topic_prefix: str,
    adc: list[AdcConfig],
) -> None:
    """Create ADC sensor."""

    for gpio in adc:
        id = gpio.identifier()
        try:
            sensor = GpioADCSensor(
                id=id,
                pin=gpio.pin,
                message_bus=message_bus,
                topic_prefix=topic_prefix,
                filter=Filter(gpio.filters),
            )
            manager.append_task(
                refresh_wrapper(sensor.update, gpio.update_interval), sensor.id
            )
            if gpio.show_in_ha:
                manager.send_ha_autodiscovery(
                    id=id,
                    name=id,
                    ha_type="sensor",
                    availability_msg_func=ha_adc_sensor_availabilty_message,
                )
        except I2CError as err:
            _LOGGER.error("Can't configure ADC sensor %s. %s", id, err)


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
        coordinator = ModbusCoordinator(
            device_config=entry,
            message_bus=message_bus,
            modbus=modbus,
            event_bus=event_bus,
            config=config,
        )
        manager.append_task(refresh_wrapper(coordinator.async_update), id)
        modbus_coordinators[id] = coordinator
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
        output_config.output_type == "none"
        and state_manager.state.relay.get(relay_id) is not None
    ):
        state_manager.remove_relay_from_state(relay_id)
        restored_state = False

    if isinstance(output_config.interlock_group, str):
        output_config.interlock_group = [output_config.interlock_group]

    relay: BasicRelay
    if isinstance(output_config, MockOutputConfig):
        from boneio.relay.mock import MockRelay

        relay = MockRelay(
            id=relay_id,
            pin_id=output_config.pin,
            expander_id="mock",
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
        relay = GpioRelay(
            gpio_manager=manager.gpio_manager,
            id=relay_id,
            pin_id=output_config.pin,
            expander_id="gpio",
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
            raise ValueError("No such MCP configured!")
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
            raise ValueError("No such PCA configured!")
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
        if pcf is None:
            raise ValueError("No such PCF configured!")
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
        assert_never(output_config)

    manager.interlock_manager.register(relay, output_config.interlock_group)
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


def configure_ds2482(i2cbusio: I2C, address: str = DS2482_ADDRESS) -> OneWireBus:
    ds2482 = DS2482(i2c=i2cbusio, address=address)
    ow_bus = OneWireBus(ds2482=ds2482)
    return ow_bus


def find_onewire_devices(
    ow_bus: type[OneWireBus] | type[AsyncBoneIOW1ThermSensor],
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
            ha_type="sensor",
            availability_msg_func=ha_sensor_temp_availabilty_message,
            unit_of_measurement=config.unit_of_measurement,
        )
    return sensor
