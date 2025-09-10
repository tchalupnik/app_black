from __future__ import annotations

import logging
import time
import typing
from collections import namedtuple
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from adafruit_mcp230xx.mcp23017 import MCP23017
from adafruit_pca9685 import PCA9685
from busio import I2C

from boneio.config import (
    AdcConfig,
    BinarySensorActionTypes,
    BinarySensorConfig,
    Config,
    EventActionTypes,
    EventConfig,
    Ina219Config,
    OutputConfig,
    SensorConfig,
    TemperatureConfig,
)
from boneio.const import (
    ADDRESS,
    BINARY_SENSOR,
    COVER,
    DEVICE_CLASS,
    EVENT_ENTITY,
    GPIO,
    ID,
    INIT_SLEEP,
    INPUT,
    INPUT_SENSOR,
    LM75,
    MCP,
    MCP_ID,
    MCP_TEMP_9808,
    MODEL,
    NONE,
    PCA,
    PCA_ID,
    PCF,
    PCF_ID,
    RELAY,
    RESTORE_STATE,
    SENSOR,
    SHOW_HA,
    UPDATE_INTERVAL,
    DallasBusTypes,
    ExpanderTypes,
)
from boneio.cover import PreviousCover, TimeBasedCover, VenetianCover
from boneio.gpio import (
    GpioEventButtonNew,
    GpioEventButtonOld,
    GpioInputBinarySensorNew,
    GpioInputBinarySensorOld,
    GpioRelay,
)
from boneio.group import OutputGroup
from boneio.helper import (
    CoverConfigurationException,
    GPIOInputException,
    GPIOOutputException,
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
from boneio.helper.pcf8575 import PCF8575
from boneio.message_bus.basic import MessageBus
from boneio.modbus.client import Modbus
from boneio.modbus.coordinator import ModbusCoordinator
from boneio.relay import PWMPCA, MCPRelay, PCFRelay
from boneio.relay.basic import BasicRelay
from boneio.sensor import DallasSensorDS2482, GpioADCSensor, initialize_adc
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


expander_class = {MCP: MCP23017, PCA: PCA9685, PCF: PCF8575}


def create_expander(
    expander_dict: dict,
    expander_config: list,
    exp_type: ExpanderTypes,
    i2cbusio: I2C,
) -> dict:
    grouped_outputs = {}
    for expander in expander_config:
        id = expander[ID] or expander[ADDRESS]
        try:
            expander_dict[id] = expander_class[exp_type](
                i2c=i2cbusio, address=expander[ADDRESS], reset=False
            )
            sleep_time = expander.get(INIT_SLEEP, timedelta(seconds=0))
            if sleep_time.total_seconds() > 0:
                _LOGGER.debug(
                    "Sleeping for %s while %s %s is initializing.",
                    sleep_time.total_seconds(),
                    exp_type,
                    id,
                )
                time.sleep(sleep_time.total_seconds())
            else:
                _LOGGER.debug("%s %s is initializing.", exp_type, id)
            grouped_outputs[id] = {}
        except TimeoutError as err:
            _LOGGER.error("Can't connect to %s %s. %s", exp_type, id, err)
    return grouped_outputs


def create_modbus_coordinators(
    manager: Manager,
    message_bus: MessageBus,
    event_bus: EventBus,
    entries: dict,
    modbus: Modbus,
    config: Config,
) -> dict[str, ModbusCoordinator]:
    """Create Modbus sensor for each device."""

    modbus_coordinators = {}
    for entry in entries:
        name = entry.get(ID)
        id = name.replace(" ", "")
        additional_data = entry.get("data", {})
        try:
            modbus_coordinators[id.lower()] = ModbusCoordinator(
                address=entry[ADDRESS],
                id=id,
                name=name,
                manager=manager,
                model=entry[MODEL],
                message_bus=message_bus,
                update_interval=entry.get(UPDATE_INTERVAL, timedelta(seconds=60)),
                sensors_filters=entry.get("sensors_filters", {}),
                additional_data=additional_data,
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


OutputEntry = namedtuple("OutputEntry", "OutputClass output_kind expander_id")


def output_chooser(output_kind: str, config):
    """Get named tuple based on input."""
    if output_kind == MCP:
        expander_id = config.pop(MCP_ID, None)
        return OutputEntry(MCPRelay, MCP, expander_id)
    elif output_kind == GPIO:
        return OutputEntry(GpioRelay, GPIO, GPIO)
    elif output_kind == PCA:
        expander_id = config.pop(PCA_ID, None)
        return OutputEntry(PWMPCA, PCA, expander_id)
    elif output_kind == PCF:
        expander_id = config.pop(PCF_ID, None)
        return OutputEntry(PCFRelay, PCF, expander_id)
    else:
        raise GPIOOutputException(f"""Output type {output_kind} dont exists""")


def configure_output_group(
    message_bus: MessageBus,
    topic_prefix: str,
    config: dict,
    **kwargs,
) -> Any:
    """Configure kind of relay. Most common MCP."""
    _id = config.pop(ID)

    output = OutputGroup(
        message_bus=message_bus,
        topic_prefix=topic_prefix,
        id=_id,
        callback=lambda: None,
        **config,
        **kwargs,
    )
    return output


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
) -> BasicRelay:
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

    output = output_chooser(output_kind=output_config.kind, config=output_config)

    if isinstance(output_config.interlock_group, str):
        output_config.interlock_group = [output_config.interlock_group]

    if output_config.kind == "gpio":
        expander_id = "gpio"
        if GPIO not in manager.grouped_outputs_by_expander:
            manager.grouped_outputs_by_expander[GPIO] = {}
        relay = GpioRelay(
            pin=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager._interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
        )
    elif output_config.kind == "mcp":
        expander_id = "mcp_id"
        if output_config.mcp_id is None:
            _LOGGER.error("No MCP id configured!")
            return None
        mcp = manager.mcp.get(output_config.mcp_id)
        if not mcp:
            _LOGGER.error("No such MCP configured!")
            return None
        relay = MCPRelay(
            pin=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager._interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
            mcp=mcp,
            mcp_id=output_config.mcp_id,
            output_type=output_config.output_type,
        )
    elif output_config.kind == "pca":
        expander_id = "pca_id"
        if output_config.pca_id is None:
            _LOGGER.error("No PCA id configured!")
            return None
        pca = manager.pca.get(output_config.pca_id)
        if not pca:
            _LOGGER.error("No such PCA configured!")
            return None
        relay = PWMPCA(
            pin=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager._interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
            pca=pca,
            pca_id=output_config.pca_id,
            output_type=output_config.output_type,
        )
    elif output_config.kind == "pcf":
        expander_id = "pcf_id"
        if output_config.pcf_id is None:
            _LOGGER.error("No PCF id configured!")
            return None
        expander = manager.pcf.get(output_config.pcf_id)
        if not expander:
            _LOGGER.error("No such PCF configured!")
            return None
        relay = PCFRelay(
            pin=output_config.pin,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            id=relay_id,
            restored_state=restored_state,
            interlock_manager=manager._interlock_manager,
            interlock_groups=output_config.interlock_group,
            name=name,
            event_bus=event_bus,
            output_type=output_config.output_type,
        )
    else:
        _LOGGER.error(
            "Output kind: %s is not configured", getattr(output, "output_kind")
        )
        return None

    manager._interlock_manager.register(relay, output_config.interlock_group)
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
    manager_press_callback: Callable,
    event_bus: EventBus,
    send_ha_autodiscovery: Callable,
    actions: dict[
        EventActionTypes | BinarySensorActionTypes, list[dict[str, typing.Any]]
    ],
    input: GpioEventButtonOld
    | GpioEventButtonNew
    | GpioInputBinarySensorOld
    | GpioInputBinarySensorNew
    | None = None,
) -> GpioEventButtonOld | GpioEventButtonNew | None:
    """Configure input sensor or button."""
    try:
        gpioEventButtonClass = (
            GpioEventButtonNew if gpio.detection_type == "new" else GpioEventButtonOld
        )
        name = gpio.id or gpio.pin
        if input:
            if not isinstance(input, gpioEventButtonClass):
                _LOGGER.warning(
                    "You reconfigured type of input. It's forbidden. Please restart boneIO."
                )
                return input
            input.set_actions(actions=actions)
        else:
            input = gpioEventButtonClass(
                pin=gpio.pin,
                name=name,
                input_type=INPUT,
                empty_message_after=gpio.clear_message,
                actions=actions,
                manager_press_callback=manager_press_callback,
                event_bus=event_bus,
                gpio=gpio,
            )
        if gpio.show_in_ha:
            send_ha_autodiscovery(
                id=gpio.pin,
                name=name,
                ha_type=EVENT_ENTITY,
                device_class=gpio.device_class,
                availability_msg_func=ha_event_availabilty_message,
            )
        return input
    except GPIOInputException as err:
        _LOGGER.error("This PIN %s can't be configured. %s", gpio.pin, err)


