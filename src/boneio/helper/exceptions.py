"""BoneIO Errors"""


class I2CError(BaseException):
    """I2C Exception."""


class OneWireError(BaseException):
    """One Wire Exception."""


class CoverConfigurationError(BaseException):
    """Cover configuration exception."""
