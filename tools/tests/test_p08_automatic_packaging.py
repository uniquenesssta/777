"""Controller checks only; no Windows tools, builds or business hosts are started."""
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from p08_automatic import packaging

class Controller(packaging.PackagingMixin):
    def status(self):
        raise AssertionError('unavailable business source must not be read by packaging')

class PackagingTests(unittest.TestCase):
    def controller(self, root):
        c = Controller()
        c.dev = types.SimpleNamespace(DEV=root, ROOT=root)
        c.signer = types.SimpleNamespace(state=root/'local-signer.bin', status=lambda:dict(ready=True))
        c.job_lock = threading.Lock()
        c.cancelled = threading.Event()
        c.preferences = dict(output=str(root/'new-output'), version='9.9.9', runtime='offlineInstaller')
        c.job = None
        return c

    def test_status_uses_issuer_even_when_the_business_source_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            c = self.controller(Path(temp))
            result = c.package_status()
            self.assertTrue(result['issuer']['ready'])
            self.assertNotIn('connection', result)

    def test_retry_keeps_original_identity_version_runtime_and_output_after_preferences_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            c = self.controller(root)
            c.job = dict(id='original-package', signing='local', state='failed', delivery='manager', permissions=['quote'],
                         version='1.2.3', runtime='downloadBootstrapper', output=str(root/'original-output'))
            dependencies = types.SimpleNamespace(local=lambda p,**_:Path(p),package_preferences=lambda v:Path(v['output']),replace_json=Mock())
            with patch.dict(sys.modules, {'p07_developer':dependencies}), patch.object(packaging,'os',types.SimpleNamespace(name='nt',environ={})), patch.object(packaging.threading,'Thread') as thread:
                result = c.package('manager',['quote'],retry=True)
            args = thread.call_args.kwargs['args'][0]
            for flag,value in [('--package-id','original-package'),('--version','1.2.3'),('--webview','downloadBootstrapper'),('--output',str(root/'original-output'))]:
                self.assertEqual(args[args.index(flag)+1],value)
            self.assertEqual(result['job']['id'],'original-package')
            self.assertEqual(result['job']['version'],'1.2.3')

if __name__ == '__main__':unittest.main()
