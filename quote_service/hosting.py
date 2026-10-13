"""Explicit new local host configuration, TLS identity and single-owner runner."""
from datetime import datetime,timedelta,timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl

from quote_ledger import Ledger
from quote_ledger.backup import Backups,publish_json
from quote_ledger.paths import local_path
from quote_ledger.security import protect_directory
from quote_files.transactions import file_lock
from .auth import Auth
from .app import Application,Service
from .protocol import APIError,fields


def certificate(folder,hosts):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    names=[]
    for host in hosts:
        try:names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:names.append(x509.DNSName(host))
    if not names:raise APIError(422,'CERTIFICATE_HOSTS_REQUIRED')
    key=ec.generate_private_key(ec.SECP256R1());subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'777 service')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
          .not_valid_after(now+timedelta(days=365)).add_extension(x509.SubjectAlternativeName(names),False)
          .add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
          .add_extension(x509.KeyUsage(True,False,False,False,False,True,False,False,False),True)
          .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False)
          .sign(key,hashes.SHA256()))
    for name,raw in [('tls-key.pem',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())),
                     ('tls-cert.pem',cert.public_bytes(serialization.Encoding.PEM))]:
        fd=os.open(folder/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def initialize(root,backup_dir,user,secret,*,hosts,bind='127.0.0.1',port=8477,auxiliary=False):
    if os.name!='nt' and not auxiliary:raise APIError(400,'WINDOWS_HOST_REQUIRED')
    if os.name=='nt' and auxiliary:raise APIError(400,'WINDOWS_SECURITY_CANNOT_BE_DISABLED')
    ipaddress.ip_address(bind)
    if type(port) is not int or not 1<=port<=65535 or not hosts:raise APIError(422,'HOST_CONFIG_INVALID')
    from .auth import username,password
    username(user);password(secret)
    from cryptography import x509
    for host in hosts:
        try:ipaddress.ip_address(host)
        except ValueError:x509.DNSName(host)
    root=local_path(root,directory=True,exists=False)
    backup_dir=local_path(backup_dir,directory=True,exists=False)
    if root.exists() or backup_dir.exists():raise FileExistsError('主机与备份必须使用独立新目录')
    root.mkdir(mode=0o700)
    private=root/'private';private.mkdir(mode=0o700)
    security=protect_directory(private) if os.name=='nt' else {'status':'auxiliary_no_native_security_claim'}
    ledger=Ledger.create(private/'ledger.sqlite3');auth=Auth.create(private/'auth.sqlite3',user,secret)
    from .outputs import Outputs
    Outputs.create(private/'outputs.sqlite3', ledger.inventory()['ledger_id'])
    backups=Backups.create(backup_dir,auxiliary=auxiliary)
    fingerprint=certificate(private,hosts)
    config={'schema':'777-host-v1','ledger_id':ledger.inventory()['ledger_id'],'backup_store_id':backups.status()['store_id'],
            'backup_dir':str(backups.root),'bind':bind,'port':port,'certificate_sha256':fingerprint,'private_security':security,'maintenance':False}
    publish_json(private/'service.json',config)
    # Only this public cert/template may be copied to client computers.
    (root/'service-cert.pem').write_bytes((private/'tls-cert.pem').read_bytes())
    publish_json(root/'client-template.json',{'schema':'777-service-client-v1','url':f'https://{hosts[0]}:{port}',
                 'certificate':str(root/'service-cert.pem'),'certificate_sha256':fingerprint,'username':''})
    return config


def load(root,*,auxiliary=False,allow_maintenance=False):
    root=local_path(root,directory=True)
    if os.name!='nt' and not auxiliary:raise APIError(400,'WINDOWS_HOST_REQUIRED')
    raw=local_path(root/'private/service.json').read_bytes()
    if len(raw)>65536:raise APIError(422,'HOST_CONFIG_TOO_LARGE')
    from .protocol import decode
    config=decode(raw)
    fields(config,{'schema','ledger_id','backup_store_id','backup_dir','bind','port','certificate_sha256','private_security','maintenance'},{'ledger_backend','rust_worker_sha256','service_backend','rust_host_sha256'})
    if type(config['maintenance']) is not bool:raise APIError(422,'HOST_CONFIG_INVALID')
    if config['maintenance'] and not allow_maintenance:raise APIError(503,'RECOVERY_MAINTENANCE_REQUIRED')
    if config['schema']!='777-host-v1' or type(config['port']) is not int or not 1<=config['port']<=65535:raise APIError(422,'HOST_CONFIG_INVALID')
    ipaddress.ip_address(config['bind'])
    private=local_path(root/'private',directory=True)
    from .recovery import ConfiguredBackups
    from .backend import selected
    ledger=selected(private,config,auxiliary=auxiliary);auth=Auth(private/'auth.sqlite3');backups=ConfiguredBackups(config['backup_dir'],config['backup_store_id'],auxiliary=auxiliary)
    if ledger.inventory()['ledger_id']!=config['ledger_id']:raise APIError(503,'HOST_STORE_IDENTITY_CONFLICT')
    pem=local_path(private/'tls-cert.pem').read_text(encoding='ascii')
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()!=config['certificate_sha256']:raise APIError(503,'CERTIFICATE_IDENTITY_CONFLICT')
    local_path(private/'tls-key.pem')
    from .native_host import validate_resources
    validate_resources(private, config)
    service=Service(ledger,auth,backups);service.host_root=root;service.auxiliary=auxiliary
    service.host_backend=config.get('service_backend','python')
    if (private/'outputs.sqlite3').exists():
        from .outputs import Outputs
        service.outputs=Outputs(private/'outputs.sqlite3', config['ledger_id'], native=getattr(ledger,'native_formats',None))
    return root,config,service


def server(service,cert,key,*,host='127.0.0.1',port=8477):
    if getattr(service,'host_backend','python')!='python':raise APIError(409,'RUST_HOST_SELECTED')
    import uvicorn
    config=uvicorn.Config(Application(service),host=host,port=port,workers=1,loop='asyncio',http='h11',ws='none',
        lifespan='on',access_log=False,log_level='warning',proxy_headers=False,limit_concurrency=16,
        timeout_keep_alive=5,timeout_graceful_shutdown=45,ssl_version=ssl.PROTOCOL_TLS_SERVER,
        ssl_certfile=str(cert),ssl_keyfile=str(key))
    config.load();config.ssl.minimum_version=ssl.TLSVersion.TLSv1_2
    return uvicorn.Server(config)


def serve(root):
    root,config,service=load(root)
    if config.get('service_backend','python')=='rust':
        import subprocess
        subprocess.run([str(root/'private/rust-service-host.exe'),'run','--root',str(root)],check=True)
        return
    with file_lock(root/'service-owner'):
        server(service,root/'private/tls-cert.pem',root/'private/tls-key.pem',host=config['bind'],port=config['port']).run()


def enable_outputs(root, user, secret, *, auxiliary=False):
    """Explicit offline extension activation for an existing v1 host."""
    root, config, service = load(root, auxiliary=auxiliary)
    with file_lock(root/'service-owner'):
        if service.outputs is not None: raise APIError(409, 'OUTPUTS_ALREADY_INITIALIZED')
        identity = service.auth.login(user, secret, 'local-output-enable')
        try:
            actor = service.auth.authenticate(identity['token']); service.auth.admin(actor)
            service.backup(kind='maintenance')
            from .outputs import Outputs
            Outputs.create(root/'private/outputs.sqlite3', config['ledger_id'])
        finally: service.auth.logout(identity['token'])
    return {'format': '777-output-store-v1', 'ledger_schema_unchanged': True}
