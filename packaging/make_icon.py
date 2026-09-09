"""rebuild the simple ald monogram icon; pillow is only a build dependency."""

from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((64, 64, 960, 960), radius=150, fill="#eef4f8", outline="#afc5d6", width=12)
draw.rectangle((160, 224, 864, 248), fill="#92c7e7")

# draw the letters directly so the icon needs no installed font.

ink = "#34668b"
draw.line([(195, 690), (281, 362), (367, 690)], fill=ink, width=40, joint="curve")
draw.line([(232, 558), (330, 558)], fill=ink, width=36)
draw.line([(432, 367), (432, 674), (552, 674)], fill=ink, width=40, joint="curve")
draw.line([(630, 691), (630, 366), (741, 366), (808, 426), (808, 614), (741, 674), (630, 674)],
    fill=ink, width=40, joint="curve")
directory = Path(__file__).parent
image.save(directory/"ald-reactor.png")
image.save(directory/"ald-reactor.icns")
