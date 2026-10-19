"""services/upload_security.py — verify that an uploaded "image" really is one."""
from PIL import Image


def is_real_image(file_storage) -> bool:
    """True if the upload decodes as an image Pillow recognises (png/jpeg/gif/webp)."""
    try:
        pos = file_storage.stream.tell()
        with Image.open(file_storage.stream) as img:
            img.verify()
            ok = (img.format or '').upper() in {'PNG', 'JPEG', 'GIF', 'WEBP'}
        file_storage.stream.seek(pos)
        return ok
    except Exception:
        try:
            file_storage.stream.seek(0)
        except Exception:
            pass
        return False
