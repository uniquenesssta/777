"""Owned package jobs, resumable issuance and cancellation; no business connection input."""
import json, os, re, subprocess, threading, uuid
from pathlib import Path
import p07_diagnostics as diagnostics

class PackagingMixin:
    def package_status(self):
        # Packaging never reads the currently selected business source.
        with self.job_lock:job=json.loads(json.dumps(self.job))
        return dict(preferences=self.preferences,job=job,issuer=self.signer.status())

    def package(self, delivery, permissions, retry=False):
        from p07_developer import local, package_preferences, replace_json
        if os.name != 'nt':raise RuntimeError('WINDOWS_PACKAGING_REQUIRED')
        if delivery not in ['manager', 'sales']:raise RuntimeError('DELIVERY_REQUIRED')
        with self.job_lock:
            if (getattr(self,'worker',None) and self.worker.is_alive()) or (self.job and self.job['state'] in ['running', 'cancelling']):raise RuntimeError('DEVELOPER_BUILD_BUSY')
            preferences = ({**self.preferences, **{k:self.job[k] for k in ['version','runtime']}} if retry and self.job else self.preferences)
            output = package_preferences(preferences)
            output.mkdir(parents=True, exist_ok=True)
            local(output, directory=True)
            if retry:
                if not self.job or self.job['state']!='failed':raise RuntimeError('PACKAGE_RETRY_UNAVAILABLE')
                if self.job.get('signing') != 'local':raise RuntimeError('PACKAGE_LEGACY_REBUILD_REQUIRED')
                if self.job['delivery']!=delivery or self.job.get('permissions')!=permissions:raise RuntimeError('PACKAGE_RESUME_CONFLICT')
                key=self.job['id']
            else:
                key=str(uuid.uuid4())
            destination = output / f'{delivery}-{preferences["version"]}-{key[:8]}'
            if retry:destination=Path(self.job['output'])
            issuer=self.signer.status()
            if not issuer.get('ready'):raise RuntimeError('LOCAL_SIGNER_UNAVAILABLE')
            if not retry and self.job and self.job['state']=='failed' and self.job.get('signing') != 'local':self.close_queue.enqueue(self.job['id'])
            candidate=self.dev.DEV/'local-issuance'/(key+'.bin')
            candidate.parent.mkdir(exist_ok=True)
            self.job = dict(id=key, signing='local', state='running', delivery=delivery, permissions=permissions, version=preferences['version'], runtime=preferences['runtime'], output=str(destination), lines=[], error=None, bytes=None)
            replace_json(self.dev.DEV/'automatic-job.json',self.job)
            self.cancelled.clear()
            args = [os.environ.get('QUOTE777_NODE') or 'node', str(self.dev.ROOT / 'desktop/tools/package.mjs'), '--delivery', delivery, '--issuer-state', str(self.signer.state), '--candidate', str(candidate), '--package-id', key, '--output', str(destination), '--version', preferences['version'], '--webview', preferences['runtime'], '--permissions', json.dumps(permissions, separators=(',', ':'))]
            self.worker = threading.Thread(target=self.build_package, args=(args, candidate, destination), daemon=False)
            self.worker.start()
        return self.package_status()

    def build_package(self, args, candidate, destination):
        from p07_developer import local, replace_json
        try:
            from p07_owned_job import OwnedJob
            with self.job_lock:
                if self.cancelled.is_set():
                    self.job.update(state='cancelled', error=None)
                    return
                self.build_owner = OwnedJob()
                self.build = subprocess.Popen(args, cwd=self.dev.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                                              env=dict(os.environ, QUOTE777_PACKAGE_CONTROL_STDIN='1',QUOTE777_PACKAGE_ID=self.job['id']))
                process = self.build
                # Node waits on this private pipe until the job owns all future descendants.
                self.build_owner.assign(process)
                process.stdin.write(b'start\n'); process.stdin.flush(); process.stdin.close()
            for line in iter(process.stdout.readline, b''):
                with self.job_lock:
                    self.job['lines'] = (self.job['lines'] + [line.decode('utf-8', 'replace').rstrip()[-2000:]])[-80:]
            code = process.wait()
            if self.cancelled.is_set():state, error = 'cancelled', None
            elif code:state, error = 'failed', next((line for line in reversed(self.job['lines']) if re.fullmatch(r'[A-Z][A-Z0-9_]{4,100}',line)), 'TAURI_BUILD_FAILED')
            else:
                manifest = json.loads((destination / 'release.json').read_text(encoding='utf-8'))
                if manifest['delivery'] != self.job['delivery']:raise RuntimeError('COMPILED_PACKAGE_MISMATCH')
                state, error = 'succeeded', None
                with self.job_lock:
                    self.job['bytes'] = sum(p.stat().st_size for p in destination.iterdir() if p.is_file())
                    self.job['source_commit'] = manifest['source_commit']
            diagnostics.event('package.finish', package_id=self.job['id'], state=state, error=error, returncode=code)
            with self.job_lock:self.job.update(state=state, error=error)
        except Exception as error:
            diagnostics.failure("package", error)
            with self.job_lock:self.job.update(state='cancelled' if self.cancelled.is_set() else 'failed', error='DEVELOPER_BUILD_FAILED')
        finally:
            with self.job_lock:
                if self.build_owner:self.build_owner.close(); self.build_owner = None
                process = self.build
                self.build = None
            if process and process.poll() is None:process.kill(); process.wait(timeout=15)
            if self.cancelled.is_set() and candidate.exists() and self.job.get('signing') != 'local':
                self.close_queue.enqueue(self.job['id'])
            replace_json(self.dev.DEV/'automatic-job.json',self.job)

    def cancel(self):
        with self.job_lock:
            if not self.job or self.job['state'] not in ['running', 'cancelling']:return
            self.cancelled.set(); self.job['state'] = 'cancelling'
            from p07_developer import replace_json
            replace_json(self.dev.DEV/'automatic-job.json',self.job)
            if self.build_owner:self.build_owner.close(); self.build_owner = None

