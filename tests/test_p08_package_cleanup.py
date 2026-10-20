"""Exercise owned file cleanup only; no installer/build preparation is performed."""
import json
import sys
import tempfile
import threading
import types
import unittest
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from p08_automatic.package_cleanup import cleanup, remember_output

class CleanupTests(unittest.TestCase):
    def owner(self, root):
        return types.SimpleNamespace(dev=types.SimpleNamespace(DEV=root, ROOT=root), preferences={'output':str(root/'packages')}, job=None,worker=None,job_lock=threading.Lock(),package_status=lambda:{'job':None})

    def package(self, owner, delivery='manager', partial=False):
        key=str(uuid.uuid4());path=owner.dev.DEV/'packages'/f'{delivery}-1.0.0-{key[:8]}'
        path.mkdir(parents=True);(path/'installer.exe').write_bytes(b'test artifact')
        row=dict(id=key,output=str(path),delivery=delivery,version='1.0.0')
        if partial:
            remember_output(owner,row)
            stage=owner.dev.DEV/'local-issuance'/(key+'.bin.stage');stage.mkdir(parents=True)
            (stage/'build-state.json').write_text(json.dumps({**row,'package_id':key}))
        else:(path/'release.json').write_text(json.dumps({**row,'schema':'777-desktop-release-v1','package_id':key}))
        return path

    def test_discovery_preview_and_deletion_preserve_other_files_and_signer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);owner=self.owner(root)
            first=self.package(owner);second=self.package(owner,'sales',True)
            unrelated=root/'packages'/'my-document.txt';unrelated.write_text('keep')
            signer=root/'local-signer.bin';signer.write_text('keep')
            self.assertEqual(cleanup(owner)['count'],2);self.assertTrue(first.exists())
            self.assertEqual(cleanup(owner,True)['cleaned'],2)
            self.assertFalse(first.exists());self.assertFalse(second.exists())
            self.assertEqual(unrelated.read_text(),'keep');self.assertEqual(signer.read_text(),'keep')
            self.assertEqual(list((root/'local-issuance').iterdir()),[])
            self.assertEqual(cleanup(owner)['count'],0)

    def test_active_job_blocks_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            owner=self.owner(Path(folder));owner.job={'state':'running'}
            with self.assertRaisesRegex(RuntimeError,'PACKAGE_CLEANUP_BUSY'):cleanup(owner,True)

    def test_link_and_business_file_abort_before_deleting_any_package(self):
        for kind in ['link','business']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);owner=self.owner(root);first=self.package(owner);second=self.package(owner,'sales')
                if kind=='link':
                    try:(second/'linked').symlink_to(first,target_is_directory=True)
                    except OSError:self.skipTest('symlink creation unavailable')
                else:(second/'ledger.sqlite3').write_text('business')
                with self.assertRaisesRegex(RuntimeError,'PACKAGE_CLEANUP_UNSAFE'):cleanup(owner,True)
                self.assertTrue(first.exists());self.assertTrue(second.exists())

if __name__=='__main__':unittest.main()
