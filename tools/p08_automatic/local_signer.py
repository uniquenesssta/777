"""Offline developer identity. Initialization and signing never contact the Host."""
import os
import re
import subprocess
import time
from .issuer import Issuer

class LocalSigner(Issuer):
    def __init__(self, owner):
        super().__init__(owner)
        self.state = owner.dev.DEV / 'local-signer.bin'

    def status(self, refresh=False):
        if not refresh and self.cache is not None and time.monotonic()-self.checked < 10:
            return self.cache
        if os.name != 'nt':
            return dict(ready=False, phase='windows_required', interfaces=[])
        try:
            result = self.native(['automatic-local-status', '--state', str(self.state)])
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            code = str(error)
            result = dict(ready=False, phase='unavailable', error=code if re.fullmatch(r'[A-Z0-9_]{1,128}', code) else 'LOCAL_SIGNER_UNAVAILABLE')
        self.cache = {k: result.get(k) for k in ['ready', 'phase', 'issuer_id', 'error']}
        self.cache['interfaces'] = []
        self.checked = time.monotonic()
        return self.cache
