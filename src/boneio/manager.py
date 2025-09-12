from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import typing
from collections import defaultdict, deque
from collections.abc import Callable, Coroutine
from pathlib import Path

from adafruit_mcp230xx.mcp23017 import MCP23017
from adafruit_pca9685 import PCA9685
from busio import I2C
from w1thermsensor.errors import KernelModuleLoadError

from boneio.config import (
    ActionConfig,
    AdcConfig,
    BinarySensorActionTypes,
    Config,
    DallasConfig,
    Ds2482Config,
    EventActionTypes,
    Ina219Config,
    ModbusConfig,
    ModbusDeviceConfig,
    MqttAutodiscoveryMessage,
    SensorConfig,
    TemperatureConfig,
    UartsConfig,
)
from boneio.const import (
    BINARY_SENSOR,
    BUTTON,
    CLOSE,
    COVER,
    COVER_OVER_MQTT,
    DALLAS,
    DS2482,
    EVENT_ENTITY,
    ID,
    INPUT,
    IP,
    LED,
    LIGHT,
    MQTT,
    NONE,
    ON,
    ONLINE,
    OPEN,
    OUTPUT,
    OUTPUT_OVER_MQTT,
    RELAY,
    SET_BRIGHTNESS,
    STATE,
    STOP,
    SWITCH,
    TOPIC,
    VALVE,
    cover_actions,
    relay_actions,
)
from boneio.cover import PreviousCover, TimeBasedCover
from boneio.cover.venetian import VenetianCover
from boneio.gpio import GpioEventButtonsAndSensors
from boneio.gpio_manager import GpioManager
from boneio.group.output import OutputGroup
from boneio.helper import (
    GPIOInputException,
    HostData,
    I2CError,
    StateManager,
    ha_button_availabilty_message,
    ha_led_availabilty_message,
    ha_light_availabilty_message,
    ha_switch_availabilty_message,
)
from boneio.helper.events import EventBus
from boneio.helper.exceptions import CoverConfigurationException, ModbusUartException
from boneio.helper.ha_discovery import ha_valve_availabilty_message
from boneio.helper.interlock import SoftwareInterlockManager
from boneio.helper.loader import (
    configure_binary_sensor,
    configure_cover,
    configure_event_sensor,
    configure_relay,
    create_adc,
    create_dallas_sensor,
    create_expander,
    create_modbus_coordinators,
    create_serial_number_sensor,
    create_temp_sensor,
)
from boneio.helper.logger import configure_logger
from boneio.helper.onewire.onewire import OneWireAddress
from boneio.helper.pcf8575 import PCF8575
from boneio.helper.stats import get_network_info
from boneio.helper.util import strip_accents
from boneio.helper.yaml_util import load_config_from_file
from boneio.message_bus import MessageBus
from boneio.modbus.client import Modbus
from boneio.modbus.coordinator import ModbusCoordinator
from boneio.models import OutputState
from boneio.relay.basic import BasicRelay
from boneio.sensor.temp import TempSensor

if typing.TYPE_CHECKING:
    from boneio.gpio.base import GpioBase

_LOGGER = logging.getLogger(__name__)

AVAILABILITY_FUNCTION_CHOOSER = {
    LIGHT: ha_light_availabilty_message,
    LED: ha_led_availabilty_message,
    SWITCH: ha_switch_availabilty_message,
    VALVE: ha_valve_availabilty_message,
}


