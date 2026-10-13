"""Reproducible isolated HTTPS workload and sampled host-process resources."""
import ctypes,json,math,os,queue,statistics,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from native_host_fixture import Hosted,BINARY

def memory(pid):
    if os.name=='nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),*[(k,ctypes.c_size_t) for k in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage']]]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD];psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
        h=kernel.OpenProcess(0x410,False,pid)
        if not h:raise ctypes.WinError(ctypes.get_last_error())
        try:
            c=Counters();c.cb=ctypes.sizeof(c)
            if not psapi.GetProcessMemoryInfo(h,ctypes.byref(c),c.cb):raise ctypes.WinError(ctypes.get_last_error())
            return {'resident_bytes':c.WorkingSetSize,'private_bytes':c.PrivateUsage,'native_peak_resident_bytes':c.PeakWorkingSetSize}
        finally:kernel.CloseHandle(h)
    fields={k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in Path('/proc',str(pid),'status').read_text().splitlines() if ':' in line) if k in {'VmRSS','VmHWM'}}
    return {'resident_bytes':fields['VmRSS'],'private_bytes':None,'native_peak_resident_bytes':fields.get('VmHWM')}

def process_id(process,root):
    if os.name=='nt':return process.pid
    # Some auxiliary runtimes expose namespace PIDs while mounting host procfs.
    # Resolve only the exact command of this owned temporary host, never a
    # coincidental numeric PID in a different namespace.
    expected=[str(a) for a in process.args]
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:args=[a.decode('utf-8') for a in path.read_bytes().split(b'\0') if a]
        except (OSError,UnicodeError):continue
        if args==expected:return int(path.parent.name)
    raise RuntimeError('OWNED_HOST_PROCESS_NOT_FOUND')

def summary(samples):
    v=sorted(samples);return {'samples_ms':samples,'median_ms':statistics.median(v),'p95_ms':v[max(0,math.ceil(len(v)*.95)-1)],'max_ms':max(v)}

def compare(*,repetitions=30,orders=200):
    results={}
    for backend in ['python_rust_worker','rust_direct']:
        host=Hosted();process=None
        seed=host.client()
        from quote_core import QuoteSnapshot,NormalLine,DraftDetails
        from quote_service.journal import MemoryJournal
        for i in range(orders):seed.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','4'),)),DraftDetails('固定客户',f'{i:05d}','微信'),MemoryJournal())
        try:
            if backend=='python_rust_worker':
                host.stop();config=json.loads((host.host_root/'private/service.json').read_bytes());config['service_backend']='python';(host.host_root/'private/service.json').write_text(json.dumps(config),encoding='utf-8')
                (host.host_root/'private/p06-isolated-check.json').write_text(json.dumps({'schema':'777-isolated-check-v1','production':False}),encoding='utf-8')
                process=subprocess.Popen([sys.executable,str(ROOT/'tools/p06_reference_host.py'),'--root',str(host.host_root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                ready=queue.Queue();threading.Thread(target=lambda:ready.put(process.stdout.readline()),daemon=True).start();line=ready.get(timeout=15)
                if not line or json.loads(line).get('status')!='ready':raise RuntimeError('REFERENCE_HOST_NOT_READY')
            else:process=host.process
            api=host.client();snapshot={'price_version_id':'fixture-v1','lines':[{'line_kind':'normal','product_id':'单件','q':'4'},{'line_kind':'discount','percent':'90%'}]}
            for _ in range(5):
                result=api.request('POST','/v1/calculate',{'snapshot':snapshot});assert result['totals']=={'income_cents':'3600'}
            for _ in range(3):assert api.request('GET','/v1/orders?limit=20')['total']==orders
            observed_pid=process_id(process,host.host_root)
            values=[];stop=threading.Event();errors=[]
            def sample():
                while not stop.is_set():
                    try:values.append(memory(observed_pid))
                    except Exception as e:errors.append(type(e).__name__);break
                    stop.wait(.01)
            thread=threading.Thread(target=sample,daemon=True);thread.start();calculate_ms=[];listing_ms=[]
            try:
                for _ in range(repetitions):
                    start=time.perf_counter();value=api.request('POST','/v1/calculate',{'snapshot':snapshot});calculate_ms.append((time.perf_counter()-start)*1000);assert value['totals']=={'income_cents':'3600'}
                    start=time.perf_counter();value=api.request('GET','/v1/orders?limit=20');listing_ms.append((time.perf_counter()-start)*1000);assert value['total']==orders and value['totals']=={'income_cents':str(orders*4000)}
            finally:stop.set();thread.join(5)
            if errors or not values:raise RuntimeError('PROCESS_RESOURCE_SAMPLE_FAILED: '+','.join(errors))
            results[backend]={'calculation':summary(calculate_ms),'listing':summary(listing_ms),'host_process_memory':{'samples':len(values),'sample_interval_seconds':.01,'peak_sampled_resident_bytes':max(v['resident_bytes'] for v in values),'peak_sampled_private_bytes':None if os.name!='nt' else max(v['private_bytes'] for v in values),'native_peak_resident_bytes':max(v['native_peak_resident_bytes'] for v in values)},'request_results_equal':True}
        finally:
            if backend=='python_rust_worker' and process:
                if process.poll() is None:process.stdin.write(b'\n');process.stdin.flush()
                _,err=process.communicate(timeout=50)
                if process.returncode:raise RuntimeError('REFERENCE_HOST_STOP_FAILED')
            host.close()
    return {'status':'measured','baseline':'retained Python HTTPS/Auth/queue with Rust financial and Excel worker (P06-03 architecture); current compatible code','candidate':'standalone Rust HTTPS/Auth/query/queue with in-process core/ledger/Excel','workload':{'repetitions_per_endpoint':repetitions,'warmup_calculations':5,'prices':'sale10/cost4/single; q4 and 90% discount','connection':'old pinned-certificate Python Client opens a fresh HTTPS connection per request','list_limit':20,'orders':orders},'measurements':results,'binary_bytes':{'rust_host':BINARY.stat().st_size,'python_interpreter':Path(sys.executable).stat().st_size},'scope':'Host-process memory only; short-lived baseline Rust-worker processes and clients are excluded. Sampled peaks are not total application memory. Binary bytes are not installer/runtime dependency size. No real share/E paths or installed service.','product_platform':'Windows' if os.name=='nt' else 'auxiliary_only','sandboxes_cleaned':True}
