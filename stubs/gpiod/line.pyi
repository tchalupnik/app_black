from enum import Enum

class Value(Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"

class Direction(Enum):
    AS_IS = "AS_IS"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"

class Bias(Enum):
    AS_IS = "AS_IS"
    UNKNOWN = "UNKNOWN"
    DISABLED = "DISABLED"
    PULL_UP = "PULL_UP"
    PULL_DOWN = "PULL_DOWN"

class Drive(Enum):
    PUSH_PULL = "PUSH_PULL"
    OPEN_DRAIN = "OPEN_DRAIN"
    OPEN_SOURCE = "OPEN_SOURCE"

class Edge(Enum):
    NONE = "NONE"
    RISING = "RISING"
    FALLING = "FALLING"
    BOTH = "BOTH"

class Clock(Enum):
    MONOTONIC = "MONOTONIC"
    REALTIME = "REALTIME"
    HTE = "HTE"
