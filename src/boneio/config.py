from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, Discriminator, Field, RootModel, field_validator

from boneio.const import (
    BINARY_SENSOR,
    BONEIO,
    BUTTON,
    COVER,
    EVENT_ENTITY,
    LIGHT,
    NUMERIC,
    SELECT,
    SENSOR,
    SWITCH,
    TEXT_SENSOR,
    VALVE,
)


class MqttHADiscoveryConfig(BaseModel):
    enabled: bool = True
    topic_prefix: str = "homeassistant"


class MqttAutodiscoveryMessage(BaseModel):
    topic: str
    payload: str | dict[str, Any]


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

BoneIOInput = Literal[
    "in_01",
    "in_02",
    "in_03",
    "in_04",
    "in_05",
    "in_06",
    "in_07",
    "in_08",
    "in_09",
    "in_10",
    "in_11",
    "in_12",
    "in_13",
    "in_14",
    "in_15",
    "in_16",
    "in_17",
    "in_18",
    "in_19",
    "in_20",
    "in_21",
    "in_22",
    "in_23",
    "in_24",
    "in_25",
    "in_26",
    "in_27",
    "in_28",
    "in_29",
    "in_30",
    "in_31",
    "in_32",
    "in_33",
    "in_34",
    "in_35",
    "in_36",
    "in_37",
    "in_38",
    "in_39",
    "in_40",
    "in_41",
    "in_42",
    "in_43",
    "in_44",
    "in_45",
    "in_46",
    "in_47",
    "in_48",
    "in_49",
]


class MqttAutodiscoveryMessages(
    RootModel[dict[AutodiscoveryType, MqttAutodiscoveryMessage]]
):
    def model_post_init(self, __context: Any) -> None:
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
    host: str
    port: int = 1883
    username: str = "boneio"
    password: str = "boneio123"
    topic_prefix: str = "boneio"
    ha_discovery: MqttHADiscoveryConfig = MqttHADiscoveryConfig()
    autodiscovery_messages: MqttAutodiscoveryMessages = Field(
        default_factory=lambda: MqttAutodiscoveryMessages(root={})
    )

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


OledScreens = Literal[
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


class OledConfig(BaseModel):
    enabled: bool = False
    screens: list[OledScreens] = Field(
        default_factory=lambda: [
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
    screensaver_timeout: timedelta = Field(default_factory=lambda: timedelta(minutes=1))


Filters = Literal[
    "offset",
    "round",
    "multiply",
    "filter_out",
    "filter_out_greater",
    "filter_out_lower",
]


class TemperatureConfig(BaseModel):
    address: int
    id: str
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=60))
    filters: list[dict[Filters, float]] = Field(default_factory=list)
    unit_of_measurement: Literal["°C", "°F"] = "°C"

    def identifier(self) -> str:
        return self.id.replace(" ", "")


class Lm75Config(TemperatureConfig):
    pass


class Mcp9808Config(TemperatureConfig):
    pass


Ina219DeviceClass = Literal["voltage", "current", "power"]


class Ina219SensorConfig(BaseModel):
    id: str | None = None
    device_class: Ina219DeviceClass
    filters: list[dict[Filters, float]] = Field(default_factory=list)


class Ina219Config(BaseModel):
    address: int
    id: str | None = None
    sensors: list[Ina219SensorConfig] = Field(default_factory=list)
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=60))

    def identifier(self) -> str:
        if self.id:
            return (self.id).replace(" ", "")
        return str(self.address)


class ActionDataConfig(BaseModel):
    position: int | None = None
    tilt_position: int | None = None


CoverActionTypes: TypeAlias = Literal[
    "toggle",
    "open",
    "close",
    "stop",
    "toggle_open",
    "toggle_close",
    "tilt",
    "tilt_open",
    "tilt_close",
]
OutputActionTypes: TypeAlias = Literal["toggle", "on", "off"]


class OutputActionConfig(BaseModel):
    action: Literal["output"] = "output"
    pin: str
    action_output: OutputActionTypes

    @field_validator("action_output", mode="before")
    @classmethod
    def validate_action_output(cls, v: str) -> str:
        return v.lower()


