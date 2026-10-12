"""PNG publication through the existing verified file protocol; no overwrites."""
from io import BytesIO
import uuid
import re
from pathlib import Path

from .transactions import digest, transact


def save_png(path, image, *, on_request=None, metadata=None):
    from PIL.PngImagePlugin import PngInfo
    request_id = str(uuid.uuid4())
    if on_request:
        on_request(request_id)
    info = PngInfo()
    info.add_text("777_request_id", request_id)
    for key,value in (metadata or {}).items():
        info.add_text(key,str(value))
    source = BytesIO()
    image.save(source, format="PNG", pnginfo=info)
    raw = source.getvalue()
    from PIL import Image
    with Image.open(BytesIO(raw)) as check:
        check.verify()
    fingerprint = digest(raw)
    receipt = {"fingerprint": fingerprint}
    return transact(path, request_id, fingerprint, "screenshot",
        lambda before: (raw, receipt),
        lambda data, rid: receipt if digest(data) == fingerprint else None,
        expected_hash=None)


def filename_part(text):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(text)).strip(' .')
    return text[:16].strip(' .') or '未填写'


def unique_window_path(folder, details):
    return Path(folder) / f'窗口_{filename_part(details.customer)}_{filename_part(details.order_ref)}_{uuid.uuid4().hex}.png'
