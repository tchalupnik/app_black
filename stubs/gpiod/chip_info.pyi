from dataclasses import dataclass

__all__ = ["ChipInfo"]

@dataclass(frozen=True, repr=False)
class ChipInfo:
    name: str
    label: str
    num_lines: int
