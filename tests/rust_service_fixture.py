"""Reuse the unchanged real HTTPS fixture, selecting Rust before it starts."""
import os
from unittest.mock import patch
from pathlib import Path
import service_fixture
from quote_service.hosting import initialize
from quote_service.backend import select_backend
ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/'target/release'/('quote-ledger.exe' if os.name=='nt' else 'quote-ledger')
def initialize_rust(root,backup_dir,user,secret,**kwargs):
    initialize(root,backup_dir,user,secret,**kwargs)
    return select_backend(root,user,secret,'rust',binary=BINARY,notices=ROOT/'THIRD_PARTY_NOTICES.md',auxiliary=kwargs.get('auxiliary',False))
class Hosted(service_fixture.Hosted):
    def __init__(self):
        with patch.object(service_fixture,'initialize',initialize_rust):super().__init__()
