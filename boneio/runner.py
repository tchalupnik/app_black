"""Runner code for boneIO. Based on HA runner."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Literal
import warnings

from pydantic import BaseModel, Field, RootModel

from boneio.const import (
    ADC,
    BINARY_SENSOR,
    BONEIO,
    BUTTON,
    COVER,
    DALLAS,
    DS2482,
    EVENT_ENTITY,
    INA219,
    LIGHT,
    LM75,
    MCP23017,
    MCP_TEMP_9808,
    MODBUS,
    NUMERIC,
    OLED,
    ONEWIRE,
    OUTPUT,
    OUTPUT_GROUP,
    PCA9685,
    PCF8575,
    SELECT,
    SENSOR,
    SWITCH,
    TEXT_SENSOR,
    VALVE,
)
from boneio.helper import StateManager
from boneio.helper.events import EventBus, GracefulExit
from boneio.helper.exceptions import RestartRequestException
from boneio.manager import Manager
from boneio.message_bus import MQTTClient
from boneio.webui.web_server import WebServer

# Filter out cryptography deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning, module="cryptography")

_LOGGER = logging.getLogger(__name__)

config_modules = [
    {"name": MCP23017, "default": []},
    {"name": PCF8575, "default": []},
    {"name": PCA9685, "default": []},
    {"name": DS2482, "default": []},
    {"name": ADC, "default": []},
    {"name": COVER, "default": []},
    {"name": MODBUS, "default": {}},
    {"name": OLED, "default": {}},
    {"name": DALLAS, "default": None},
    {"name": OUTPUT_GROUP, "default": []},
]


class MqttHADiscoveryConfig(BaseModel):
    enabled: bool = True
    topic_prefix: str = "homeassistant"


class MqttAutodiscoveryMessage(BaseModel):
    topic: str
    payload: str


AutodiscoveryType = Literal[
    "switch",
    "light",
    "binary_sensor",
    "sensor",
    "cover",
    "button",
    "event_entity",
    "valve",
    "text_sensor",
    "select",
    "numeric",
]


class MqttAutodiscoveryMessages(
    RootModel[dict[AutodiscoveryType, MqttAutodiscoveryMessage]]
):
    def model_post_init(self) -> None:
        for type in (
            SWITCH,
            LIGHT,
            BINARY_SENSOR,
            SENSOR,
            COVER,
            BUTTON,
            EVENT_ENTITY,
            VALVE,
            TEXT_SENSOR,
            SELECT,
            NUMERIC,
        ):
            if type not in self.root:
                self.root[type] = {}

    def clear_type(self, type: AutodiscoveryType) -> None:
        self.root[type] = {}

    def add_message(
        self, type: AutodiscoveryType, message: MqttAutodiscoveryMessage
    ) -> None:
        self.root[type] = message


class MqttConfig(BaseModel):
    host: str = "localhost"
    port: int = 1883
    username: str = "boneio"
    password: str = "boneio123"
    topic_prefix: str = "boneio"
    ha_discovery: MqttHADiscoveryConfig = MqttHADiscoveryConfig()
    autodiscovery_messages: MqttAutodiscoveryMessages = MqttAutodiscoveryMessages()

    def is_topic_in_autodiscovery(self, topic: str) -> bool:
        topic_parts_raw = topic[len(f"{self.ha_discovery.topic_prefix}/") :].split("/")
        ha_type = topic_parts_raw[0]
        if ha_type in self.autodiscovery_messages.root:
            return topic in self.autodiscovery_messages.root[ha_type]
        return False

    def cmd_topic_prefix(self) -> str:
        return f"{self.topic_prefix}/cmd/"

    def subscribe_topic(self) -> str:
        return f"{self.cmd_topic_prefix()}+/+/#"


class OledExtraScreenSensorConfig(BaseModel):
    sensor_id: str
    sensor_type: Literal["modbus", "dallas"]
    modbus_id: str | None = None


class OledConfig(BaseModel):
    enabled: bool = False
    screens: list[
        Literal[
            "uptime",
            "network",
            "ina219",
            "cpu",
            "disk",
            "memory",
            "swap",
            "outputs",
            "inputs",
            "extra_sensors",
            "web",
        ]
    ] = Field(
        default_factory=[
            "uptime",
            "network",
            "ina219",
            "cpu",
            "disk",
            "memory",
            "swap",
            "outputs",
        ]
    )
    extra_screen_sensors: list[OledExtraScreenSensorConfig] = Field(
        default_factory=list
    )
    screensaver_timeout: str = "60s"


class TemperatureConfig(BaseModel):
    address: str
    id: str | None = None
    update_interval: str = "60s"
    filters: list[str] = Field(default_factory=list)
    unit_of_measurement: Literal["°C", "°F"] = "°C"


class Ina219SensorConfig(BaseModel):
    id: str
    device_class: Literal["voltage", "current", "power"]
    filters: list[str] = Field(default_factory=list)


class Ina219Config(BaseModel):
    address: str
    id: str | None = None
    sensors: list[Ina219SensorConfig] = Field(default_factory=list)


class EventActionDataConfig(BaseModel):
    position: int
    tilt_position: int


class EventActionConfig(BaseModel):
    action: Literal[
        "cover", "cover_over_mqtt", "mqtt", "mqtt_output", "output", "output_over_mqtt"
    ]
    pin: str
    topic: str
    action_mqtt_msg: str
    boneio_id: str
    action_cover: Literal[
        "toggle",
        "open",
        "close",
        "stop",
        "toggle_open",
        "toggle_close",
        "tilt",
        "tilt_open",
        "tilt_close",
    ] = "toggle"
    data: EventActionDataConfig | None = None
    action_output: Literal["toggle", "on", "off"] = "toggle"


class EventConfig(BaseModel):
    id: str
    pin: str
    boneio_input: Literal[
        "IN_01",
        "IN_02",
        "IN_03",
        "IN_04",
        "IN_05",
        "IN_06",
        "IN_07",
        "IN_08",
        "IN_09",
        "IN_10",
        "IN_11",
        "IN_12",
        "IN_13",
        "IN_14",
        "IN_15",
        "IN_16",
        "IN_17",
        "IN_18",
        "IN_19",
        "IN_20",
        "IN_21",
        "IN_22",
        "IN_23",
        "IN_24",
        "IN_25",
        "IN_26",
        "IN_27",
        "IN_28",
        "IN_29",
        "IN_30",
        "IN_31",
        "IN_32",
        "IN_33",
        "IN_34",
        "IN_35",
        "IN_36",
        "IN_37",
        "IN_38",
        "IN_39",
        "IN_40",
        "IN_41",
        "IN_42",
        "IN_43",
        "IN_44",
        "IN_45",
        "IN_46",
        "IN_47",
        "IN_48",
        "IN_49",
    ]
    action: RootModel[dict[Literal["single", "double", "long"], EventActionConfig]]
    device_class: Literal["button", "doorbell", "motion"]
    show_in_ha: bool = True
    inverted: bool = False
    gpio_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] = "gpio"
    detection_type: Literal["new", "old"] = "new"
    clear_message: bool = False
    bounce_time: str = "30ms"


EventsConfig = RootModel[list[EventConfig]]


class BinarySensorConfig(BaseModel):
    pass


class OutputConfig(BaseModel):
    pass


class SensorConfig(BaseModel):
    address: str
    update_interval: str = "60s"
    filters: list[str] = Field(default_factory=list)
    unit_of_measurement: Literal["°C", "°F"] = "°C"
    id: str | None = None
    show_in_ha: bool = True
    bus_id: int | None = None
    platform: Literal["dallas"] = "dallas"


class BoneIOConfig(BaseModel):
    name: str = BONEIO
    device_type: Literal["24", "32", "cover", "cover mix"] = "cover"
    version: float = 0.8


class WebConfig(BaseModel):
    username: str | None = None
    password: str | None = None
    port: int = 8090

    def is_auth_required(self) -> bool:
        return self.username is not None and self.password is not None


class AdcConfig(BaseModel):
    pin: Literal["P9_33", "P9_35", "P9_36", "P9_37", "P9_38", "P9_39", "P9_40"]
    id: str | None = None
    update_interval: str = "60s"
    show_in_ha: bool = True
    filters: list[str] = Field(default_factory=list)


class Config(BaseModel):
    boneio: BoneIOConfig
    mqtt: MqttConfig | None = None
    oled: OledConfig | None = None
    lm75: list[TemperatureConfig] | None = None
    mcp9808: list[TemperatureConfig] | None = None
    ina219: list[Ina219Config] | None = None
    sensors: list[SensorConfig] | None = None
    binary_sensor: BinarySensorConfig | None = None
    event: EventsConfig | None = None
    output: OutputConfig | None = None
    web: WebConfig | None = None
    adc: AdcConfig | None = None


async def async_run(
    config: dict,
    config_file: str,
    mqttusername: str | None = None,
    mqttpassword: str | None = None,
    debug: int = 0,
) -> int:
    """Run BoneIO."""
    configuration = Config.model_validate(config)
    web_server = None
    tasks: set[asyncio.Task] = set()
    event_bus = EventBus(loop=asyncio.get_event_loop())
    shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    if debug >= 2:
        loop.set_debug(True)

    def signal_handler():
        """Handle shutdown signals."""
        _LOGGER.info("Received shutdown signal, initiating graceful shutdown...")
        shutdown_event.set()

    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    event_bus_task = asyncio.create_task(event_bus.start())
    tasks.add(event_bus_task)
    event_bus_task.add_done_callback(tasks.discard)

    # Initialize message bus based on config
    if configuration.mqtt is not None:
        if mqttusername is not None:
            configuration.mqtt.username = mqttusername
        if mqttpassword is not None:
            configuration.mqtt.password = mqttpassword
        message_bus = MQTTClient(
            config=configuration,
        )
    else:
        from boneio.message_bus import LocalMessageBus

        message_bus = LocalMessageBus()

    manager_kwargs = {
        item["name"]: config.get(item["name"], item["default"])
        for item in config_modules
    }

    manager = Manager(
        config=configuration,
        message_bus=message_bus,
        event_bus=event_bus,
        relay_pins=config.get(OUTPUT, []),
        event_pins=config.get(EVENT_ENTITY, []),
        binary_pins=config.get(BINARY_SENSOR, []),
        config_file_path=config_file,
        state_manager=StateManager(
            state_file=f"{os.path.split(config_file)[0]}state.json"
        ),
        sensors={
            LM75: configuration.lm75 or [],
            INA219: configuration.ina219 or [],
            MCP_TEMP_9808: configuration.mcp9808 or [],
            ONEWIRE: configuration.sensors or [],
        },
        modbus_devices=config.get("modbus_devices", {}),
        **manager_kwargs,
    )
    # Convert coroutines to Tasks
    message_bus.set_manager(manager=manager)
    tasks.update(manager.get_tasks())

    message_bus_type = "MQTT" if isinstance(message_bus, MQTTClient) else "Local"
    _LOGGER.info("Starting message bus %s.", message_bus_type)
    message_bus_task = asyncio.create_task(message_bus.start_client())
    tasks.add(message_bus_task)
    message_bus_task.add_done_callback(tasks.discard)

    # Start web server if configured
    if configuration.web is not None:
        _LOGGER.info("Starting Web server.")
        web_server = WebServer(
            config=configuration,
            config_file=config_file,
            manager=manager,
        )
        web_server_task = asyncio.create_task(web_server.start_webserver())
        tasks.add(web_server_task)
        web_server_task.add_done_callback(tasks.discard)
    else:
        _LOGGER.info("Web server not configured.")

    try:
        # Convert tasks set to list for main gather
        task_list = list(tasks)
        main_gather = asyncio.gather(*task_list)

        # Wait for either shutdown signal or main task completion
        await asyncio.wait(
            [main_gather, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if shutdown_event.is_set():
            _LOGGER.info("Starting graceful shutdown...")
            await message_bus.announce_offline()
            main_gather.cancel()
            try:
                await main_gather
            except asyncio.CancelledError:
                pass

        return 0
    except asyncio.CancelledError:
        _LOGGER.info("Main task cancelled")
    except (RestartRequestException, GracefulExit):
        _LOGGER.info("Restart or graceful exit requested")
    except Exception as e:
        _LOGGER.error(f"Unexpected error: {type(e).__name__} - {e}")
    except BaseException as e:
        _LOGGER.error(f"Unexpected BaseException: {type(e).__name__} - {e}")
    finally:
        _LOGGER.info("Cleaning up resources...")

        # Trigger web server shutdown if it's running
        if web_server and hasattr(web_server, "trigger_shutdown"):
            try:
                _LOGGER.info("Requesting web server shutdown...")
                await web_server.trigger_shutdown()
            except Exception as e:
                _LOGGER.error(f"Error triggering web server shutdown: {e}")

        # Stop the event bus
        event_bus.request_stop()

        # Create a copy of tasks set to avoid modification during iteration
        remaining_tasks = list(tasks)
        if remaining_tasks:
            # Cancel and wait for all remaining tasks
            # Web server task will be cancelled here if it hasn't finished after trigger_shutdown
            for task in remaining_tasks:
                if not task.done():
                    _LOGGER.debug(
                        f"Cancelling task: {task.get_name() if hasattr(task, 'get_name') else task}"
                    )
                    task.cancel()

            # Wait for all tasks to complete
            try:
                await asyncio.gather(*remaining_tasks, return_exceptions=True)
            except Exception as e:
                _LOGGER.error(f"Error during cleanup: {type(e).__name__} - {e}")

        _LOGGER.info("Shutdown complete")
        return 0
