from pathlib import Path

from PIL import ImageFont


def make_font(name: str, size: int, local: bool = False):
    """Prepare ImageFont for Oled screen."""
    font_path = name if not local else (Path(__file__).parent / ".." / "fonts" / name)
    return ImageFont.truetype(font_path, size)
