"""Photo uploads on the mounted volume. Stores a resized original and a thumbnail."""
import uuid
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

MAX_SIDE = 2000
THUMB_SIDE = 640


class BadImage(ValueError):
    pass


def save_upload(fileobj: BinaryIO) -> str:
    """Returns the path relative to PHOTOS_DIR, e.g. 'ab/abcdef….jpg'."""
    try:
        img = Image.open(fileobj)
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError) as e:
        raise BadImage(str(e)) from e
    img = img.convert("RGB")
    name = uuid.uuid4().hex
    rel = Path(name[:2]) / f"{name}.jpg"
    dest = get_settings().photos_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    full = img.copy()
    full.thumbnail((MAX_SIDE, MAX_SIDE))
    full.save(dest, "JPEG", quality=86, optimize=True)
    img.thumbnail((THUMB_SIDE, THUMB_SIDE))
    img.save(dest.with_name(f"{name}_t.jpg"), "JPEG", quality=82, optimize=True)
    return rel.as_posix()


def thumb_path(path: str) -> str:
    return path[:-4] + "_t.jpg" if path.endswith(".jpg") else path
