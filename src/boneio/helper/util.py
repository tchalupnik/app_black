import json
import unicodedata
from pathlib import Path
from typing import Any


def strip_accents(s: str) -> str:
    """Remove accents and spaces from a string."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn" and c != " "
    )


def open_json(path: str, model: str) -> dict:
    """Open json file."""
    file_path = Path(path) / f"{model}.json"
    with file_path.open("r") as db_file:
        datastore = json.load(db_file)
        return datastore


def find_key_by_value(d: dict, value: Any) -> Any:
    for k, v in d.items():
        if v == value:
            return k
    return None
