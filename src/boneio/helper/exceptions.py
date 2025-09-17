"""BoneIO Errors"""


class BoneIOException(Exception):
    """BoneIO standard exception."""


class I2CError(BoneIOException):
    """I2C Exception."""


class OneWireError(BoneIOException):
    """One Wire Exception."""


class CoverConfigurationError(BoneIOException):
    """Cover configuration exception."""


class CoverRelayException(BoneIOException):
    """Cover configuration exception."""


class ModbusUartException(BoneIOException):
    """Cover configuration exception."""
