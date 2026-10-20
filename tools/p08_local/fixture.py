"""Actual issuance and isolated route; never replace the production primary URL."""
import hashlib
import json
import secrets
import time
from p08_application.fixture import ApplicationFixture
from p08_application.wire import PROTOCOLS, envelope, identifier


class LocalFixture(ApplicationFixture):
    def package(self, delivery):
        session = self.call('/v1/automatic/issuer/session', envelope(PROTOCOLS['issuance'], issuer_id=self.issuer), token=self.issuer_secret)
        secret = secrets.token_urlsafe(32)
        manifest = dict(format='777-package-manifest-v1', package_id=identifier(), issuer_id=self.issuer,
                        site_id=self.site, ledger_id=self.host.config['ledger_id'], trust_revision=1,
                        delivery=delivery, capabilities=['edit_orders', 'orders', 'quote'], node_enrollment=delivery == 'manager',
                        release_version='isolated-D-runtime', artifact_sha256=hashlib.sha256(b'isolated desktop runtime; no installer').hexdigest(),
                        protocols=PROTOCOLS, enroll_before=int(time.time())+3600, max_devices=16, max_nodes=4 if delivery == 'manager' else 0)
        self.call('/v1/automatic/packages', envelope(PROTOCOLS['issuance'], manifest=manifest,
                  secret_hash=hashlib.sha256(secret.encode()).hexdigest()), token=session['token'])
        public = dict(format='777-site-profile-v1', site_id=self.site, ledger_id=self.host.config['ledger_id'], trust_revision=1,
                      primary_url='https://192.168.4.23:8477', required_protocols=PROTOCOLS,
                      tls=dict(certificate_pem=(self.host.host_root/'service-cert.pem').read_text(), certificate_sha256=self.host.config['certificate_sha256']))
        folder = self.host.root / ('desktop-'+delivery)
        folder.mkdir()
        (folder/'777-isolated-profile.json').write_text('{"production":false}')
        (folder/'offline-test-connection.json').write_text(json.dumps(dict(url=f'https://127.0.0.1:{self.host.port}', **public['tls'])))
        path = folder/'fixture-package.json'
        path.write_text(json.dumps(dict(format='777-automatic-package-v1', profile=public, manifest=manifest, secret=secret)))
        return folder, path