def configure_binary_sensor(
    gpio: BinarySensorConfig,
    manager_press_callback: Callable,
    event_bus: EventBus,
    send_ha_autodiscovery: Callable,
    actions: dict[
        EventActionTypes | BinarySensorActionTypes, list[dict[str, typing.Any]]
    ],
    input: GpioEventButtonOld
    | GpioEventButtonNew
    | GpioInputBinarySensorOld
    | GpioInputBinarySensorNew
    | None = None,
) -> GpioInputBinarySensorOld | GpioInputBinarySensorNew | None:
    """Configure input sensor or button."""
    try:
        GpioInputBinarySensorClass = (
            GpioInputBinarySensorNew
            if gpio.detection_type == "new"
            else GpioInputBinarySensorOld
        )
        name = gpio.id or gpio.pin
        if input:
            if not isinstance(input, GpioInputBinarySensorClass):
                _LOGGER.warning(
                    "You preconfigured type of input. It's forbidden. Please restart boneIO."
                )
                return input
            input.set_actions(actions=actions)
        else:
            input = GpioInputBinarySensorClass(
                pin=gpio.pin,
                name=name,
                actions=actions,
                input_type=INPUT_SENSOR,
                empty_message_after=gpio.clear_message,
                manager_press_callback=manager_press_callback,
                event_bus=event_bus,
                gpio=gpio,
            )
        if gpio.show_in_ha:
            send_ha_autodiscovery(
                id=gpio.pin,
                name=name,
                ha_type=BINARY_SENSOR,
                device_class=gpio.device_class,
                availability_msg_func=ha_binary_sensor_availabilty_message,
            )
        return input
    except GPIOInputException as err:
        _LOGGER.error("This PIN %s can't be configured. %s", gpio.pin, err)