class MqttActionConfig(BaseModel):
    action: Literal["mqtt"] = "mqtt"
    action_mqtt_msg: str
    topic: str


class CoverActionConfig(BaseModel):
    action: Literal["cover"] = "cover"
    pin: str
    action_cover: CoverActionTypes
    data: ActionDataConfig | None = None

    @field_validator("action_cover", mode="before")
    @classmethod
    def validate_action_cover(cls, v: str) -> str:
        return v.lower()


class OutputOverMqttActionConfig(BaseModel):
    action: Literal["output_over_mqtt"] = "output_over_mqtt"
    pin: str
    boneio_id: str
    action_output: OutputActionTypes

    @field_validator("action_output", mode="before")
    @classmethod
    def validate_action_output(cls, v: str) -> str:
        return v.lower()


class CoverOverMqttActionConfig(BaseModel):
    action: Literal["cover_over_mqtt"] = "cover_over_mqtt"
    pin: str
    boneio_id: str
    action_cover: CoverActionTypes

    @field_validator("action_cover", mode="before")
    @classmethod
    def validate_action_cover(cls, v: str) -> str:
        return v.lower()


ActionConfig = Annotated[
    (
        OutputActionConfig
        | MqttActionConfig
        | CoverActionConfig
        | CoverOverMqttActionConfig
        | OutputOverMqttActionConfig
    ),
    Discriminator("action"),
]


EventActionTypes = Literal["single", "double", "long"]


class EventConfig(BaseModel):
    pin: str
    id: str | None = None
    boneio_input: BoneIOInput | None = None
    actions: dict[EventActionTypes, list[ActionConfig]] = Field(default_factory=dict)
    device_class: Literal["button", "doorbell", "motion"] = "button"
    show_in_ha: bool = True
    inverted: bool = False
    gpio_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] = "gpio"
    detection_type: Literal["new", "old"] = "new"
    clear_message: bool = False
    bounce_time: timedelta = timedelta(milliseconds=30)

    @field_validator("boneio_input", mode="before")
    @classmethod
    def validate_boneio_input(cls, v: str) -> str:
        return v.lower()

    def identifier(self) -> str:
        if self.id:
            return (self.id).replace(" ", "")
        return self.pin


BinarySensorActionTypes = Literal["pressed", "released"]


class BinarySensorConfig(BaseModel):
    pin: str
    id: str | None = None
    boneio_input: BoneIOInput | None = None
    device_class: (
        Literal[
            "battery",
            "cold",
            "connectivity",
            "door",
            "garage_door",
            "gas",
            "heat",
            "light",
            "lock",
            "moisture",
            "motion",
            "occupancy",
            "opening",
            "plug",
            "power",
            "presence",
            "safety",
            "smoke",
            "sound",
            "vibration",
            "window",
        ]
        | None
    ) = None
    actions: dict[BinarySensorActionTypes, list[ActionConfig]] = Field(
        default_factory=dict
    )
    show_in_ha: bool = True
    inverted: bool = False
    gpio_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] = "gpio"
    detection_type: Literal["new", "old"] = "new"
    clear_message: bool = False
    bounce_time: timedelta = timedelta(milliseconds=120)
    initial_send: bool = False

    @field_validator("boneio_input", mode="before")
    @classmethod
    def validate_boneio_input(cls, v: str) -> str:
        return v.lower()

    def identifier(self) -> str:
        if self.id:
            return (self.id).replace(" ", "")
        return self.pin


OutputTypes: TypeAlias = Literal["cover", "light", "switch", "valve", "none"]


class OutputConfigBase(BaseModel):
    id: str
    pin: int
    output_type: OutputTypes
    kind: Literal["gpio", "mcp", "pca", "pcf", "mock"]
    boneio_output: str | None = None
    momentary_turn_on: timedelta | None = None
    momentary_turn_off: timedelta | None = None
    virtual_power_usage: str | None = None
    virtual_volume_flow_rate: str | None = None
    restore_state: bool = True
    interlock_group: str | list[str] = Field(default_factory=list)