class Manager:
    """Manager to communicate MQTT with GPIO inputs and outputs."""

    def __init__(
        self,
        config: Config,
        message_bus: MessageBus,
        event_bus: EventBus,
        state_manager: StateManager,
        config_file_path: Path,
        old_config: dict,
        gpio_manager: GpioManager,
    ) -> None:
        self.gpio_manager = gpio_manager
        _LOGGER.info("Initializing manager module.")

        self._loop = asyncio.get_event_loop()
        self.config = config
        self._host_data: HostData | None = None
        self._config_file_path = config_file_path
        self._state_manager = state_manager
        self._event_bus = event_bus
        self.message_bus = message_bus
        self._inputs: dict[str, GpioEventButtonsAndSensors] = {}
        from board import SCL, SDA

        self._i2cbusio = I2C(SCL, SDA)
        self._mcp = {}
        self._pcf = {}
        self._pca = {}
        self.outputs: dict[str, BasicRelay] = {}
        self.output_groups: dict[str, OutputGroup] = {}
        self.interlock_manager = SoftwareInterlockManager()

        self.tasks: list[asyncio.Task] = []
        self.covers: dict[str, PreviousCover | TimeBasedCover | VenetianCover] = {}
        self.temp_sensors: list[TempSensor] = []
        self.ina219_sensors = []
        self.modbus_coordinators = {}
        self.modbus: Modbus | None = None

        if config.modbus is not None:
            self._configure_modbus(modbus=config.modbus)

        if config.lm75 is not None:
            self._configure_temp_sensors(sensor_type="lm75", sensors=config.lm75)
        if config.mcp9808 is not None:
            self._configure_temp_sensors(sensor_type="mcp9808", sensors=config.mcp9808)

        self.modbus_coordinators = {}
        if config.ina219 is not None:
            self._configure_ina219_sensors(sensors=config.ina219)
        self._configure_sensors(
            dallas=config.dallas, ds2482=config.ds2482, sensors=config.sensor
        )

        self.grouped_outputs_by_expander = create_expander(
            expander_dict=self._mcp,
            expander_config=config.mcp23017,
            i2cbusio=self._i2cbusio,
            Class=MCP23017,
        )
        self.grouped_outputs_by_expander.update(
            create_expander(
                expander_dict=self._pcf,
                expander_config=config.pcf8575,
                i2cbusio=self._i2cbusio,
                Class=PCF8575,
            )
        )
        self.grouped_outputs_by_expander.update(
            create_expander(
                expander_dict=self._pca,
                expander_config=config.pca9685,
                i2cbusio=self._i2cbusio,
                Class=PCA9685,
            )
        )

        create_adc(
            manager=self,
            message_bus=self.message_bus,
            topic_prefix=self.config.mqtt.topic_prefix,
            adc=self.config.adc,
        )

        for output in config.output:
            _id = strip_accents(output.id)
            _LOGGER.debug("Configuring relay: %s", _id)
            out = configure_relay(  # grouped_output updated here.
                manager=self,
                output_config=output,
                message_bus=message_bus,
                state_manager=self._state_manager,
                topic_prefix=self.config.mqtt.topic_prefix,
                name=output.id,
                restore_state=output.restore_state,
                relay_id=_id,
                event_bus=self._event_bus,
            )
            if not out:
                continue
            if output.restore_state:
                self._event_bus.add_event_listener(
                    event_type="output",
                    entity_id=out.id,
                    listener_id="manager",
                    target=self._relay_callback,
                )
            self.outputs[_id] = out
            if out.output_type not in (NONE, COVER):
                self.send_ha_autodiscovery(
                    id=out.id,
                    name=out.name,
                    ha_type=(LIGHT if out.output_type == LED else out.output_type),
                    availability_msg_func=AVAILABILITY_FUNCTION_CHOOSER.get(
                        out.output_type, ha_switch_availabilty_message
                    ),
                )
            self._loop.create_task(self._delayed_send_state(out))

        if self.outputs:
            self._configure_covers()

        self._configure_output_group()

        _LOGGER.info("Initializing inputs. This will take a while.")
        self.configure_inputs(reload_config=False)

        self._serial_number_sensor = create_serial_number_sensor(
            manager=self,
            message_bus=self.message_bus,
            topic_prefix=self.config.mqtt.topic_prefix,
        )
        self.modbus_coordinators = self._configure_modbus_coordinators(
            devices=config.modbus_devices
        )

        if config.oled is not None and config.oled.enabled:
            from boneio.oled import Oled

            self._host_data = HostData(
                manager=self,
                event_bus=self._event_bus,
                enabled_screens=config.oled.screens,
                output=self.grouped_outputs_by_expander,
                inputs=self._inputs,
                temp_sensor=(self.temp_sensors[0] if self.temp_sensors else None),
                ina219=(self.ina219_sensors[0] if self.ina219_sensors else None),
                extra_sensors=config.oled.extra_screen_sensors,
            )
            try:
                oled = Oled(
                    host_data=self._host_data,
                    screen_order=config.oled.screens,
                    grouped_outputs_by_expander=list(self.grouped_outputs_by_expander),
                    sleep_timeout=config.oled.screensaver_timeout,
                    event_bus=self._event_bus,
                    gpio_manager=self.gpio_manager,
                )
            except (GPIOInputException, I2CError) as err:
                _LOGGER.error("Can't configure OLED display. %s", err)
            else:
                oled.render_display()
        self.prepare_ha_buttons()
        _LOGGER.info("BoneIO manager is ready.")

    def _configure_output_group(self) -> None:
        def get_outputs(output_list: list[str]) -> list[BasicRelay]:
            outputs: list[BasicRelay] = []
            for x in output_list:
                x = strip_accents(x)
                if x in self.outputs:
                    output = self.outputs[x]
                    if output.output_type == COVER:
                        _LOGGER.warning("You can't add cover output to group.")
                    else:
                        outputs.append(output)
            return outputs

        for group in self.config.output_group:
            members = get_outputs(group.outputs)
            if not members:
                _LOGGER.warning(
                    "This group %s doesn't have any valid members. Not adding it.",
                    group.id,
                )
                continue
            _LOGGER.debug(
                "Configuring output group %s with members: %s",
                group.id,
                [x.name for x in members],
            )
            output_group = OutputGroup(
                message_bus=self.message_bus,
                state_manager=self._state_manager,
                topic_prefix=self.config.mqtt.topic_prefix,
                relay_id=group.id.replace(" ", ""),
                event_bus=self._event_bus,
                members=members,
                config=group,
            )
            self.output_groups[output_group.id] = output_group
            if output_group.output_type != NONE:
                self.send_ha_autodiscovery(
                    id=output_group.id,
                    name=output_group.name,
                    ha_type=output_group.output_type,
                    availability_msg_func=AVAILABILITY_FUNCTION_CHOOSER.get(
                        output_group.output_type,
                        ha_switch_availabilty_message,
                    ),
                    device_type="group",
                    icon=(
                        "mdi:lightbulb-group"
                        if output_group.output_type == LIGHT
                        else "mdi:toggle-switch-variant"
                    ),
                )
            self.append_task(coro=output_group.event_listener, name=output_group.id)

    def _configure_covers(self, reload_config: bool = False) -> None:
        """Configure covers."""
        if reload_config:
            config = load_config_from_file(self._config_file_path)
            new_config = Config.model_validate(config)
            self.config.cover = new_config.cover
            self.config.mqtt.autodiscovery_messages.clear_type(type=COVER)
        for cover in self.config.cover:
            _id = strip_accents(cover.id)
            open_relay = self.outputs.get(cover.open_relay)
            close_relay = self.outputs.get(cover.close_relay)
            if not open_relay:
                _LOGGER.error(
                    "Can't configure cover %s. This relay doesn't exist.",
                    cover.open_relay,
                )
                continue
            if not close_relay:
                _LOGGER.error(
                    "Can't configure cover %s. This relay doesn't exist.",
                    cover.close_relay,
                )
                continue
            if open_relay.output_type != COVER or close_relay.output_type != COVER:
                _LOGGER.error(
                    "Can't configure cover %s. %s. Current types are: %s, %s",
                    _id,
                    "You have to explicitly set types of relays to Cover so you can't turn it on directly.",
                    open_relay.output_type,
                    close_relay.output_type,
                )
                continue
            try:
                if _id in self.covers:
                    _cover = self.covers[_id]
                    _cover.update_config_times(cover)
                    continue
                self.covers[_id] = configure_cover(
                    message_bus=self.message_bus,
                    cover_id=_id,
                    state_manager=self._state_manager,
                    config=cover,
                    open_relay=open_relay,
                    close_relay=close_relay,
                    event_bus=self._event_bus,
                    send_ha_autodiscovery=self.send_ha_autodiscovery,
                    topic_prefix=self.config.mqtt.topic_prefix,
                )

            except CoverConfigurationException as err:
                _LOGGER.error("Can't configure cover %s. %s", _id, err)
                continue

    def parse_actions(
        self,
        pin: str,
        actions: dict[EventActionTypes, list[ActionConfig]]
        | dict[BinarySensorActionTypes, list[ActionConfig]],
    ) -> dict[EventActionTypes | BinarySensorActionTypes, list[dict[str, typing.Any]]]:
        """Parse actions from config."""
        parsed_actions: dict[
            EventActionTypes | BinarySensorActionTypes, list[dict[str, typing.Any]]
        ] = defaultdict(list)

        for click_type, action_definitions in actions.items():
            for action_definition in action_definitions:
                if action_definition.action == OUTPUT:
                    entity_id = action_definition.pin
                    stripped_entity_id = strip_accents(entity_id)
                    action_output = action_definition.action_output
                    output = self.outputs.get(
                        stripped_entity_id,
                        self.output_groups.get(stripped_entity_id),
                    )
                    action_to_execute = relay_actions.get(action_output)
                    if output and action_to_execute:
                        _f = getattr(output, action_to_execute)
                        if _f:
                            parsed_actions[click_type].append(
                                {
                                    "action": action_definition.action,
                                    "pin": stripped_entity_id,
                                    "action_to_execute": action_to_execute,
                                }
                            )
                            continue
                    _LOGGER.warning(
                        "Device %s for action in %s not found. Omitting.",
                        entity_id,
                        pin,
                    )
                elif action_definition.action == COVER:
                    entity_id = action_definition.pin
                    stripped_entity_id = strip_accents(entity_id)
                    action_cover = action_definition.action_cover
                    extra_data = action_definition.data
                    cover = self.covers.get(stripped_entity_id)
                    action_to_execute = cover_actions.get(action_cover)
                    if cover and action_to_execute:
                        _f = getattr(cover, action_to_execute)
                        if _f:
                            parsed_actions[click_type].append(
                                {
                                    "action": action_definition.action,
                                    "action_to_execute": action_to_execute,
                                    "extra_data": extra_data,
                                }
                            )
                            continue
                    _LOGGER.warning(
                        "Device %s for action not found. Omitting.", entity_id
                    )
                elif action_definition.action == MQTT:
                    action_mqtt_msg = action_definition.action_mqtt_msg
                    action_topic = action_definition.topic
                    if action_topic and action_mqtt_msg:
                        parsed_actions[click_type].append(
                            {
                                "action": action_definition.action,
                                "action_mqtt_msg": action_mqtt_msg,
                                "action_topic": action_topic,
                            }
                        )
                        continue
                    _LOGGER.warning(
                        "Device %s for action not found. Omitting.", entity_id
                    )
                elif action_definition.action == OUTPUT_OVER_MQTT:
                    boneio_id = action_definition.boneio_id
                    action_output = action_definition.action_output
                    action_to_execute = relay_actions.get(action_output.upper())
                    if boneio_id and action_to_execute:
                        parsed_actions[click_type].append(
                            {
                                "action": action_definition.action,
                                "boneio_id": boneio_id,
                                "action_output": action_output,
                            }
                        )
                        continue
                    _LOGGER.warning(
                        "Device %s for action not found. Omitting.", entity_id
                    )
                elif action_definition.action == COVER_OVER_MQTT:
                    boneio_id = action_definition.boneio_id
                    action_cover = action_definition.action_cover
                    action_to_execute = cover_actions.get(action_cover.upper())
                    if boneio_id and action_to_execute:
                        parsed_actions[click_type].append(
                            {
                                "action": action_definition.action,
                                "boneio_id": boneio_id,
                                "action_cover": action_cover,
                            }
                        )
                        continue
                    _LOGGER.warning(
                        "Device %s for action not found. Omitting.", entity_id
                    )
        return parsed_actions

    def configure_inputs(self, reload_config: bool = False) -> None:
        """Configure inputs. Either events or binary sensors."""

        def check_if_pin_configured(pin: str) -> bool:
            if pin in self._inputs:
                if not reload_config:
                    _LOGGER.warning(
                        "This PIN %s is already configured. Omitting it.", pin
                    )
                    return True
            return False

        if reload_config:
            config_dict = load_config_from_file(self._config_file_path)
            if config_dict is not None:
                new_config = Config.model_validate(config_dict)
                self.config.event = new_config.event
                self.config.binary_sensor = new_config.binary_sensor
                self.config.mqtt.autodiscovery_messages.clear_type(type=EVENT_ENTITY)
                self.config.mqtt.autodiscovery_messages.clear_type(type=BINARY_SENSOR)
        for gpio in self.config.event:
            if check_if_pin_configured(pin=gpio.pin):
                return
            input = configure_event_sensor(
                gpio=gpio,
                manager_press_callback=self.press_callback,
                event_bus=self._event_bus,
                send_ha_autodiscovery=self.send_ha_autodiscovery,
                input=self._inputs.get(gpio.pin),  # for reload actions.
                actions=self.parse_actions(gpio.pin, gpio.actions),
                gpio_manager=self.gpio_manager,
            )
            if input:
                self._inputs[input.pin] = input

        for gpio in self.config.binary_sensor:
            if check_if_pin_configured(pin=gpio.pin):
                return
            input = configure_binary_sensor(
                gpio=gpio,
                manager_press_callback=self.press_callback,
                event_bus=self._event_bus,
                send_ha_autodiscovery=self.send_ha_autodiscovery,
                input=self._inputs.get(gpio.pin),  # for reload actions.
                actions=self.parse_actions(gpio.pin, gpio.actions),
                gpio_manager=self.gpio_manager,
            )
            if input:
                self._inputs[input.pin] = input

    def append_task(self, coro: Coroutine, name: str = "Unknown") -> asyncio.Task:
        """Add task to run with asyncio loop."""
        _LOGGER.debug("Appending update task for %s", name)
        task: asyncio.Task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    @property
    def inputs(self) -> list[GpioBase]:
        return list(self._inputs.values())

    def _configure_sensors(
        self,
        dallas: DallasConfig | None,
        ds2482: list[Ds2482Config],
        sensors: list[SensorConfig],
    ) -> None:
        """
        Configure Dallas sensors via GPIO PIN bus or DS2482 bus.
        """
        if not ds2482 and not dallas:
            return
        from boneio.helper.loader import (
            find_onewire_devices,
        )

        _one_wire_devices: dict[int, OneWireAddress] = {}
        _ds_onewire_bus = {}

        for _single_ds in ds2482:
            _LOGGER.debug("Preparing DS2482 bus at address %s.", _single_ds.address)
            from boneio.helper.loader import (
                configure_ds2482,
            )

            _ds_onewire_bus[_single_ds.id] = configure_ds2482(
                i2cbusio=self._i2cbusio, address=_single_ds.address
            )
            _one_wire_devices.update(
                find_onewire_devices(
                    ow_bus=_ds_onewire_bus[_single_ds.id],
                    bus_id=_single_ds.id,
                    bus_type=DS2482,
                )
            )
        if dallas is not None:
            _LOGGER.debug("Preparing Dallas bus.")
            from boneio.helper.loader import configure_dallas

            try:
                from w1thermsensor.kernel import load_kernel_modules

                load_kernel_modules()

                _one_wire_devices.update(
                    find_onewire_devices(
                        ow_bus=configure_dallas(),
                        bus_id=dallas.id,
                        bus_type=DALLAS,
                    )
                )
            except KernelModuleLoadError as err:
                _LOGGER.error("Can't configure Dallas W1 device %s", err)

        for sensor in sensors:
            address = _one_wire_devices.get(sensor.address)
            if not address:
                continue
            bus = None
            if sensor.bus_id and sensor.bus_id in _ds_onewire_bus:
                bus = _ds_onewire_bus[sensor.bus_id]
            _LOGGER.debug("Configuring sensor %s for boneIO", address)
            self.temp_sensors.append(
                create_dallas_sensor(
                    manager=self,
                    message_bus=self.message_bus,
                    address=address,
                    topic_prefix=self.config.mqtt.topic_prefix,
                    config=sensor,
                    bus=bus,
                )
            )

    def _configure_adc(self, adc: list[AdcConfig]) -> None:
        create_adc(
            manager=self,
            message_bus=self.message_bus,
            topic_prefix=self.config.mqtt.topic_prefix,
            adc=adc,
        )

    def _configure_modbus(self, modbus: ModbusConfig) -> None:
        uart = modbus.uart
        if uart in UartsConfig:
            try:
                self.modbus = Modbus(
                    uart=UartsConfig[uart],
                    baudrate=modbus.baudrate,
                    stopbits=modbus.stopbits,
                    bytesize=modbus.bytesize,
                    parity=modbus.parity,
                )
            except ModbusUartException:
                _LOGGER.error(
                    "This UART %s can't be used for modbus communication.",
                    uart,
                )
                self.modbus = None

    def _configure_temp_sensors(
        self,
        sensor_type: typing.Literal["lm75", "mcp9808"],
        sensors: list[TemperatureConfig],
    ) -> None:
        for sensor in sensors:
            temp_sensor = create_temp_sensor(
                manager=self,
                message_bus=self.message_bus,
                topic_prefix=self.config.mqtt.topic_prefix,
                sensor_type=sensor_type,
                config=sensor,
                i2cbusio=self._i2cbusio,
            )
            if temp_sensor:
                self.temp_sensors.append(temp_sensor)

    def _configure_ina219_sensors(self, sensors: list[Ina219Config]) -> None:
        from boneio.helper.loader import create_ina219_sensor

        for sensor_config in sensors:
            ina219 = create_ina219_sensor(
                topic_prefix=self.config.mqtt.topic_prefix,
                manager=self,
                message_bus=self.message_bus,
                config=sensor_config,
            )
            if ina219:
                self.ina219_sensors.append(ina219)

    def _configure_modbus_coordinators(
        self, devices: list[ModbusDeviceConfig]
    ) -> dict[str, ModbusCoordinator]:
        if self.modbus is not None:
            return create_modbus_coordinators(
                manager=self,
                message_bus=self.message_bus,
                event_bus=self._event_bus,
                entries=devices,
                modbus=self.modbus,
                config=self.config,
            )
        return {}

    async def reconnect_callback(self) -> None:
        """Function to invoke when connection to MQTT is (re-)established."""
        _LOGGER.info("Sending online state.")
        topic = f"{self.config.mqtt.topic_prefix}/{STATE}"
        self.message_bus.send_message(topic=topic, payload=ONLINE, retain=True)

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def _relay_callback(
        self,
        event: OutputState,
    ) -> None:
        """Relay callback function."""
        self._state_manager.save_attribute(
            attr_type=RELAY,
            attribute=event.id,
            value=event.state == ON,
        )

    def _logger_reload(self) -> None:
        """_Logger reload function."""
        _config = load_config_from_file(config_file=self._config_file_path)
        if not _config:
            return
        configure_logger(log_config=_config.get("logger"), debug=-1)

    def prepare_ha_buttons(self) -> None:
        """Prepare HA buttons for reload."""
        self.send_ha_autodiscovery(
            id="logger",
            name="Logger reload",
            ha_type=BUTTON,
            availability_msg_func=ha_button_availabilty_message,
            entity_category="config",
        )
        self.send_ha_autodiscovery(
            id="restart",
            name="Restart boneIO",
            ha_type=BUTTON,
            payload_press="restart",
            availability_msg_func=ha_button_availabilty_message,
            entity_category="config",
        )
        self.send_ha_autodiscovery(
            id="inputs_reload",
            name="Reload actions",
            ha_type=BUTTON,
            payload_press="inputs_reload",
            availability_msg_func=ha_button_availabilty_message,
            entity_category="config",
        )
        if self.covers:
            self.send_ha_autodiscovery(
                id="cover_reload",
                name="Reload times of covers",
                ha_type=BUTTON,
                payload_press="cover_reload",
                availability_msg_func=ha_button_availabilty_message,
                entity_category="config",
            )

    @property
    def mcp(self):
        """Get MCP by it's id."""
        return self._mcp

    @property
    def pca(self):
        """Get PCA by it's id."""
        return self._pca

    @property
    def pcf(self):
        """Get PCF by it's id."""
        return self._pcf

    async def press_callback(
        self,
        x: EventActionTypes | BinarySensorActionTypes,
        gpio: GpioBase,
        empty_message_after: bool = False,
        duration: float | None = None,
        start_time: float | None = None,
    ) -> None:
        """Press callback to use in input gpio.
        If relay input map is provided also toggle action on relay or cover or mqtt.
        """
        actions = gpio.get_actions_of_click(click_type=x)
        topic = f"{self.config.mqtt.topic_prefix}/{gpio.input_type}/{gpio.pin}"

        def generate_payload():
            if gpio.input_type == INPUT:
                if duration:
                    return {"event_type": x, "duration": duration}
                return {"event_type": x}
            return x

        for action_definition in actions:
            entity_id = action_definition.get("pin")
            action = action_definition.get("action")

            if action == MQTT:
                action_topic = action_definition.get(TOPIC)
                action_payload = action_definition.get("action_mqtt_msg")
                if action_topic and action_payload:
                    self.message_bus.send_message(
                        topic=action_topic, payload=action_payload, retain=False
                    )
                continue
            elif action == OUTPUT:
                output = self.outputs.get(entity_id, self.output_groups.get(entity_id))
                action_to_execute = action_definition.get("action_to_execute")
                duration = None
                if start_time is not None:
                    duration = time.time() - start_time
                _LOGGER.debug(
                    "Executing action %s for output %s. Duration: %s",
                    action_to_execute,
                    output.name,
                    duration,
                )
                _f = getattr(output, action_to_execute)
                await _f()
            elif action == COVER:
                cover = self.covers.get(entity_id)
                action_to_execute = action_definition.get("action_to_execute")
                extra_data = action_definition.get("extra_data", {})
                duration = None
                if start_time is not None:
                    duration = time.time() - start_time
                _LOGGER.debug(
                    "Executing action %s for cover %s. Duration: %s",
                    action_to_execute,
                    cover.name,
                    duration,
                )
                _f = getattr(cover, action_to_execute)
                await _f(**extra_data)
            elif action == OUTPUT_OVER_MQTT:
                boneio_id = action_definition.get("boneio_id")
                self.message_bus.send_message(
                    topic=f"{boneio_id}/cmd/relay/{entity_id}/set",
                    payload=action_definition.get("action_output"),
                    retain=False,
                )
            elif action == COVER_OVER_MQTT:
                boneio_id = action_definition.get("boneio_id")
                self.message_bus.send_message(
                    topic=f"{boneio_id}/cmd/cover/{entity_id}/set",
                    payload=action_definition.get("action_cover"),
                    retain=False,
                )

        payload = generate_payload()
        _LOGGER.debug("Sending message %s for input %s", payload, topic)
        self.message_bus.send_message(topic=topic, payload=payload, retain=False)
        # This is similar how Z2M is clearing click sensor.
        if empty_message_after:
            self._loop.call_soon_threadsafe(
                self._loop.call_later, 0.2, self.message_bus.send_message, topic, ""
            )

    async def toggle_output(self, output_id: str) -> str:
        """Toggle output state."""
        output = self.outputs.get(output_id)
        if output:
            if output.output_type == NONE or output.output_type == COVER:
                return "not_allowed"
            if not output.check_interlock():
                return "interlock"
            await output.async_toggle()
            return "success"
        return "not_found"

    async def receive_message(self, topic: str, message: str) -> None:
        """Callback for receiving action from Mqtt."""
        _LOGGER.debug("Processing topic %s with message %s.", topic, message)
        if topic.startswith(f"{self.config.mqtt.ha_discovery.topic_prefix}/status"):
            if message == ONLINE:
                self.resend_autodiscovery()
                self._event_bus.signal_ha_online()
            return
        try:
            assert topic.startswith(self.config.mqtt.cmd_topic_prefix())
        except AssertionError as err:
            _LOGGER.error("Wrong topic %s. Error %s", topic, err)
            return
        topic_parts_raw = topic[len(self.config.mqtt.cmd_topic_prefix()) :].split("/")
        topic_parts = deque(topic_parts_raw)
        try:
            msg_type = topic_parts.popleft()
            device_id = topic_parts.popleft()
            command = topic_parts.pop()
            _LOGGER.debug(
                "Divide topic to: msg_type: %s, device_id: %s, command: %s",
                msg_type,
                device_id,
                command,
            )
        except IndexError:
            _LOGGER.error("Part of topic is missing. Not invoking command.")
            return
        if msg_type == RELAY and command == "set":
            target_device = self.outputs.get(device_id)

            if target_device and target_device.output_type != NONE:
                action_from_msg = relay_actions.get(message.upper())
                if action_from_msg:
                    _f = getattr(target_device, action_from_msg)
                    await _f()
                else:
                    _LOGGER.debug("Action not exist %s.", message.upper())
            else:
                _LOGGER.debug("Target device not found %s.", device_id)
        elif msg_type == RELAY and command == SET_BRIGHTNESS:
            target_device = self.outputs.get(device_id)
            if target_device and target_device.output_type != NONE and message != "":
                target_device.set_brightness(int(message))
            else:
                _LOGGER.debug("Target device not found %s.", device_id)
        elif msg_type == COVER:
            cover = self.covers.get(device_id)
            if not cover:
                return
            if command == "set":
                if message in (
                    OPEN,
                    CLOSE,
                    STOP,
                    "toggle",
                    "toggle_open",
                    "toggle_close",
                ):
                    _f = getattr(cover, message.lower())
                    await _f()
            elif command == "pos":
                try:
                    await cover.set_cover_position(position=int(message))
                except ValueError as err:
                    _LOGGER.warning(err)
            elif command == "tilt":
                if message == STOP:
                    await cover.stop()
                else:
                    try:
                        await cover.set_tilt(tilt_position=int(message))
                    except ValueError as err:
                        _LOGGER.warning(err)
        elif msg_type == "group" and command == "set":
            target_device = self.output_groups.get(device_id)
            if target_device and target_device.output_type != NONE:
                action_from_msg = relay_actions.get(message.upper())
                if action_from_msg:
                    asyncio.create_task(getattr(target_device, action_from_msg)())
                else:
                    _LOGGER.debug("Action not exist %s.", message.upper())
            else:
                _LOGGER.debug("Target device not found %s.", device_id)
        elif msg_type == BUTTON and command == "set":
            if device_id == "logger" and message == "reload":
                _LOGGER.info("Reloading logger configuration.")
                self._logger_reload()
            elif device_id == "restart" and message == "restart":
                await self.restart_request()
            elif device_id == "inputs_reload" and message == "inputs_reload":
                _LOGGER.info("Reloading events and binary sensors actions")
                self.configure_inputs(reload_config=True)
            elif device_id == "cover_reload" and message == "cover_reload":
                _LOGGER.info("Reloading covers actions")
                self._configure_covers(reload_config=True)
        elif msg_type == "modbus" and command == "set":
            target_device = self.modbus_coordinators.get(device_id)
            if target_device:
                if isinstance(message, str):
                    message = json.loads(message)
                    if "device" in message and "value" in message:
                        await target_device.write_register(
                            value=message["value"], entity=message["device"]
                        )

    async def restart_request(self) -> None:
        _LOGGER.info("Restarting process. Systemd should restart it soon.")
        os._exit(0)  # Terminate the process

    async def _delayed_send_state(self, output: BasicRelay) -> None:
        """Send state after a delay."""
        await asyncio.sleep(0.5)
        await output.async_send_state()

    async def handle_actions(self, actions: dict) -> None:
        """Handle actions."""
        for action in actions:
            if action == MQTT:
                topic = actions[action].get(TOPIC)
                payload = actions[action].get("payload")
                if topic and payload:
                    self.message_bus.send_message(
                        topic=topic, payload=payload, retain=False
                    )
            elif action == OUTPUT:
                output_id = actions[action].get(ID)
                output_action = actions[action].get("action")
                output = self.outputs.get(output_id)
                if output and output_action:
                    _f = getattr(output, output_action)
                    await _f()
            elif action == COVER:
                cover_id = actions[action].get(ID)
                cover_action = actions[action].get("action")
                cover = self.covers.get(cover_id)
                if cover and cover_action:
                    _f = getattr(cover, cover_action)
                    await _f()

    def send_ha_autodiscovery(
        self,
        id: str,
        name: str,
        ha_type: str,
        availability_msg_func: Callable,
        topic_prefix: str | None = None,
        **kwargs,
    ) -> None:
        """Send HA autodiscovery information for each relay."""
        if not self.config.mqtt.ha_discovery.enabled:
            return
        topic_prefix = topic_prefix or self.config.mqtt.topic_prefix
        web_url = None
        if self.config.web is not None:
            network_state = get_network_info()
            if self._host_data is not None:
                web_url = self._host_data.web_url
            elif IP in network_state:
                web_url = f"http://{network_state[IP]}:{self.config.web.port}"
        payload = availability_msg_func(
            topic=topic_prefix,
            id=id,
            name=name,
            model=self.config.boneio.device_type.title(),
            device_name=self.config.boneio.name,
            web_url=web_url,
            **kwargs,
        )
        topic = f"{self.config.mqtt.ha_discovery.topic_prefix}/{ha_type}/{topic_prefix}/{id}/config"
        _LOGGER.debug("Sending HA discovery for %s entity, %s.", ha_type, name)
        self.config.mqtt.autodiscovery_messages.add_message(
            message=MqttAutodiscoveryMessage(topic=topic, payload=payload),
            type=ha_type,
        )
        self.message_bus.send_message(topic=topic, payload=payload, retain=True)

    def resend_autodiscovery(self) -> None:
        for msg in self.config.mqtt.autodiscovery_messages.root.values():
            self.message_bus.send_message(**msg.model_dump(), retain=True)
