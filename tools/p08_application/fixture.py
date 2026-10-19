"""Own the isolated Host lifecycle and enroll real scoped business devices."""
import hashlib
import secrets
import time
from native_host_fixture import Hosted, command
from .client import PinnedAPI
from .owner import seed_owner
from .wire import FORMAT, PROTOCOLS, envelope, identifier, operation


class ApplicationFixture:
    def __init__(self):
        self.host = Hosted()
        self.api = PinnedAPI(self.host)
        try:
            self.host.stop()
            # Only the trusted owner's initial site/issuer records are seeded.
            # No device/session/receipt/order/result is fabricated. All later
            # enrollment and business requests cross the actual pinned HTTPS Host.
            self.site,self.issuer,self.issuer_secret=seed_owner(self.host)
            command('enable-offline-application', root=self.host.host_root, admin='manager', secret=self.host.password)
            self.host.start()
            self.admin = self.host.client('manager')
            session = self.call('/v1/automatic/issuer/session', envelope(PROTOCOLS['issuance'], issuer_id=self.issuer), token=self.issuer_secret)
            package, package_secret, self.device, device_secret = identifier(), secrets.token_urlsafe(32), identifier(), secrets.token_urlsafe(32)
            manifest = dict(format='777-package-manifest-v1', package_id=package, issuer_id=self.issuer,
                            site_id=self.site, ledger_id=self.host.config['ledger_id'], trust_revision=1,
                            delivery='manager', capabilities=['edit_orders', 'orders', 'quote'], node_enrollment=True,
                            release_version='isolated-runtime', artifact_sha256=hashlib.sha256(b'fixture; no installer built').hexdigest(),
                            protocols=PROTOCOLS, enroll_before=int(time.time()) + 3600, max_devices=2, max_nodes=1)
            self.call('/v1/automatic/packages', envelope(PROTOCOLS['issuance'], manifest=manifest, secret_hash=hashlib.sha256(package_secret.encode()).hexdigest()), token=session['token'])
            self.call('/v1/automatic/devices/enroll', envelope(PROTOCOLS['enrollment'], package_id=package,
                      site_id=self.site, ledger_id=self.host.config['ledger_id'], device_id=self.device,
                      device_secret_hash=hashlib.sha256(device_secret.encode()).hexdigest()), token=package_secret)
            device = self.call('/v1/automatic/devices/session', envelope(PROTOCOLS['scoped_auth'], device_id=self.device), token=device_secret)
            self.token = device['token']
            self.lease = self.call('/v1/offline/lease', dict(protocol=FORMAT, request_id=identifier()))['body']
        except BaseException:
            self.host.close()
            raise

    def call(self,path,body,*,token=None,accepted=(200,202),method='POST'):
        return self.api.call(path,body,token=self.token if token is None else token,accepted=accepted,method=method)

    @property
    def last_status(self):
        return self.api.last_status

    @property
    def tls_version(self):
        return self.api.tls_version

    def operation(self,sequence,**kwargs):
        return operation(self.lease,sequence,**kwargs)

    def send(self, operation):
        response = self.call('/v1/offline/operations', dict(protocol=FORMAT, batch_id=identifier(), operations=[operation]))
        assert self.last_status == 202
        return response

    def wait(self, operation, state):
        deadline = time.monotonic() + 15
        while True:
            result = self.call('/v1/offline/receipts', dict(protocol=FORMAT, operation_ids=[operation['operation_id']]))['receipts'][0]
            if result['state'] == state:
                return result
            assert result['state'] in ['received', 'waiting_dependency'], result
            if time.monotonic() >= deadline:
                raise RuntimeError('APPLICATION_DID_NOT_PROGRESS: ' + str(result))
            time.sleep(.1)

    def close(self):
        self.host.close()
