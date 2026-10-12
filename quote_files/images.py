"""PNG publication through the existing verified file protocol; no overwrites."""
from io import BytesIO
import uuid

from .transactions import digest, transact


def save_png(path, image, *, on_request=None):
    from PIL.PngImagePlugin import PngInfo
    request_id = str(uuid.uuid4())
    if on_request:
        on_request(request_id)
    metadata = PngInfo()
    metadata.add_text("777_request_id", request_id)
    source = BytesIO()
    image.save(source, format="PNG", pnginfo=metadata)
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
