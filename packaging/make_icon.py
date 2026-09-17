"""package the supplied white-backed lily render as the desktop icon."""

from pathlib import Path
from PIL import Image

source = Path(__file__).with_name("ald-reactor.png")
with Image.open(source) as image:
    image.save(source.with_suffix(".icns"))