class McpOutputConfig(OutputConfigBase):
    mcp_id: str
    kind: Literal["mcp"] = "mcp"


class PcaOutputConfig(OutputConfigBase):
    pca_id: str
    kind: Literal["pca"] = "pca"
    percentage_default_brightness: int | None = None


class PcfOutputConfig(OutputConfigBase):
    pcf_id: str
    kind: Literal["pcf"] = "pcf"


class GpioOutputConfig(OutputConfigBase):
    kind: Literal["gpio"] = "gpio"


class MockOutputConfig(OutputConfigBase):
    kind: Literal["mock"] = "mock"


OutputConfigKinds: TypeAlias = (
    McpOutputConfig
    | PcaOutputConfig
    | PcfOutputConfig
    | GpioOutputConfig
    | MockOutputConfig
)


class OutputConfig(RootModel[OutputConfigKinds]):
    root: OutputConfigKinds = Field(discriminator="kind")


class OutputGroupConfig(BaseModel):
    id: str
    outputs: list[str]
    all_on_behaviour: bool = False
    output_type: Literal["switch", "light"] = "switch"

    def identifier(self) -> str:
        return self.id.replace(" ", "")


class SensorConfig(BaseModel):
    address: int
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=60))
    filters: list[dict[Filters, float]] = Field(default_factory=list)
    unit_of_measurement: Literal["°C", "°F"] = "°C"
    id: str | None = None
    show_in_ha: bool = True
    bus_id: int | None = None
    platform: Literal["dallas"] = "dallas"


class BoneIOConfig(BaseModel):
    name: str = BONEIO
    device_type: Literal[
        "32x10A",
        "32x10",
        "32",
        "24x16A",
        "24x16",
        "24",
        "cover",
        "cover mix",
        "cm",
        "32x10a",
        "24x16a",
        "mock",
    ] = "cover"
    version: float = 0.9


class WebAuthConfig(BaseModel):
    username: str | None = None
    password: str | None = None


class WebConfig(BaseModel):
    auth: WebAuthConfig | None = None
    port: int = 8090

    def is_auth_required(self) -> bool:
        return (
            self.auth is not None
            and self.auth.username is not None
            and self.auth.password is not None
        )

    def validate_auth(self, username: str, password: str) -> bool:
        if not self.is_auth_required():
            return True
        return self.auth.username == username and self.auth.password == password


class AdcConfig(BaseModel):
    pin: Literal["P9_33", "P9_35", "P9_36", "P9_37", "P9_38", "P9_39", "P9_40"]
    id: str | None = None
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=60))
    show_in_ha: bool = True
    filters: list[dict[Filters, float]] = Field(default_factory=list)


LoggerLevels = Literal["critical", "error", "warning", "info", "debug"]


class LoggerConfig(BaseModel):
    default: LoggerLevels | None = None
    logs: dict[str, LoggerLevels] = Field(default_factory=dict)


Uarts = Literal["uart1", "uart2", "uart3", "uart4", "uart5"]


class UartConfig(BaseModel):
    id: str
    tx: str
    rx: str | None = None


UartsConfig: dict[Uarts, UartConfig] = {
    "uart1": UartConfig(id="/dev/ttyS1", tx="P9.24", rx="P9.26"),
    "uart2": UartConfig(id="/dev/ttyS2", tx="P9.21", rx="P9.22"),
    "uart3": UartConfig(id="/dev/ttyS3", tx="P9.42", rx=None),
    "uart4": UartConfig(id="/dev/ttyS4", tx="P9.13", rx="P9.11"),
    "uart5": UartConfig(id="/dev/ttyS5", tx="P8.37", rx="P8.38"),
}

ModbusParity = Literal["N", "E", "O"]


class ModbusConfig(BaseModel):
    uart: Uarts
    baudrate: int = 9600
    stopbits: int = Field(default=1, ge=1, le=2)
    bytesize: int = 8
    parity: ModbusParity = "N"


