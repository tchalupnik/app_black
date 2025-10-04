from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, assert_never

import anyio
import anyio.abc
from adafruit_mcp230xx.mcp23017 import MCP23017
from adafruit_pca9685 import PCA9685
from pydantic import BaseModel, TypeAdapter
from w1thermsensor.errors import KernelModuleLoadError

from boneio.config import (
    AdcConfig,
    BinarySensorActionTypes,
    Config,
    CoverActionConfig,
    CoverOverMqttActionConfig,
    DallasConfig,
    Ds2482Config,
    EventActionTypes,
    Ina219Config,
    Mcp23017Config,
    ModbusConfig,
    ModbusDeviceConfig,
    MqttActionConfig,
    MqttAutodiscoveryMessage,
    OutputActionConfig,
    OutputOverMqttActionConfig,
    Pca9685Config,
    Pcf8575Config,
    PreviousCoverConfig,
    SensorConfig,
    TimeBasedCoverConfig,
    UartsConfig,
    VenetianCoverConfig,
)
from boneio.cover import PreviousCover, TimeBasedCover
from boneio.cover.venetian import VenetianCover
from boneio.events import EventBus, EventType
from boneio.gpio_manager_mock import GpioManagerMock
from boneio.group.output import OutputGroup
from boneio.helper import (
    HostData,
    I2CError,
    StateManager,
    ha_button_availabilty_message,
    ha_led_availabilty_message,
    ha_light_availabilty_message,
    ha_switch_availabilty_message,
)
from boneio.helper.async_updater import refresh_wrapper
from boneio.helper.exceptions import CoverConfigurationError
from boneio.helper.ha_discovery import (
    ha_cover_availabilty_message,
    ha_cover_with_tilt_availabilty_message,
    ha_sensor_availability_message,
    ha_sensor_ina_availabilty_message,
    ha_sensor_temp_availabilty_message,
    ha_valve_availabilty_message,
)
from boneio.helper.loader import (
    configure_binary_sensor,
    configure_ds2482,
    configure_event_sensor,
    configure_relay,
    create_adc,
    create_dallas_sensor,
    create_modbus_coordinators,
)
from boneio.helper.onewire.onewire import OneWireAddress
from boneio.helper.pcf8575 import PCF8575
from boneio.helper.stats import get_network_info
from boneio.helper.util import strip_accents
from boneio.logger import configure_logger
from boneio.message_bus import (
    ButtonMqttMessage,
    CoverMqttMessage,
    CoverPosMqttMessage,
    CoverSetMqttMessage,
    CoverTiltMqttMessage,
    GroupMqttMessage,
    MessageBus,
    ModbusMqttMessage,
    MqttMessage,
    RelayMqttMessage,
    RelaySetBrightnessMqttMessage,
    RelaySetMqttMessage,
)
from boneio.modbus.client import Modbus, ModbusUartException
from boneio.modbus.coordinator import ModbusCoordinator
from boneio.models import OutputState
from boneio.relay.basic import BasicRelay
from boneio.relay.pca import PWMPCA
from boneio.sensor.ina219 import INA219
from boneio.sensor.temp import TempSensor
from boneio.sensor.temp.lm75 import LM75Sensor
from boneio.sensor.temp.mcp9808 import MCP9808Sensor
from boneio.yaml import load_config

if TYPE_CHECKING:
    from busio import I2C

    from boneio.gpio import GpioEventButtonsAndSensors
    from boneio.gpio.base import GpioBase
    from boneio.gpio_manager import GpioManager

_LOGGER = logging.getLogger(__name__)

AVAILABILITY_FUNCTION_CHOOSER = {
    "light": ha_light_availabilty_message,
    "led": ha_led_availabilty_message,
    "switch": ha_switch_availabilty_message,
    "valve": ha_valve_availabilty_message,
}


