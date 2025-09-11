from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel, field_validator

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
    host: str = "localhost"
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
    id: str | None = None
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=60))
    filters: list[dict[Filters, float]] = Field(default_factory=list)
    unit_of_measurement: Literal["°C", "°F"] = "°C"


Ina219DeviceClass = Literal["voltage", "current", "power"]


class Ina219SensorConfig(BaseModel):
    id: str
    device_class: Ina219DeviceClass
    filters: list[dict[Filters, float]] = Field(default_factory=list)


class Ina219Config(BaseModel):
    address: int
    id: str | None = None
    sensors: list[Ina219SensorConfig] = Field(default_factory=list)
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=60))


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


EventActionTypes = Literal["single", "double", "long"]


class EventConfig(BaseModel):
    id: str
    pin: str
    boneio_input: BoneIOInput
    actions: dict[EventActionTypes, list[EventActionConfig]] = Field(
        default_factory=dict
    )
    device_class: Literal["button", "doorbell", "motion"]
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


class BinarySensorAction(BaseModel):
    action: Literal[
        "mqtt",
        "output",
        "output_over_mqtt",
        "cover",
        "cover_over_mqtt",
    ]
    action_mqtt_msg: str
    pin: str
    topic: str
    action_cover: Literal[
        "toggle", "open", "close", "stop", "tilt", "tilt_open", "tilt_close"
    ] = "toggle"
    boneio_id: str | None = None
    action_output: Literal["toggle", "on", "off"] = "toggle"


BinarySensorActionTypes = Literal["pressed", "released"]


class BinarySensorConfig(BaseModel):
    id: str
    pin: str
    boneio_input: BoneIOInput
    device_class: Literal[
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
    actions: dict[BinarySensorActionTypes, list[BinarySensorAction]] = Field(
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


class OutputConfig(BaseModel):
    id: str
    output_type: Literal["cover", "light", "switch", "valve", "none"]
    kind: Literal["gpio", "mcp", "pca", "pcf"] | None = None
    boneio_output: str | None = None
    pin: int | None = None
    momentary_turn_on: timedelta | None = None
    momentary_turn_off: timedelta | None = None
    virtual_power_usage: str | None = None
    virtual_volume_flow_rate: str | None = None
    restore_state: bool | None = None
    interlock_group: str | list[str] = Field(default_factory=list)
    percentage_default_brightness: int | None = None
    mcp_id: str | None = None
    pca_id: str | None = None
    pcf_id: str | None = None


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
    update_interval: timedelta = Field(default_factory=lambda: timedelta(seconds=60))
    show_in_ha: bool = True
    filters: list[dict[Filters, float]] = Field(default_factory=list)


class Config(BaseModel):
    boneio: BoneIOConfig
    mqtt: MqttConfig | None = None
    oled: OledConfig | None = None
    lm75: list[TemperatureConfig] = Field(default_factory=list)
    mcp9808: list[TemperatureConfig] = Field(default_factory=list)
    ina219: list[Ina219Config] = Field(default_factory=list)
    sensors: list[SensorConfig] = Field(default_factory=list)
    binary_sensors: list[BinarySensorConfig] = Field(default_factory=list)
    event: list[EventConfig] = Field(default_factory=list)
    output: list[OutputConfig] = Field(default_factory=list)
    adc: list[AdcConfig] = Field(default_factory=list)
    web: WebConfig | None = None