ModbusDeviceDataNames = Literal["width", "length"]
ModbusDeviceData = dict[ModbusDeviceDataNames, str | int | float]
ModbusDeviceSensorFilterNames = Literal["temperature", "humidity"]
ModbusDeviceSensorFilters = dict[
    ModbusDeviceSensorFilterNames, list[dict[Filters, float]]
]


class ModbusDeviceConfig(BaseModel):
    id: str
    address: int
    model: Literal[
        "cwt",
        "dts1964_3f",
        "liquid-sensor",
        "orno-or-we-517",
        "pt100",
        "fujitsu-ac",
        "r4dcb08",
        "sdm120",
        "sdm630",
        "sht20",
        "sht30",
        "socomec_e03",
        "socomec_e23",
        "sofar",
        "ventclear",
    ]
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=30))
    sensor_filters: ModbusDeviceSensorFilters | None = None
    data: ModbusDeviceData | None = None

    def identifier(self) -> str:
        return self.id.replace(" ", "")


class ExpanderConfig(BaseModel):
    address: int
    id: str | None = None
    init_sleep: timedelta = Field(default_factory=lambda: timedelta(seconds=0))

    def identifier(self) -> str:
        if self.id:
            return (self.id).replace(" ", "")
        return str(self.address)


class Mcp23017Config(ExpanderConfig):
    pass


class Pcf8575Config(ExpanderConfig):
    pass


class Pca9685Config(ExpanderConfig):
    pass


class CoverConfig(BaseModel):
    id: str
    open_relay: str
    close_relay: str
    platform: Literal["time_based", "venetian", "previous"]
    open_time: timedelta
    close_time: timedelta
    tilt_duration: timedelta | None = None
    actuator_activation_duration: timedelta | None = None
    restore_state: bool = False
    device_class: (
        Literal[
            "awning",
            "blind",
            "curtain",
            "damper",
            "door",
            "garage",
            "gate",
            "shade",
            "shutter",
            "window",
        ]
        | None
    ) = None
    show_in_ha: bool = True

    def identifier(self) -> str:
        return self.id.replace(" ", "")


class Ds2482Config(BaseModel):
    address: str
    id: str | None = None

    def identifier(self) -> str:
        if self.id:
            return self.id.replace(" ", "")
        return self.address


class DallasConfig(BaseModel):
    id: str


class Config(BaseModel):
    boneio: BoneIOConfig
    mqtt: MqttConfig | None = None
    oled: OledConfig | None = None
    lm75: list[Lm75Config] = Field(default_factory=list)
    mcp9808: list[Mcp9808Config] = Field(default_factory=list)
    ina219: list[Ina219Config] = Field(default_factory=list)
    mcp23017: list[Mcp23017Config] = Field(default_factory=list)
    pcf8575: list[Pcf8575Config] = Field(default_factory=list)
    pca9685: list[Pca9685Config] = Field(default_factory=list)
    sensor: list[SensorConfig] = Field(default_factory=list)
    binary_sensor: list[BinarySensorConfig] = Field(default_factory=list)
    event: list[EventConfig] = Field(default_factory=list)
    output: list[OutputConfig] = Field(default_factory=list)
    output_group: list[OutputGroupConfig] = Field(default_factory=list)
    cover: list[CoverConfig] = Field(default_factory=list)
    adc: list[AdcConfig] = Field(default_factory=list)
    modbus_devices: list[ModbusDeviceConfig] = Field(default_factory=list)
    ds2482: list[Ds2482Config] = Field(default_factory=list)
    web: WebConfig | None = None
    modbus: ModbusConfig | None = None
    dallas: DallasConfig | None = None
    logger: LoggerConfig | None = None

    def get_topic_prefix(self) -> str:
        if self.mqtt is not None:
            return self.mqtt.topic_prefix
        return "boneio"

    def get_ha_autodiscovery_topic_prefix(self) -> str:
        if self.mqtt is not None:
            return self.mqtt.ha_discovery.topic_prefix
        return "homeassistant"
