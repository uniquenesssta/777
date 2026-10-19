"""Allow operation IDs, block accidental credentials and full financial payloads."""
import re

def valid_id(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,96}',value) is not None

def safe(value):
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            k=str(key).lower()
            secret=k in {'password','secret','ticket','token','authorization','private_key','private_key_pem','body','payload','request','response','orders','customer'} or k.endswith(('_password','_secret','_token','_ticket','_private_key','_body'))
            result[key]='[redacted]' if secret else safe(item)
        return result
    if isinstance(value,(list,tuple)):return [safe(item) for item in value[:64]]
    if isinstance(value,str) and ('PRIVATE KEY' in value or len(value)>4096):return '[omitted]'
    return value
