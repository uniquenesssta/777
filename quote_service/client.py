"""HTTPS-only direct client; pinned certificate, no proxy, redirect or role claim."""
from dataclasses import asdict
import hashlib
import http.client
import json
from pathlib import Path
import ssl
from urllib.parse import urlsplit
import uuid

from .protocol import APIError,BODY_LIMIT,fields,decode,text


class CommitUnknown(Exception):
    def __init__(self,request_id):
        self.request_id=request_id
        super().__init__('提交结果未确认；保留原请求并查询回执')


def connection_settings(value):
    fields(value,{'schema','url','certificate','certificate_sha256','username'})
    if value['schema']!='777-service-client-v1':raise APIError(422,'CLIENT_CONFIG_INVALID')
    parsed=urlsplit(text(value['url'],2048,nonempty=True))
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:raise APIError(422,'HTTPS_SERVICE_ADDRESS_REQUIRED')
    try:port=parsed.port or 443
    except ValueError:raise APIError(422,'INVALID_PORT') from None
    if not 1<=port<=65535:raise APIError(422,'INVALID_PORT')
    if type(value['certificate_sha256']) is not str or len(value['certificate_sha256'])!=64 or any(c not in '0123456789abcdef' for c in value['certificate_sha256']):raise APIError(422,'INVALID_CERTIFICATE_PIN')
    text(value['certificate'],32767,nonempty=True);text(value['username'],64)
    return dict(value)


class Client:
    def __init__(self,settings,*,timeout=10):
        self.settings=connection_settings(settings);self.timeout=timeout
        self.token='';self.subject=None;self.role=None

    def request(self,method,path,data=None):
        if not path.startswith('/v1/') or '#' in path:raise APIError(422,'INVALID_API_PATH')
        raw=Path(self.settings['certificate']).read_bytes()
        if len(raw)>65536:raise APIError(422,'CERTIFICATE_TOO_LARGE')
        der=ssl.PEM_cert_to_DER_cert(raw.decode('ascii'))
        if hashlib.sha256(der).hexdigest()!=self.settings['certificate_sha256']:raise APIError(403,'CERTIFICATE_PIN_MISMATCH')
        context=ssl.create_default_context(cadata=raw.decode('ascii'));context.minimum_version=ssl.TLSVersion.TLSv1_2
        parsed=urlsplit(self.settings['url']);connection=http.client.HTTPSConnection(parsed.hostname,parsed.port or 443,context=context,timeout=self.timeout)
        try:
            connection.connect()
            self.last_tls_version=connection.sock.version()
            if hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()!=self.settings['certificate_sha256']:raise APIError(403,'CERTIFICATE_PIN_MISMATCH')
            body=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8') if data is not None else None
            if body is not None and len(body)>BODY_LIMIT:raise APIError(413,'BODY_TOO_LARGE')
            headers={'Accept':'application/json'}
            if body is not None:headers['Content-Type']='application/json'
            if self.token:headers['Authorization']='Bearer '+self.token
            connection.request(method,path,body=body,headers=headers)
            response=connection.getresponse();result=decode(response.read(8*BODY_LIMIT+1),maximum=8*BODY_LIMIT)
            # Responses can contain a bounded 200-order page with full details.
            if response.status==202 and result.get('error')=='COMMIT_UNKNOWN':raise CommitUnknown(result['request_id'])
            if response.status!=200:raise APIError(response.status,result.get('error','SERVICE_RESPONSE_INVALID'))
            return result
        finally:connection.close()

    def login(self,user,secret):
        result=self.request('POST','/v1/login',{'username':user,'password':secret})
        self.token=result['token'];self.subject=result['subject'];self.role=result['role']
        return {k:result[k] for k in ('subject','role','expires')}

    def logout(self):
        try:return self.request('POST','/v1/logout',{})
        finally:self.token='';self.subject=None;self.role=None

    def submit(self,snapshot,details,journal):
        return self.mutate('/v1/orders',{'snapshot':asdict(snapshot),'details':asdict(details)},journal)

    def mutate(self,path,payload,journal):
        if path not in {'/v1/orders','/v1/notes','/v1/state','/v1/prices'}:raise APIError(422,'INVALID_MUTATION')
        if 'request_id' in payload:raise APIError(422,'REQUEST_ID_ASSIGNED_BY_JOURNAL')
        if journal.read() is not None:raise APIError(409,'PENDING_REQUEST_REQUIRES_QUERY')
        body={'request_id':str(uuid.uuid4()),**payload}
        pending={'schema':'777-pending-v1','path':path,'body':body,'subject':self.subject,
                 'url':self.settings['url'],'certificate_sha256':self.settings['certificate_sha256']}
        if not self.subject:raise APIError(401,'UNAUTHENTICATED')
        journal.write(pending)  # Must persist before the first network send.
        return self._send_pending(pending,journal)

    def _send_pending(self,pending,journal):
        self._check_pending(pending)
        try:result=self.request('POST',pending['path'],pending['body'])
        except APIError as exc:
            if exc.status>=500:raise CommitUnknown(pending['body']['request_id']) from None
            journal.clear();raise
        except Exception:raise CommitUnknown(pending['body']['request_id']) from None
        journal.clear();return result

    def _check_pending(self,pending):
        fields(pending,{'schema','path','body','subject','url','certificate_sha256'})
        if pending['schema']!='777-pending-v1' or pending['path'] not in {'/v1/orders','/v1/notes','/v1/state','/v1/prices'} or pending['subject']!=self.subject or pending['url']!=self.settings['url'] or pending['certificate_sha256']!=self.settings['certificate_sha256']:raise APIError(403,'PENDING_IDENTITY_MISMATCH')

    def check_pending(self,journal,*,retry=False):
        pending=journal.read()
        if pending is None:return {'result':None,'pending':False}
        self._check_pending(pending)
        receipt=self.request('GET','/v1/requests/'+pending['body']['request_id'])
        if receipt['result'] is not None:journal.clear();return {'result':receipt['result'],'pending':False}
        if retry:return {'result':self._send_pending(pending,journal),'pending':False}
        return {'result':None,'pending':True,'request_id':pending['body']['request_id']}
