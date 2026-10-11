"""Bounded versioned settings and unique directory probes; no price fallback."""
import json
import os
from pathlib import Path
import tempfile

from .transactions import FileFailure


def decode_settings(raw, kind):
    if raw is None or len(raw) > 1024 * 1024:
        raise FileFailure("设置缺失或超过1MiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("重复字段")
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique)
        fields = {"local": {"schema", "data_root", "backup_dir"},
                  "shared": {"schema", "price_file", "export_dir", "screenshot_dir"}}[kind]
        if type(data) is not dict or set(data) != fields or data["schema"] != "777-" + kind + "-v1":
            raise ValueError("未知设置版本或字段")
        for key in fields - {"schema"}:
            value = data[key]
            if type(value) is not str or len(value) > 32767 or any(ord(c) < 32 for c in value) or (key != "backup_dir" and not value.strip()):
                raise ValueError("无效路径：" + key)
        return data
    except (ValueError, RecursionError, TypeError) as exc:
        raise FileFailure("设置校验失败：" + str(exc)) from exc


def encode_settings(data, kind):
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    decode_settings(raw, kind)
    return raw


def probe_directory(path):
    """Create/clean only our exclusive random probe, never a fixed test file."""
    Path(path).mkdir(parents=True, exist_ok=True)
    fd, owned = tempfile.mkstemp(prefix=".777-probe-", suffix=".tmp", dir=path)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"777 directory probe\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.unlink(owned)
