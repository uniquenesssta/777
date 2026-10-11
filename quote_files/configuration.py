"""Optimistic, backed-up configuration publication without schema mutation."""
from .transactions import digest, transact
from .workbooks import request


def save_config(path, source, *, expected_hash, validator, pending=None):
    validator(source)
    fingerprint = digest(source)
    req = pending if pending and pending.fingerprint == fingerprint else request("config_save", {})
    from dataclasses import replace
    req = replace(req, fingerprint=fingerprint)
    result = {"fingerprint": fingerprint, "config_sha256": fingerprint}
    def inspect(raw, request_id):
        return result if digest(raw) == fingerprint else None
    try:
        committed = transact(path, req.request_id, fingerprint, "config_save",
                             lambda raw: (source, result), inspect, expected_hash=expected_hash)
    except Exception as error:
        error.pending_request = req
        if getattr(error, "request_id", None) and error.request_id != req.request_id:
            error.blocking_request_id = error.request_id
        else:
            error.request_id = req.request_id
        raise
    return committed, req
