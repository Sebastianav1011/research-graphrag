"""Local coordinator telemetry and explicit metric provenance; no remote resource claims."""
import ctypes
import os
import platform
import statistics
import threading
import time


def metric(value=None, status=None, scope=None):
    return {'value':value,'status':status or ('MEASURED' if value is not None else 'NOT_AVAILABLE'),
            'scope':scope}


def resident_bytes():
    if os.name=='nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
                *[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize',
                  'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
                  'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]]
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        api = ctypes.WinDLL('psapi',use_last_error=True).GetProcessMemoryInfo
        api.argtypes = [wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if api(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
            return int(counters.WorkingSetSize)
        return None
    try:
        # Linux resident pages. No peak from process lifetime is mislabeled as run peak.
        with open('/proc/self/statm',encoding='ascii') as stream:
            return int(stream.read().split()[1])*os.sysconf('SC_PAGE_SIZE')
    except (OSError,ValueError,IndexError):
        return None


class Measurement:
    def __enter__(self):
        self.started = time.perf_counter()
        self.cpu = time.process_time()
        self.samples = []
        self.stop = threading.Event()
        self.sample()
        def poll():
            while not self.stop.wait(.05):
                self.sample()
        self.thread = threading.Thread(target=poll,daemon=True)
        self.thread.start()
        return self

    def sample(self):
        value = resident_bytes()
        if value is not None:
            self.samples.append(value)

    def __exit__(self,*args):
        self.stop.set(); self.thread.join(timeout=1)
        self.sample()
        self.result = {'wall_seconds':metric(time.perf_counter()-self.started,scope='LOCAL_ELAPSED_INTERVAL'),
            'cpu_seconds':metric(time.process_time()-self.cpu,scope='PYTHON_COORDINATOR_ONLY'),
            'ram_bytes':metric(self.samples[-1] if self.samples else None,scope='PYTHON_COORDINATOR_RSS'),
            'peak_ram_bytes':metric(max(self.samples) if self.samples else None,scope='SAMPLED_COORDINATOR_RSS_50MS'),
            'remote_cpu':metric(),'remote_ram':metric(),
            'sampling_interval_seconds':.05}


def usage_metrics(call):
    observations = call.get('usage_observations',[])
    # Multiple turn completions might be retries or continuation events. Preserve
    # observations without guessing whether the provider returned cumulative usage.
    usage = observations[0] if len(observations)==1 else {}
    result = {}
    for target,source in (('input_tokens','input_tokens'),('output_tokens','output_tokens'),
                          ('cached_tokens','cached_input_tokens')):
        value = usage.get(source)
        result[target] = metric(value if type(value) is int and value>=0 else None,
                                scope='CLI_REPORTED_CALL')
    i,o = result['input_tokens']['value'],result['output_tokens']['value']
    result['total_tokens'] = metric(i+o if i is not None and o is not None else None,
                                    scope='INPUT_PLUS_OUTPUT_CACHED_IS_SUBSET')
    return result


def interval_union(intervals):
    intervals = sorted((a,b) for a,b in intervals if b>=a)
    total = 0
    start = end = None
    for a,b in intervals:
        if start is None:
            start,end = a,b
        elif a>end:
            total += end-start; start,end=a,b
        else:
            end=max(end,b)
    return total+(end-start if start is not None else 0)


def describe(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {'n':0,'total':None,'mean':None,'median':None,'p90':None,'p95':None,'min':None,'max':None}
    def percentile(p):
        i=(len(values)-1)*p; low=int(i); high=min(low+1,len(values)-1)
        return values[low]+(values[high]-values[low])*(i-low)
    return {'n':len(values),'total':sum(values),'mean':statistics.mean(values),
            'median':statistics.median(values),'p90':percentile(.9),'p95':percentile(.95),
            'min':min(values),'max':max(values)}


def environment():
    return {'os':platform.system(),'os_release':platform.release(),'python':platform.python_version(),
            'logical_cpus':os.cpu_count(),'resources_scope':'LOCAL_PYTHON_COORDINATOR_ONLY',
            'remote_resources_status':'NOT_AVAILABLE','monetary_cost_status':'NOT_AVAILABLE'}
