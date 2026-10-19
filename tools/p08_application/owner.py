"""Install only trusted-owner fixture identity; all sessions use real Host APIs."""
from contextlib import closing
import hashlib
import json
import secrets
import sqlite3
from native_host_fixture import ROOT
from .wire import PROTOCOLS, identifier


def seed_owner(host):
    site, issuer, issuer_secret = identifier(), identifier(), secrets.token_urlsafe(32)
    private = host.host_root / 'private'
    with closing(sqlite3.connect(private / 'auth.sqlite3')) as c:
        c.executescript((ROOT / 'crates/quote-host/src/automatic/schema.sql').read_text())
        c.execute("INSERT INTO principal_modes SELECT id,'legacy_password' FROM users")
        profile = dict(format='777-site-profile-v1', site_id=site,
                       ledger_id=host.config['ledger_id'], trust_revision=1,
                       primary_url='https://192.168.4.23:8477', required_protocols=PROTOCOLS,
                       tls=dict(certificate_pem=(host.host_root / 'service-cert.pem').read_text(),
                                certificate_sha256=host.config['certificate_sha256']))
        c.execute('INSERT INTO site_binding VALUES(1,?,?,?)', (site, host.config['ledger_id'], json.dumps(profile)))
        caps = sorted(item['id'] for item in json.loads((ROOT / 'desktop/permissions.json').read_text()))
        c.execute('INSERT INTO issuers VALUES(?,?,?,1,1)', (issuer, hashlib.sha256(issuer_secret.encode()).hexdigest(), json.dumps(caps)))
        c.execute('PRAGMA user_version=2')
        c.commit()
    return site,issuer,issuer_secret