class Manager:
    """Manager to communicate MQTT with GPIO inputs and outputs."""

    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        config: Config,
        message_bus: MessageBus,
        event_bus: EventBus,
        config_file_path: Path,
        dry: bool = False,
    ) -> AsyncGenerator[Manager]:
        if dry:
            _LOGGER.warning("Running in dry mode, no changes will be made.")
            GpioManagerClass = GpioManagerMock
        else:
            from boneio.gpio_manager import GpioManager

            GpioManagerClass = GpioManager
        async with GpioManagerClass.create() as gpio_manager:
            async with StateManager.create(
                config_file_path.parent / "state.json"
            ) as state_manager:
                async with anyio.create_task_group() as tg:
                    this = cls(
                        tg=tg,
                        config=config,
                        message_bus=message_bus,
                        event_bus=event_bus,
                        config_file_path=config_file_path,
                        gpio_manager=gpio_manager,
                        state_manager=state_manager,
                    )

                    if config.oled is not None and config.oled.enabled:
                        from boneio.oled import Oled

                        async with anyio.create_task_group() as oled_tg:
                            try:
                                oled = Oled(
                                    tg=oled_tg,
                                    host_data=this.host_data,
                                    screen_order=config.oled.screens,
                                    grouped_outputs_by_expander=this.grouped_outputs_by_expander.keys(),
                                    sleep_timeout=config.oled.screensaver_timeout,
                                    event_bus=event_bus,
                                    gpio_manager=gpio_manager,
                                )
                            except I2CError as err:
                                _LOGGER.error("Can't configure OLED display. %s", err)
                            else:
                                oled.render_display()
                            try:
                                yield this
                            except BaseException:
                                tg.cancel_scope.cancel()
                                raise
                    else:
                        try:
                            yield this
                        except BaseException:
                            tg.cancel_scope.cancel()
                            raise

    def _get_lazy_i2c(self) -> I2C:
        if self.i2c is None:
            from board import SCL, SDA  # type: ignore
            from busio import I2C

            self.i2c = I2C(SCL, SDA)
        return self.i2c

    def __init__(
        self,
        tg: anyio.abc.TaskGroup,
        config: Config,
        message_bus: MessageBus,
        event_bus: EventBus,
        config_file_path: Path,
        gpio_manager: GpioManager,
        state_manager: StateManager,
    ) -> None:
        self.tg = tg
        self.gpio_manager = gpio_manager
        self.state_manager = state_manager
        _LOGGER.info("Initializing manager module.")

        self.config = config
        self._config_file_path = config_file_path
        self.event_bus = event_bus
        self.message_bus = message_bus
        self.inputs: dict[str, GpioEventButtonsAndSensors] = {}
        self.outputs: dict[str, BasicRelay] = {}
        self.output_groups: dict[str, OutputGroup] = {}
        self.interlock_manager = SoftwareInterlockManager()
        self.covers: dict[str, PreviousCover | TimeBasedCover | VenetianCover] = {}
        self.temp_sensors: list[TempSensor] = []
        self.ina219_sensors: list[INA219] = []
        self.modbus_coordinators: dict[str, ModbusCoordinator] = {}
        self.modbus: Modbus | None = None
        self.i2c: I2C | None = None

        if config.modbus is not None:
            self._configure_modbus(modbus=config.modbus)

        for sensor in config.lm75:
            id = sensor.identifier()
            try:
                temp_sensor = LM75Sensor(
                    id=id,
                    name=sensor.id,
                    i2c=self._get_lazy_i2c(),
                    address=sensor.address,
                    manager=self,
                    message_bus=message_bus,
                    topic_prefix=self.config.get_topic_prefix(),
                    update_interval=sensor.update_interval,
                    filters=sensor.filters,
                    unit_of_measurement=sensor.unit_of_measurement,
                )
            except I2CError as err:
                _LOGGER.error("Can't configure Temp sensor. %s", err)
                continue

            self.send_ha_autodiscovery(
                id=id,
                name=sensor.id,
                ha_type="sensor",
                availability_msg_func=ha_sensor_temp_availabilty_message,
                unit_of_measurement=temp_sensor.unit_of_measurement,
            )
            if temp_sensor:
                self.temp_sensors.append(temp_sensor)
        for sensor in config.mcp9808:
            id = sensor.identifier()
            try:
                temp_sensor = MCP9808Sensor(
                    id=id,
                    name=sensor.id,
                    i2c=self._get_lazy_i2c(),
                    address=sensor.address,
                    manager=self,
                    message_bus=message_bus,
                    topic_prefix=self.config.get_topic_prefix(),
                    update_interval=sensor.update_interval,
                    filters=sensor.filters,
                    unit_of_measurement=sensor.unit_of_measurement,
                )
            except I2CError as err:
                _LOGGER.error("Can't configure Temp sensor. %s", err)
                continue

            self.send_ha_autodiscovery(
                id=id,
                name=sensor.id,
                ha_type="sensor",
                availability_msg_func=ha_sensor_temp_availabilty_message,
                unit_of_measurement=temp_sensor.unit_of_measurement,
            )
            if temp_sensor:
                self.temp_sensors.append(temp_sensor)

        self.modbus_coordinators = {}
        if config.ina219 is not None:
            self._configure_ina219_sensors(sensors=config.ina219)
        self._configure_sensors(
            dallas=config.dallas, ds2482=config.ds2482, sensors=config.sensor
        )

        _E = TypeVar("_E", bound="MCP23017 | PCF8575 | PCA9685")
        _C = TypeVar("_C", bound="Mcp23017Config | Pcf8575Config | Pca9685Config")

        def create_expander(
            expanders_config: list[_C],
            create_func: Callable[[_C], _E],
        ) -> dict[str, _E]:
            result: dict[str, _E] = {}
            for config in expanders_config:
                id = config.identifier()
                try:
                    obj = create_func(config)
                    result[id] = obj
                    if config.init_sleep.total_seconds() > 0:
                        _LOGGER.debug(
                            "Sleeping for %s while %s %s is initializing.",
                            config.init_sleep.total_seconds(),
                            str(type(obj)),
                            id,
                        )
                        # TODO it has to be async!!!
                        time.sleep(config.init_sleep.total_seconds())
                    else:
                        _LOGGER.debug("%s %s is initializing.", str(type(obj)), id)
                except TimeoutError as err:
                    _LOGGER.error("Can't connect to %s. %s", id, err)
            return result

        def mcp23017(expander: Mcp23017Config) -> MCP23017:
            return MCP23017(self._get_lazy_i2c(), address=expander.address)

        def pcf8575(expander: Pcf8575Config) -> PCF8575:
            return PCF8575(self._get_lazy_i2c(), address=expander.address)

        def pca9685(expander: Pca9685Config) -> PCA9685:
            return PCA9685(self._get_lazy_i2c(), address=expander.address)

        self.mcp = create_expander(
            expanders_config=config.mcp23017,
            create_func=mcp23017,
        )
        self.pcf = create_expander(
            expanders_config=config.pcf8575,
            create_func=pcf8575,
        )
        self.pca = create_expander(
            expanders_config=config.pca9685,
            create_func=pca9685,
        )
        self.grouped_outputs_by_expander: dict[str, dict[str, BasicRelay]] = {
            key: {} for key in (self.mcp.keys() | self.pcf.keys() | self.pca.keys())
        }

        create_adc(
            manager=self,
            message_bus=self.message_bus,
            topic_prefix=self.config.get_topic_prefix(),
            adc=self.config.adc,
        )

        for _output in config.output:
            output = _output.root
            _id = strip_accents(output.id)
            _LOGGER.debug("Configuring relay: %s", _id)
            out = configure_relay(  # grouped_output updated here.
                manager=self,
                output_config=output,
                message_bus=message_bus,
                state_manager=self.state_manager,
                topic_prefix=self.config.get_topic_prefix(),
                relay_id=_id,
                event_bus=self.event_bus,
            )
            if output.restore_state:
                self.event_bus.add_event_listener(
                    event_type=EventType.OUTPUT,
                    entity_id=out.id,
                    listener_id="manager",
                    target=self._relay_callback,
                )
            self.outputs[_id] = out
            if out.output_type not in ("none", "cover"):
                self.send_ha_autodiscovery(
                    id=out.id,
                    name=out.name,
                    ha_type=("light" if out.output_type == "led" else out.output_type),
                    availability_msg_func=AVAILABILITY_FUNCTION_CHOOSER.get(
                        out.output_type, ha_switch_availabilty_message
                    ),
                )
            self.tg.start_soon(self._delayed_send_state, out)

        if self.outputs:
            self._configure_covers()

        self._configure_output_group()

        _LOGGER.info("Initializing inputs. This will take a while.")
        self.configure_inputs()

        self.create_serial_number_sensor()
        self.modbus_coordinators = self._configure_modbus_coordinators(
            devices=config.modbus_devices
        )

        self.host_data = HostData(
            manager=self,
            event_bus=self.event_bus,
            enabled_screens=config.oled.screens if config.oled is not None else [],
            output=self.grouped_outputs_by_expander,
            inputs=self.inputs,
            temp_sensor=(self.temp_sensors[0] if self.temp_sensors else None),
            ina219=(self.ina219_sensors[0] if self.ina219_sensors else None),
            extra_sensors=config.oled.extra_screen_sensors
            if config.oled is not None
            else [],
        )
        self.prepare_ha_buttons()
        _LOGGER.info("BoneIO manager is ready.")

    def _configure_output_group(self) -> None:
        def get_outputs(output_list: list[str]) -> list[BasicRelay]:
            outputs: list[BasicRelay] = []
            for x in output_list:
                x = strip_accents(x)
                if x in self.outputs:
                    output = self.outputs[x]
                    if output.output_type == "cover":
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
                id=strip_accents(group.identifier()),
                message_bus=self.message_bus,
                state_manager=self.state_manager,
                topic_prefix=self.config.get_topic_prefix(),
                event_bus=self.event_bus,
                members=members,
                config=group,
            )
            self.output_groups[output_group.id] = output_group
            if output_group.output_type != "none":
                self.send_ha_autodiscovery(
                    id=output_group.id,
                    name=output_group.id,
                    ha_type=output_group.output_type,
                    availability_msg_func=AVAILABILITY_FUNCTION_CHOOSER.get(
                        output_group.output_type,
                        ha_switch_availabilty_message,
                    ),
                    device_type="group",
                    icon=(
                        "mdi:lightbulb-group"
                        if output_group.output_type == "light"
                        else "mdi:toggle-switch-variant"
                    ),
                )
            self.append_task(coro=output_group.event_listener, name=output_group.id)

    def _configure_covers(self, reload_config: bool = False) -> None:
        """Configure covers."""
        if reload_config:
            self.config.cover = load_config(self._config_file_path).cover
            if self.config.mqtt is not None:
                self.config.mqtt.autodiscovery_messages.clear_type(type="cover")
        for _cover_config in self.config.cover:
            cover_config = _cover_config.root
            _id = strip_accents(cover_config.id)
            open_relay = self.outputs.get(cover_config.open_relay)
            close_relay = self.outputs.get(cover_config.close_relay)
            if not open_relay:
                _LOGGER.error(
                    "Can't configure cover %s. This relay doesn't exist.",
                    cover_config.open_relay,
                )
                continue
            if not close_relay:
                _LOGGER.error(
                    "Can't configure cover %s. This relay doesn't exist.",
                    cover_config.close_relay,
                )
                continue
            if open_relay.output_type != "cover" or close_relay.output_type != "cover":
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
                    if isinstance(_cover, VenetianCover):
                        _cover.update_config_times(cover_config)
                    continue

                if isinstance(cover_config.platform, VenetianCoverConfig):
                    if not cover_config.tilt_duration:
                        raise CoverConfigurationError(
                            "Tilt duration must be configured for tilt cover."
                        )
                    _LOGGER.debug("Configuring tilt cover %s", _id)
                    cover = VenetianCover(
                        id=_id,
                        name=_id,
                        actuator_activation_duration=cover_config.actuator_activation_duration,
                        tilt_delta=cover_config.tilt_duration,
                        state_manager=self.state_manager,
                        message_bus=self.message_bus,
                        open_relay=open_relay,
                        close_relay=close_relay,
                        open_time=cover_config.open_time,
                        close_time=cover_config.close_time,
                        restore_state=cover_config.restore_state,
                        event_bus=self.event_bus,
                        topic_prefix=self.config.get_topic_prefix(),
                    )
                    availability_msg_func = ha_cover_with_tilt_availabilty_message
                elif isinstance(cover_config.platform, TimeBasedCoverConfig):
                    _LOGGER.debug("Configuring time-based cover %s", _id)
                    cover = TimeBasedCover(
                        id=_id,
                        name=_id,
                        state_manager=self.state_manager,
                        message_bus=self.message_bus,
                        open_relay=open_relay,
                        close_relay=close_relay,
                        open_time=cover_config.open_time,
                        close_time=cover_config.close_time,
                        restore_state=cover_config.restore_state,
                        event_bus=self.event_bus,
                        topic_prefix=self.config.get_topic_prefix(),
                    )
                    availability_msg_func = ha_cover_availabilty_message
                elif isinstance(cover_config.platform, PreviousCoverConfig):
                    _LOGGER.debug("Configuring previous cover %s", _id)
                    cover = PreviousCover(
                        id=_id,
                        name=_id,
                        state_manager=self.state_manager,
                        message_bus=self.message_bus,
                        open_relay=open_relay,
                        close_relay=close_relay,
                        open_time=cover_config.open_time,
                        close_time=cover_config.close_time,
                        restore_state=cover_config.restore_state,
                        event_bus=self.event_bus,
                        topic_prefix=self.config.get_topic_prefix(),
                    )
                    availability_msg_func = ha_cover_availabilty_message
                else:
                    raise ValueError(f"Wrong cover platform: {cover_config.platform}")

                if cover_config.show_in_ha:
                    self.send_ha_autodiscovery(
                        id=cover.id,
                        name=cover.name,
                        ha_type="cover",
                        device_class=cover_config.device_class,
                        availability_msg_func=availability_msg_func,
                    )
                _LOGGER.debug("Configured cover %s", _id)

                self.covers[_id] = cover

            except CoverConfigurationError as err:
                _LOGGER.error("Can't configure cover %s. %s", _id, err)
                continue

    def configure_inputs(self, reload_config: bool = False) -> None:
        """Configure inputs. Either events or binary sensors."""

        def check_if_pin_configured(pin: str) -> bool:
            if pin in self.inputs:
                if not reload_config:
                    _LOGGER.warning(
                        "This PIN %s is already configured. Omitting it.", pin
                    )
                    return True
            return False

        if reload_config:
            config = load_config(self._config_file_path)
            self.config.event = config.event
            self.config.binary_sensor = config.binary_sensor
            if self.config.mqtt is not None:
                self.config.mqtt.autodiscovery_messages.clear_type(type="event")
                self.config.mqtt.autodiscovery_messages.clear_type(type="binary_sensor")
        for gpio in self.config.event:
            if check_if_pin_configured(pin=gpio.pin):
                return
            input = configure_event_sensor(
                tg=self.tg,
                event_config=gpio,
                manager_press_callback=self.press_callback,
                event_bus=self.event_bus,
                send_ha_autodiscovery=self.send_ha_autodiscovery,
                input=self.inputs.get(gpio.pin),  # for reload actions.
                gpio_manager=self.gpio_manager,
            )
            if input:
                self.inputs[input.pin] = input

        for gpio in self.config.binary_sensor:
            if check_if_pin_configured(pin=gpio.pin):
                return
            input = configure_binary_sensor(
                tg=self.tg,
                sensor_config=gpio,
                manager_press_callback=self.press_callback,
                event_bus=self.event_bus,
                send_ha_autodiscovery=self.send_ha_autodiscovery,
                input=self.inputs.get(gpio.pin),  # for reload actions.
                gpio_manager=self.gpio_manager,
            )
            if input:
                self.inputs[input.pin] = input

    def append_task(
        self, coro: Callable[[], Coroutine[None, None, None]], name: str = "Unknown"
    ) -> None:
        _LOGGER.debug("Appending update task for %s", name)
        self.tg.start_soon(coro)

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
        from boneio.helper.loader import find_onewire_devices

        _one_wire_devices: dict[int, OneWireAddress] = {}
        _ds_onewire_bus = {}

        for _single_ds in ds2482:
            _LOGGER.debug("Preparing DS2482 bus at address %s.", _single_ds.address)
            id = _single_ds.identifier()
            _ds_onewire_bus[id] = configure_ds2482(
                i2cbusio=self._get_lazy_i2c(), address=_single_ds.address
            )
            _one_wire_devices.update(
                find_onewire_devices(
                    ow_bus=_ds_onewire_bus[id],
                    bus_id=id,
                    bus_type="ds2482",
                )
            )
        if dallas is not None:
            _LOGGER.debug("Preparing Dallas bus.")
            from boneio.helper.loader import configure_dallas

            try:
                from w1thermsensor.kernel import load_kernel_modules  # type: ignore

                load_kernel_modules()

                _one_wire_devices.update(
                    find_onewire_devices(
                        ow_bus=configure_dallas(),
                        bus_id=dallas.id,
                        bus_type="dallas",
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
                    topic_prefix=self.config.get_topic_prefix(),
                    config=sensor,
                    bus=bus,
                )
            )

    def _configure_adc(self, adc: list[AdcConfig]) -> None:
        create_adc(
            manager=self,
            message_bus=self.message_bus,
            topic_prefix=self.config.get_topic_prefix(),
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

    def _configure_ina219_sensors(self, sensors: list[Ina219Config]) -> None:
        for sensor_config in sensors:
            ina219 = INA219.from_config(
                config=sensor_config,
                message_bus=self.message_bus,
                event_bus=self.event_bus,
                topic_prefix=self.config.get_topic_prefix(),
            )
            self.append_task(
                refresh_wrapper(ina219.update, sensor_config.update_interval), ina219.id
            )

            for device_class, sensor in ina219.sensors.items():
                self.send_ha_autodiscovery(
                    id=sensor.id,
                    name=sensor.name,
                    ha_type="sensor",
                    availability_msg_func=ha_sensor_ina_availabilty_message,
                    unit_of_measurement=sensor.unit_of_measurement,
                    device_class=device_class,
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
                event_bus=self.event_bus,
                entries=devices,
                modbus=self.modbus,
                config=self.config,
            )
        return {}

    def create_serial_number_sensor(self) -> None:
        """Create Serial number sensor in manager."""
        id = "serial_number"
        name = "Serial number"

        def update(timestamp: float) -> None:
            """Fetch temperature periodically and send to MQTT."""
            network_info = get_network_info()
            if "mac" not in network_info:
                return
            # Remove colons and take last 6 characters
            state = network_info["mac"].replace(":", "")[-6:]
            state = f"blk{state}"
            self.message_bus.send_message(
                topic=f"{self.config.get_topic_prefix()}/sensor/{id}",
                payload=state,
            )

        self.append_task(refresh_wrapper(update, timedelta(minutes=60)), name)
        self.send_ha_autodiscovery(
            id=id,
            name=name,
            ha_type="sensor",
            entity_category="diagnostic",
            availability_msg_func=ha_sensor_availability_message,
        )

    async def _relay_callback(
        self,
        event: OutputState,
    ) -> None:
        """Relay callback function."""
        self.state_manager.state.relay[event.id] = event.state == "ON"
        self.state_manager.save()

    def _logger_reload(self) -> None:
        """_Logger reload function."""
        _config = load_config(config_file_path=self._config_file_path)
        configure_logger(log_config=_config.logger, debug=-1)

    def prepare_ha_buttons(self) -> None:
        """Prepare HA buttons for reload."""
        self.send_ha_autodiscovery(
            id="logger",
            name="Logger reload",
            ha_type="button",
            availability_msg_func=ha_button_availabilty_message,
            entity_category="config",
        )
        self.send_ha_autodiscovery(
            id="restart",
            name="Restart boneIO",
            ha_type="button",
            payload_press="restart",
            availability_msg_func=ha_button_availabilty_message,
            entity_category="config",
        )
        self.send_ha_autodiscovery(
            id="inputs_reload",
            name="Reload actions",
            ha_type="button",
            payload_press="inputs_reload",
            availability_msg_func=ha_button_availabilty_message,
            entity_category="config",
        )
        if self.covers:
            self.send_ha_autodiscovery(
                id="cover_reload",
                name="Reload times of covers",
                ha_type="button",
                payload_press="cover_reload",
                availability_msg_func=ha_button_availabilty_message,
                entity_category="config",
            )

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
        actions = gpio.actions.get(x, [])
        topic = f"{self.config.get_topic_prefix()}/{gpio.input_type}/{gpio.pin}"

        def generate_payload() -> str | dict[str, str | float]:
            if gpio.input_type == "input":
                if duration:
                    return {"event_type": x, "duration": duration}
                return {"event_type": x}
            return x

        for action in actions:
            if isinstance(action, MqttActionConfig):
                self.message_bus.send_message(
                    topic=action.topic, payload=action.action_mqtt_msg, retain=False
                )
                continue
            elif isinstance(action, OutputActionConfig):
                output = self.outputs.get(
                    action.pin, self.output_groups.get(action.pin)
                )
                if output is None:
                    raise ValueError("This output doesn't exist!")
                duration = None
                if start_time is not None:
                    duration = time.time() - start_time
                _LOGGER.debug(
                    "Executing action %s for output %s. Duration: %s",
                    action.action_output,
                    output.name,
                    duration,
                )
                if action.action_output == "toggle":
                    await output.toggle()
                elif action.action_output == "on":
                    await output.turn_on()
                elif action.action_output == "off":
                    await output.turn_off()
                else:
                    raise ValueError("Wrong action output type!")
            elif isinstance(action, CoverActionConfig):
                cover = self.covers.get(action.pin)
                if cover is None:
                    raise ValueError("This cover doesn't exist!")
                duration = None
                if start_time is not None:
                    duration = time.time() - start_time
                _LOGGER.debug(
                    "Executing action %s for cover %s. Duration: %s",
                    action.action_cover,
                    cover.name,
                    duration,
                )
                match action.action_cover:
                    case "close":
                        await cover.close()
                    case "open":
                        await cover.open()
                    case "toggle":
                        await cover.toggle()
                    case "stop":
                        await cover.stop()
                    case "toggle_open":
                        await cover.toggle_open()
                    case "toggle_close":
                        await cover.toggle_close()
                    case "tilt_open":
                        if not isinstance(cover, VenetianCover):
                            raise ValueError(
                                "`tilt_open` action is only for Venetian cover!"
                            )
                        await cover.tilt_open()
                    case "tilt_close":
                        if not isinstance(cover, VenetianCover):
                            raise ValueError(
                                "`tilt_close` action is only for Venetian cover!"
                            )
                        await cover.tilt_close()
                    case _:
                        raise ValueError("Wrong action cover type!")
            elif isinstance(action, OutputOverMqttActionConfig):
                self.message_bus.send_message(
                    topic=f"{action.boneio_id}/cmd/relay/{action.pin}/set",
                    payload=action.action_output,
                    retain=False,
                )
            elif isinstance(action, CoverOverMqttActionConfig):
                self.message_bus.send_message(
                    topic=f"{action.boneio_id}/cmd/cover/{action.pin}/set",
                    payload=action.action_cover,
                    retain=False,
                )
            else:
                raise ValueError("Wrong action definitiony type!")

        payload = generate_payload()
        _LOGGER.debug("Sending message %s for input %s", payload, topic)
        self.message_bus.send_message(topic=topic, payload=payload, retain=False)
        # This is similar how Z2M is clearing click sensor.
        if empty_message_after:
            await anyio.sleep(0.2)
            self.message_bus.send_message(topic=topic, payload="")

    async def toggle_output(self, output_id: str) -> str:
        """Toggle output state."""
        output = self.outputs.get(output_id)
        if output:
            if output.output_type in ("none", "cover"):
                return "not_allowed"
            if not output.check_interlock():
                return "interlock"
            await output.toggle()
            return "success"
        return "not_found"

    async def receive_message(self, topic: str, message: str) -> None:
        """Callback for receiving action from message bus."""
        _LOGGER.debug("Processing topic %s with message %s.", topic, message)
        if self.config.mqtt is not None:
            if topic.startswith(f"{self.config.mqtt.ha_discovery.topic_prefix}/status"):
                if message == "online":
                    for msg in self.config.mqtt.autodiscovery_messages.root.values():
                        self.message_bus.send_message(
                            topic=msg.topic, payload=msg.payload, retain=True
                        )

                    self.event_bus.signal_ha_online()
                return
        if not topic.startswith(f"{self.config.get_topic_prefix()}/cmd/"):
            _LOGGER.error("Wrong topic %s!", topic)
            return
        topic_parts_raw = topic[len(f"{self.config.get_topic_prefix()}/cmd/") :].split(
            "/"
        )
        mqtt_message = (
            TypeAdapter(MqttMessage)
            .validate_python(
                {
                    "type_": topic_parts_raw[-3],
                    "device_id": topic_parts_raw[-2],
                    "command": topic_parts_raw[-1],
                    "message": message,
                }
            )
            .root
        )

        if isinstance(mqtt_message, RelayMqttMessage):
            relay_message = mqtt_message.root
            if isinstance(relay_message, RelaySetMqttMessage):
                target_device = self.outputs.get(relay_message.device_id)
                if target_device is None or target_device.output_type == "none":
                    _LOGGER.warning(
                        "This relay %s doesn't exist.", relay_message.device_id
                    )
                    return
                match relay_message.message:
                    case "ON":
                        await target_device.turn_on()
                    case "OFF":
                        await target_device.turn_off()
                    case "TOGGLE":
                        await target_device.toggle()
                    case _:
                        assert_never(relay_message)
            elif isinstance(relay_message, RelaySetBrightnessMqttMessage):
                target_device = self.outputs.get(relay_message.device_id)
                if not (
                    isinstance(target_device, PWMPCA)
                    and target_device.output_type != "none"
                ):
                    _LOGGER.warning(
                        "This relay %s doesn't exist or is not PWM.",
                        relay_message.device_id,
                    )
                    return
                target_device.set_brightness(relay_message.message)
            else:
                assert_never(relay_message)
        elif isinstance(mqtt_message, CoverMqttMessage):
            cover_message = mqtt_message.root
            cover = self.covers.get(cover_message.device_id)
            if cover is None:
                _LOGGER.warning(
                    "This cover %s doesn't exist. Ignoring message.",
                    cover_message.device_id,
                )
                return
            if isinstance(cover_message, CoverSetMqttMessage):
                match cover_message.message:
                    case "stop":
                        await cover.stop()
                    case "open":
                        await cover.open()
                    case "close":
                        await cover.close()
                    case "toggle":
                        await cover.toggle()
                    case "toggle_open":
                        await cover.toggle_open()
                    case "toggle_close":
                        await cover.toggle_close()
                    case _:
                        assert_never(cover_message)
            elif isinstance(cover_message, CoverPosMqttMessage):
                await cover.set_cover_position(position=cover_message.message)
            elif isinstance(cover_message, CoverTiltMqttMessage):
                if isinstance(cover_message.message, int):
                    await cover.set_tilt(tilt_position=cover_message.message)
                else:
                    await cover.stop()
        elif isinstance(mqtt_message, GroupMqttMessage):
            target_device = self.output_groups.get(mqtt_message.device_id)
            if target_device is not None and target_device.output_type != "none":
                match mqtt_message.message:
                    case "ON":
                        await target_device.turn_on()
                    case "OFF":
                        await target_device.turn_off()
                    case "TOGGLE":
                        await target_device.toggle()
                    case _:
                        assert_never(mqtt_message)
            else:
                _LOGGER.debug("Target device not found %s.", mqtt_message.device_id)
        elif isinstance(mqtt_message, ButtonMqttMessage):
            if mqtt_message.device_id == "logger" and mqtt_message.message == "reload":
                _LOGGER.info("Reloading logger configuration.")
                self._logger_reload()
            elif (
                mqtt_message.device_id == "restart"
                and mqtt_message.message == "restart"
            ):
                await self.restart_request()
            elif (
                mqtt_message.device_id == "inputs_reload"
                and mqtt_message.message == "inputs_reload"
            ):
                _LOGGER.info("Reloading events and binary sensors actions")
                self.configure_inputs(reload_config=True)
            elif (
                mqtt_message.device_id == "cover_reload"
                and mqtt_message.message == "cover_reload"
            ):
                _LOGGER.info("Reloading covers actions")
                self._configure_covers(reload_config=True)
            else:
                raise ValueError("Wrong button command!")

        elif isinstance(mqtt_message, ModbusMqttMessage):
            target_device = self.modbus_coordinators.get(mqtt_message.device_id)
            if target_device is not None:
                await target_device.write_register(
                    value=mqtt_message.message.value,
                    entity=mqtt_message.message.device,
                )
        else:
            assert_never(mqtt_message)

    async def restart_request(self) -> None:
        _LOGGER.info("Restarting process. Systemd should restart it soon.")
        os._exit(0)  # Terminate the process

    async def _delayed_send_state(self, output: BasicRelay) -> None:
        """Send state after a delay."""
        await anyio.sleep(0.5)
        output.send_state()

    def send_ha_autodiscovery(
        self,
        id: str,
        name: str,
        ha_type: str,
        availability_msg_func: Callable[..., BaseModel],
        topic_prefix: str | None = None,
        **kwargs,
    ) -> None:
        """Send HA autodiscovery information for each relay."""
        if self.config.mqtt is None:
            return
        if not self.config.mqtt.ha_discovery.enabled:
            return
        topic_prefix = topic_prefix or self.config.get_topic_prefix()
        web_url = None
        if self.config.web is not None:
            network_state = get_network_info()
            if "ip" in network_state:
                web_url = f"http://{network_state['ip']}:{self.config.web.port}"
        payload = availability_msg_func(
            topic=topic_prefix,
            id=id,
            name=name,
            model=self.config.boneio.device_type.title(),
            device_name=self.config.boneio.name,
            web_url=web_url,
            **kwargs,
        )
        topic = f"{self.config.get_ha_autodiscovery_topic_prefix()}/{ha_type}/{topic_prefix}/{id}/config"
        _LOGGER.debug("Sending HA discovery for %s entity, %s.", ha_type, name)
        self.config.mqtt.autodiscovery_messages.add_message(
            message=MqttAutodiscoveryMessage(
                topic=topic, payload=payload.model_dump(exclude_none=True)
            ),
            type=ha_type,
        )
        self.message_bus.send_message(
            topic=topic, payload=payload.model_dump_json(exclude_none=True), retain=True
        )


@dataclass
class SoftwareInterlockManager:
    groups: defaultdict[str, set[BasicRelay]] = field(
        default_factory=lambda: defaultdict(set)
    )

    def register(self, relay: BasicRelay, group_names: list[str]) -> None:
        for group in group_names:
            self.groups[group].add(relay)

    def can_turn_on(self, relay: BasicRelay, group_names: list[str]) -> bool:
        for group in group_names:
            for other_relay in self.groups.get(group, []):
                if (
                    other_relay is not relay
                    and getattr(other_relay, "state", None) == "ON"
                ):
                    return False
        return True
