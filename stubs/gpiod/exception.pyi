__all__ = ["ChipClosedError", "RequestReleasedError"]

class ChipClosedError(Exception):
    def __init__(self) -> None: ...

class RequestReleasedError(Exception):
    def __init__(self) -> None: ...