def configure_cover(
    message_bus: MessageBus,
    cover_id: str,
    state_manager: StateManager,
    send_ha_autodiscovery: Callable,
    config: dict,
    tilt_duration: timedelta | None,
    open_relay: BasicRelay,
    close_relay: BasicRelay,
    open_time: int,
    close_time: int,
    event_bus: EventBus,
    topic_prefix: str,
) -> PreviousCover | TimeBasedCover:
    platform = config.get("platform", "previous")

    def state_save(value: dict[str, int]):
        if config[RESTORE_STATE]:
            state_manager.save_attribute(
                attr_type=COVER,
                attribute=cover_id,
                value=value,
            )

    if platform == "venetian":
        if not tilt_duration:
            raise CoverConfigurationException(
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
            tilt_duration=tilt_duration,
            actuator_activation_duration=config.get(
                "actuator_activation_duration", timedelta(milliseconds=0)
            ),
            open_relay=open_relay,
            close_relay=close_relay,
            open_time=open_time,
            close_time=close_time,
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
            open_time=open_time,
            close_time=close_time,
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
            open_time=open_time,
            close_time=close_time,
            event_bus=event_bus,
            topic_prefix=topic_prefix,
        )
        availability_msg_func = ha_cover_availabilty_message
    if config.get(SHOW_HA, True):
        send_ha_autodiscovery(
            id=cover.id,
            name=cover.name,
            ha_type=COVER,
            device_class=config.get(DEVICE_CLASS),
            availability_msg_func=availability_msg_func,
        )
    _LOGGER.debug("Configured cover %s", cover_id)
    return cover


def configure_ds2482(i2cbusio: I2C, address: str = DS2482_ADDRESS) -> OneWireBus:
    ds2482 = DS2482(i2c=i2cbusio, address=address)
    ow_bus = OneWireBus(ds2482=ds2482)
    return ow_bus


def configure_dallas() -> AsyncBoneIOW1ThermSensor:
    return AsyncBoneIOW1ThermSensor


def find_onewire_devices(
    ow_bus: OneWireBus | AsyncBoneIOW1ThermSensor,
    bus_id: str,
    bus_type: DallasBusTypes,
) -> dict[OneWireAddress]:
    out = {}
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
):
    """Create INA219 sensor in manager."""
    from boneio.sensor import INA219

    address = config.address
    id = (config.id or address).replace(" ", "")
    try:
        ina219 = INA219(
            id=id,
            address=address,
            sensors=config.sensors,
            manager=manager,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            update_interval=config.update_interval,
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
    except I2CError as err:
        _LOGGER.error("Can't configure Temp sensor. %s", err)
