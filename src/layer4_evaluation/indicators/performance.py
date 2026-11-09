"""Local coordinator telemetry and explicit metric provenance; no remote resource claims."""
from run_paths import file_path as run_file
import ctypes
import os
import platform
import statistics
import threading
import time

# Run reports supplement (and do not replace) the immutable per-call receipts.
import csv
import json
import logging
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from uuid import uuid4
from urllib.parse import unquote
from collections import Counter
import subprocess
import math

API_DURATIONS = dict(total_duration='duracion_total_ollama_segundos',
    load_duration='duracion_carga_ollama_segundos', prompt_eval_duration='duracion_prompt_ollama_segundos',
    eval_duration='duracion_generacion_ollama_segundos')
MODEL_RESOURCE_COLUMNS = ('pico_ram_python_mib','pico_ram_ollama_mib','pico_ram_python_ollama_mib',
    'pico_vram_ollama_mib','pico_vram_python_ollama_mib')
RESOURCE_KEYS = ('ram_python','ram_ollama','ram_combined','vram_ollama','vram_combined')
CPU_MODEL_COLUMNS = ('cpu_python_promedio_porcentaje_un_nucleo','cpu_ollama_promedio_porcentaje_un_nucleo',
    'cpu_python_ollama_promedio_porcentaje_un_nucleo')

_active_run = None
_local = threading.local()
STAGES = ('preparacion', 'embeddings', 'grafo', 'recuperacion', 'inferencia')
PROJECT_COLUMNS = ('id_proyecto', 'tiempo_directo_proyecto_segundos', 'tiempo_inferencia_segundos',
    'llamadas_llm', 'tokens_entrada', 'tokens_salida', 'tokens_totales', 'conteo_tokens',
    'pico_ram_proceso_mib', 'pico_vram_proceso_mib', 'estado') + MODEL_RESOURCE_COLUMNS + tuple(API_DURATIONS.values())
SUMMARY_COLUMNS = ('id_ejecucion', 'estado', 'modelo', 'proyectos_seleccionados', 'proyectos_procesados',
    'proyectos_exitosos', 'tiempo_total_activo_segundos', 'tiempo_preparacion_segundos',
    'tiempo_embeddings_segundos', 'tiempo_construccion_grafo_segundos', 'tiempo_recuperacion_segundos',
    'tiempo_inferencia_llm_segundos', 'tiempo_promedio_directo_proyecto_segundos', 'llamadas_llm',
    'tokens_entrada', 'tokens_salida', 'tokens_totales', 'conteo_tokens',
    'cpu_proceso_promedio_porcentaje_un_nucleo', 'pico_ram_proceso_mib',
    'gpu_dispositivo_promedio_porcentaje', 'pico_vram_dispositivos_mib', 'pico_vram_proceso_mib') + CPU_MODEL_COLUMNS + MODEL_RESOURCE_COLUMNS + tuple(API_DURATIONS.values())


def provider_report(run):
    """Supplement unchanged local telemetry with explicit provider/cost scope."""
    run=Path(run);binding=run_file(run, 'model.binding.json')
    if not binding.exists():return
    llm=json.loads(binding.read_text(encoding='utf-8'))['llm']
    data=dict(provider=llm['provider'],model=llm['model'],local_resource_scope='LOCAL_PIPELINE',
        remote_hardware='NOT_AVAILABLE',remote_response_seconds=0.,calls=0)
    if llm['provider']=='openai' and (run/'api-ledger.sqlite').exists():
        from .openai_provider import Ledger
        data.update(Ledger(run/'api-ledger.sqlite',llm['api']).summary())
        for path in run.rglob('call.json'):
            try:call=json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,OSError):continue
            if call.get('provider')=='openai':data['remote_response_seconds']+=call.get('remote_response_seconds') or 0
    _atomic_json(run/'resultados/performance/provider.json',data)


class ProcessSampler:
    """Observe unique PIDs, including the local Ollama server and its runners.

    psutil is optional. Windows Toolhelp/GetProcessTimes/GetProcessMemoryInfo
    provide the same counters without installing packages or invoking a shell.
    """
    def __init__(self):
        self.previous={};self.started=time.time();self.psutil=None
        self.python_pids=set();self.ollama_pids=set();self.observed_ollama=set()
        try:
            import psutil
            self.psutil=psutil
        except ImportError:pass
        self.backend='psutil' if self.psutil else 'Windows native' if os.name=='nt' else '/proc' if Path('/proc').exists() else 'NOT_AVAILABLE'

    def inventory(self):
        if self.psutil:
            return {r.info['pid']:dict(parent=r.info['ppid'],name=r.info['name'] or '')
                    for r in self.psutil.process_iter(['pid','ppid','name'],ad_value=None)}
        if os.name=='nt':
            from ctypes import wintypes as w
            class Entry(ctypes.Structure):
                _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),
                    ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),
                    ('flags',w.DWORD),('name',w.WCHAR*260)]
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateToolhelp32Snapshot.restype=w.HANDLE
            kernel.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD]
            kernel.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
            kernel.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
            kernel.CloseHandle.argtypes=[w.HANDLE]
            handle=kernel.CreateToolhelp32Snapshot(2,0)
            if handle==w.HANDLE(-1).value:raise OSError('Process inventory unavailable')
            result={};entry=Entry();entry.size=ctypes.sizeof(entry)
            try:
                ok=kernel.Process32FirstW(handle,ctypes.byref(entry))
                while ok:
                    result[entry.pid]=dict(parent=entry.parent,name=entry.name)
                    ok=kernel.Process32NextW(handle,ctypes.byref(entry))
            finally:kernel.CloseHandle(handle)
            return result
        result={}
        for path in Path('/proc').glob('[0-9]*'):
            try:
                stat=(path/'stat').read_text();tail=stat[stat.rindex(')')+2:].split()
                result[int(path.name)]=dict(parent=int(tail[1]),name=stat[stat.index('(')+1:stat.rindex(')')])
            except (OSError,ValueError,IndexError):pass
        return result

    def counters(self,pid):
        if self.psutil:
            process=self.psutil.Process(pid);cpu=process.cpu_times()
            return process.create_time(),cpu.user+cpu.system,process.memory_info().rss
        if os.name=='nt':
            from ctypes import wintypes as w
            class Memory(ctypes.Structure):
                _fields_=[('size',w.DWORD),('faults',w.DWORD)] + [(key,ctypes.c_size_t) for key in
                    ('peak_rss','rss','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.restype=w.HANDLE;kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]
            kernel.CloseHandle.argtypes=[w.HANDLE]
            kernel.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
            memory_api=ctypes.WinDLL('psapi',use_last_error=True).GetProcessMemoryInfo
            memory_api.argtypes=[w.HANDLE,ctypes.POINTER(Memory),w.DWORD]
            handle=kernel.OpenProcess(0x400|0x10,False,pid)
            if not handle:raise OSError('PID not readable')
            created,exited,system,user=(w.FILETIME() for _ in range(4));memory=Memory();memory.size=ctypes.sizeof(memory)
            try:
                if not kernel.GetProcessTimes(handle,*map(ctypes.byref,(created,exited,system,user))):raise OSError('CPU counter unavailable')
                if not memory_api(handle,ctypes.byref(memory),memory.size):raise OSError('RSS counter unavailable')
                seconds=lambda f:((f.dwHighDateTime<<32)|f.dwLowDateTime)/10_000_000
                return seconds(created)-11644473600,seconds(system)+seconds(user),memory.rss
            finally:kernel.CloseHandle(handle)
        path=Path('/proc')/str(pid);stat=(path/'stat').read_text();fields=stat[stat.rindex(')')+2:].split()
        boot=next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))
        hz=os.sysconf('SC_CLK_TCK');rss=int((path/'statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        return boot+int(fields[19])/hz,(int(fields[11])+int(fields[12]))/hz,rss

    def sample(self):
        try:inventory=self.inventory()
        except Exception:return {}
        # A GraphRAG graph worker inherits the main Python PID. Exclude unrelated Python jobs.
        root=os.getpid()
        while (parent:=inventory.get(root,{}).get('parent')) and inventory.get(parent,{}).get('name','').lower().startswith('python'):
            root=parent
        python={root};ollama={pid for pid,r in inventory.items() if r['name'].lower() in
            ('ollama','ollama.exe','ollama_llama_server','ollama_llama_server.exe')}
        for group in (python,ollama):
            while True:
                children={pid for pid,r in inventory.items() if r['parent'] in group and
                    (group is ollama or r['name'].lower().startswith('python'))}
                if children<=group:break
                group.update(children)
        python-=ollama;self.python_pids=python;self.ollama_pids=ollama;self.observed_ollama.update(ollama)
        values={};read={};deltas={}
        for pid in python|ollama:
            try:
                creation,cpu,rss=self.counters(pid);key=(pid,creation)
                prior=self.previous.get(key)
                deltas[pid]=max(0.,cpu-prior) if prior is not None else cpu if creation>=self.started else 0.
                self.previous[key]=cpu;read[pid]=rss
            except Exception:pass
        for group,name in ((python,'python'),(ollama,'ollama'),(python|ollama,'combined')):
            # Empty or partially inaccessible groups are unknown, never invented zero usage.
            if group and group<=read.keys():
                values['ram_'+name]=sum(read[pid] for pid in group)
                values['cpu_'+name+'_delta']=sum(deltas[pid] for pid in group)
        return values


def _command(arguments):
    return subprocess.run(arguments,capture_output=True,text=True,timeout=2,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)


def _number(value):
    try:
        number=float(value.strip())
        return number if math.isfinite(number) and number>=0 else None
    except (ValueError,AttributeError):return None


def _pid(value):
    return unquote(value[5:]) if value.startswith('PROJ_') else value


def _safe(action):
    """An unavailable sensor/report must never change an analytical result."""
    try:
        return action()
    except Exception as exc:
        logging.getLogger(__name__).warning('Informe de rendimiento no disponible: %s', type(exc).__name__)


class Resources:
    """CPU/RSS each second; NVML or nvidia-smi device metrics every two seconds."""
    def __init__(self):
        self.process = self.nv = None
        self.handles = []
        self.processes=ProcessSampler();self.lock=threading.RLock();self.gpu_last=-math.inf
        self.smi=False
        self.info = environment() | dict(resources_scope='LOCAL_GRAPHRAG_AND_OLLAMA_PROCESSES',processor=platform.processor(), ram_total_bytes=None,
            gpu=[], ram_sensor='native_RSS', gpu_sensor='NOT_AVAILABLE', sample_seconds=1,
            cpu_scope='Legacy column: instrumented Python only. Additional columns: Python tree, Ollama server/runners and their distinct PID union; 100 percent = one core',
            ram_scope='Legacy column: individual Python RSS. Added group peaks: simultaneous RSS sums over distinct PIDs, never sums of independent peaks; shared OS pages may appear in multiple RSS values',
            gpu_scope='utilization: maximum across devices; VRAM device: sum across devices; other applications included',
            vram_process_scope='Legacy: own Python PID. Added: Ollama PIDs and distinct Python/Ollama PID union; blanks for unsupported per-process GPU accounting',
            process_sensor=self.processes.backend,gpu_sample_seconds=2,
            ollama_scope='Whole local Ollama service and its runners during this run; shared with any other concurrent Ollama clients, not exclusive per-request attribution')
        try:
            import psutil
            self.process = psutil.Process()
            self.info.update(ram_total_bytes=psutil.virtual_memory().total, ram_sensor='psutil.Process.memory_info.rss')
        except Exception:
            if os.name == 'nt':
                class Memory(ctypes.Structure):
                    _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)] + [
                        (n,ctypes.c_ulonglong) for n in ('total','available','page','freepage','virtual','freevirtual','extended')]
                memory=Memory();memory.length=ctypes.sizeof(memory)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                    self.info['ram_total_bytes']=memory.total
            else:
                try:self.info['ram_total_bytes']=os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
                except (ValueError,OSError,AttributeError):pass
        try:
            import pynvml
            pynvml.nvmlInit();self.nv=pynvml
            self.handles=[pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
            self.info['gpu']=[str(pynvml.nvmlDeviceGetName(h)) for h in self.handles]
            self.info['gpu_sensor']='NVML' if self.handles else 'NOT_AVAILABLE'
        except Exception:
            self.handles=[]
        try:
            result=_command(['nvidia-smi','--query-gpu=name','--format=csv,noheader'])
            if result.returncode==0:
                self.smi=True
                if not self.info['gpu']:self.info['gpu']=result.stdout.strip().splitlines()
                if not self.handles:self.info['gpu_sensor']='nvidia-smi (device totals; per-process if supported)'
        except (OSError,subprocess.SubprocessError):pass

    def sample(self):
        with self.lock:return self._sample()

    def _sample(self):
        values={}
        try:values['ram']=self.process.memory_info().rss if self.process else resident_bytes()
        except Exception:values['ram']=_safe(resident_bytes)
        values.update(self.processes.sample())
        self.info['ollama_pids_observed']=sorted(self.processes.observed_ollama)
        self.info['python_pids_last_sample']=sorted(self.processes.python_pids)
        if time.perf_counter()-self.gpu_last<2:return values
        self.gpu_last=time.perf_counter();gpu={}
        if self.handles:
            for key, operation, aggregate in (
                ('gpu',lambda h:self.nv.nvmlDeviceGetUtilizationRates(h).gpu,max),
                ('device_vram',lambda h:self.nv.nvmlDeviceGetMemoryInfo(h).used,sum),
                ('vram',lambda h:self.process_vram(h,{os.getpid()}),sum),
                ('vram_ollama',lambda h:self.process_vram(h,self.processes.ollama_pids),sum),
                ('vram_combined',lambda h:self.process_vram(h,self.processes.python_pids|self.processes.ollama_pids),sum)):
                try:gpu[key]=aggregate(operation(h) for h in self.handles)
                except Exception:gpu[key]=None
        if self.smi and any(gpu.get(k) is None for k in ('gpu','device_vram','vram','vram_ollama','vram_combined')):
            try:
                device=_command(['nvidia-smi','--query-gpu=utilization.gpu,memory.used','--format=csv,noheader,nounits'])
                rows=list(csv.reader(device.stdout.splitlines())) if device.returncode==0 else []
                for index,key,aggregate,scale in ((0,'gpu',max,1),(1,'device_vram',sum,1024**2)):
                    numbers=[_number(row[index]) for row in rows if len(row)==2]
                    if gpu.get(key) is None and numbers and all(n is not None for n in numbers):gpu[key]=aggregate(numbers)*scale
                process=_command(['nvidia-smi','--query-compute-apps=pid,used_gpu_memory','--format=csv,noheader,nounits'])
                entries=list(csv.reader(process.stdout.splitlines())) if process.returncode==0 else None
                if entries is not None:
                    for key,pids in (('vram',{os.getpid()}),('vram_ollama',self.processes.ollama_pids),
                                     ('vram_combined',self.processes.python_pids|self.processes.ollama_pids)):
                        numbers=[_number(row[1]) for row in entries if len(row)==2 and row[0].strip().isdigit() and int(row[0]) in pids]
                        if gpu.get(key) is None and pids and all(n is not None for n in numbers):gpu[key]=sum(numbers)*1024**2
            except (OSError,subprocess.SubprocessError):pass
        if self.handles or self.smi:
            for key in ('vram','vram_ollama','vram_combined'):gpu.setdefault(key,None)
        return values|gpu

    def process_vram(self, handle, pids):
        if not pids:raise ValueError('No measured PIDs')
        rows=self.nv.nvmlDeviceGetComputeRunningProcesses(handle)
        vals=[p.usedGpuMemory for p in rows if p.pid in pids]
        if any(v is None or v < 0 or v >= (1<<63) for v in vals):
            raise ValueError('NVML_VALUE_NOT_AVAILABLE')
        return sum(vals)

    def close(self):
        if self.nv:
            try:self.nv.nvmlShutdown()
            except Exception:pass


def _peak(a,b):
    vals=[v for v in (a,b) if v is not None]
    return max(vals) if vals else None


def _project():
    return dict(direct=None, inference=0., calls=0, input=0, output=0, missing_input=0, missing_output=0,
                ram=None, vram=None, resources_ambiguous=False, state='PENDIENTE',model_usage=_model_usage())


def _model_usage():
    return dict(resources={key:None for key in RESOURCE_KEYS},missing_vram=[],
        cpu_seconds={key:0. for key in ('python','ollama','combined')},cpu_samples={key:0 for key in ('python','ollama','combined')},
        api_ns={key:0 for key in API_DURATIONS},api_missing={key:0 for key in API_DURATIONS})


def _resources_update(model,values):
    for key in RESOURCE_KEYS:model['resources'][key]=_peak(model['resources'][key],values.get(key))
    for key in ('vram','vram_ollama','vram_combined'):
        if key in values and values[key] is None and key not in model['missing_vram']:model['missing_vram'].append(key)
    for key in model['cpu_seconds']:
        if values.get('cpu_'+key+'_delta') is not None:
            model['cpu_seconds'][key]+=values['cpu_'+key+'_delta'];model['cpu_samples'][key]+=1


class RunMeasurement:
    def __init__(self,run, included_in_parent=False):
        self.run=Path(run);self.folder=self.run/'resultados/performance'
        self.id=uuid4().hex;self.mutex=threading.RLock();self.seen=set()
        self.data=dict(session=self.id, included_in_parent=included_in_parent, status='EN_CURSO', wall=0., cpu=0., model='', projects={},
            stages={}, ram=None,vram=None,device_vram=None,gpu_sum=0.,gpu_samples=0,model_usage=_model_usage())
        self.stage_active=Counter();self.stage_last=time.perf_counter()
        self.active_projects=Counter();self.last_flush=time.perf_counter()

    def __enter__(self):
        self.started=time.perf_counter();self.cpu=time.process_time()
        self.sensor=Resources();self.stop=threading.Event();self.sample()
        def poll():
            while not self.stop.wait(1):self.sample()
        self.thread=threading.Thread(target=poll,daemon=True);self.thread.start()
        return self

    def sample(self):
        values=self.sensor.sample()
        with self.mutex:
            _resources_update(self.data['model_usage'],values)
            for target,key in (('ram','ram'),('vram','vram'),('device_vram','device_vram')):
                self.data[target]=_peak(self.data[target],values.get(key))
            if values.get('gpu') is not None:
                self.data['gpu_sum']+=values['gpu'];self.data['gpu_samples']+=1
            # Shared process peaks cannot be assigned exclusively to concurrent projects.
            if len(self.active_projects)==1:
                pid=next(iter(self.active_projects));row=self.data['projects'].setdefault(pid,_project())
                if not row['resources_ambiguous']:
                    for key in ('ram','vram'):row[key]=_peak(row[key],values.get(key))
                    _resources_update(row['model_usage'],values)

    def stage_change(self,stage=None,delta=0):
        with self.mutex:
            now=time.perf_counter()
            if self.stage_active:
                chosen=max(self.stage_active,key=lambda s:STAGES.index(s))
                self.data['stages'][chosen]+=now-self.stage_last
            self.stage_last=now
            if stage:
                self.data['stages'].setdefault(stage,0.)
                self.stage_active[stage]+=delta
                if not self.stage_active[stage]:del self.stage_active[stage]

    def project_state(self,pid,state):
        with self.mutex:self.data['projects'].setdefault(_pid(pid),_project())['state']=state

    def call(self,call,path):
        key=str(Path(path).resolve())
        with self.mutex:
            if key in self.seen:return
            self.seen.add(key)
            row=self.data['projects'].setdefault(_pid(call['project_id']),_project());row['calls']+=1
            self.data['model']=call.get('requested_model','')
            usage=usage_metrics(call)
            native=call.get('ollama_durations_ns',{})
            for key in API_DURATIONS:
                value=native.get(key)
                if type(value) is int and value>=0:row['model_usage']['api_ns'][key]+=value
                else:row['model_usage']['api_missing'][key]+=1
            for target in ('input','output'):
                value=usage[target+'_tokens']['value']
                if value is None:row['missing_'+target]+=1
                else:row[target]+=value
            elapsed=call.get('performance',{}).get('wall_seconds',{}).get('value')
            if elapsed is None:row['inference']=None
            elif row['inference'] is not None:row['inference']+=elapsed
            row['state']='CON_ERROR' if call.get('technical_error') else 'EN_CURSO'
        if call.get('technical_error') or time.perf_counter()-self.last_flush>=15:self.flush()

    def sync(self,status):
        """Use authoritative selection/job states; never equate HTTP success with project success."""
        self.data['status']=status
        execution=run_file(self.run, 'execution.json');state=run_file(self.run, 'run.json')
        request=json.loads(execution.read_text(encoding='utf-8')) if execution.exists() else {}
        saved=json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}
        ids=request.get('project_ids') or saved.get('configuration',{}).get('project_selection',{}).get('project_ids',[])
        self.data['model']=self.data['model'] or request.get('llm',saved.get('configuration',{}).get('llm',{})).get('model','')
        for pid in ids:
            row=self.data['projects'].setdefault(pid,_project())
            if status=='VALIDATED_SELECTION':row['state']='VALIDADO_SIN_INFERENCIA'
            elif status=='COMPLETE' and request.get('through') in ('evaluation','export'):row['state']='EXITOSO'
            elif status=='COMPLETE' and row['state']=='PENDIENTE':row['state']='PREPARADO'
        if status in ('FALLIDO','INTERRUMPIDO'):
            for row in self.data['projects'].values():
                if row['state']=='PENDIENTE':row['state']='NO_PROCESADO_POR_FALLO' if status=='FALLIDO' else 'INTERRUMPIDO'
        for pid in request.get('blocked_projects',{}):self.project_state(pid,'BLOQUEADO')
        queue=self.run/'autonomous/main/queue.sqlite'
        if queue.exists():
            import sqlite3
            db=sqlite3.connect(queue.as_uri()+'?mode=ro',uri=True)
            try:
                for pid,total,passed,blocked in db.execute("SELECT pid,COUNT(*),SUM(status='PASS'),SUM(status IN ('BLOCKED','UNCERTAIN')) FROM jobs GROUP BY pid"):
                    self.project_state(pid,'EXITOSO' if total==passed else 'BLOQUEADO' if blocked else 'PENDIENTE')
            finally:db.close()

    def flush(self):
        if not self.run.exists():return
        with self.mutex:
            self.data['wall']=time.perf_counter()-self.started
            self.data['cpu']=time.process_time()-self.cpu
            # O(1) exclusive stage accounting, even during long/parallel runs.
            self.stage_change()
            self.data['updated']=time.time_ns()
            sessions=self.folder/'.sesiones';sessions.mkdir(parents=True,exist_ok=True)
            _atomic_json(sessions/(self.id+'.json'),self.data)
            _atomic_json(self.folder/'metadatos.json',self.sensor.info | dict(
                model=self.data['model'], schema_version=1, missing_values='empty CSV cell, never estimated',
                csv_separator=';', csv_decimal=',', csv_encoding='UTF-8 with BOM',
                model_status='CONFIGURED_WITHOUT_CALLS' if not any(p['calls'] for p in self.data['projects'].values()) else 'PROVIDER_REPORTED',
                tokens='provider counters only; blank total if any call lacks usage',
                shared_calls='One physical call receipt counted once per project. Queue usage belongs 100% to owner indicator; other batch members add no tokens/calls. Membership is recorded in batch_receipts and result shared_call.',
                ollama_durations='Unmodified API nanoseconds in call receipts; CSV seconds = ns / 1e9; API total includes load/prompt/generation, not extra pipeline stages; blanks when missing',
                timing='perf_counter active invocations including I/O and interactive waits; excludes time between invocations; exclusive stages (inference > retrieval > graph > embeddings > preparation); project direct times include inference, exclude shared stages',
                project_resources='observed process RSS/VRAM during exclusive project intervals, not incremental allocations; blank when concurrent projects overlap',
                persistence='flush each 15 seconds, on call error and session exit; abrupt termination can lose last unflushed interval'))
            export_run(self.folder)
            self.last_flush=time.perf_counter()

    def finish(self,status):
        self.stop.set();self.thread.join(timeout=2);self.sample()
        self.data['status']=status
        try:_safe(lambda:self.sync(status));self.flush()
        finally:
            _safe(lambda:provider_report(self.run))
            self.sensor.close()


def _atomic_json(path,value):
    temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)


def _csv(path,columns,rows):
    temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    with temp.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,delimiter=';');writer.writeheader()
        for row in rows:
            writer.writerow({k:format(v,'.6f').replace('.',',') if isinstance(v,float) else
                "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for k,v in row.items()})
    os.replace(temp,path)


def export_run(folder):
    sessions=[json.loads(p.read_text(encoding='utf-8')) for p in (folder/'.sesiones').glob('*.json')]
    sessions.sort(key=lambda s:s.get('updated',0))
    projects={}
    for session in sessions:
        for pid,current in session['projects'].items():
            row=projects.setdefault(pid,_project())
            for key in ('direct','inference'):
                if current[key] is not None:row[key]=(row[key] or 0)+current[key]
                elif key=='inference' and current['calls']:row['unknown_inference']=True
            for key in ('calls','input','output','missing_input','missing_output'):row[key]+=current[key]
            observed=current.get('model_usage')
            if observed:
                for key in RESOURCE_KEYS:
                    row['model_usage']['resources'][key]=_peak(row['model_usage']['resources'][key],observed['resources'].get(key))
                row['model_usage']['missing_vram']=sorted(set(row['model_usage']['missing_vram'])|set(observed['missing_vram']))
                for key in API_DURATIONS:
                    row['model_usage']['api_ns'][key]+=observed['api_ns'][key]
                    row['model_usage']['api_missing'][key]+=observed['api_missing'][key]
            else:
                for key in API_DURATIONS:row['model_usage']['api_missing'][key]+=current['calls']
            for key in ('ram','vram'):row[key]=_peak(row[key],current[key])
            row['resources_ambiguous'] |= current['resources_ambiguous']
            if current['state'] not in ('PENDIENTE','PREPARADO') or row['state']!='EXITOSO':
                row['state']=current['state']
    def tokens(row):
        i=None if row['missing_input'] else row['input'];o=None if row['missing_output'] else row['output']
        return dict(tokens_entrada=i,tokens_salida=o,tokens_totales=i+o if i is not None and o is not None else None,
                    conteo_tokens='NO_DISPONIBLE' if i is None or o is None else 'EXACTO_PROVEEDOR' if row['calls'] else 'SIN_LLAMADAS')
    mib=lambda value:value/(1024**2) if value is not None else None
    def model_values(row):
        observed=row['model_usage'];result={}
        for key,column in zip(RESOURCE_KEYS,MODEL_RESOURCE_COLUMNS):
            result[column]=None if row.get('resources_ambiguous') or key in observed['missing_vram'] else mib(observed['resources'][key])
        for key,column in API_DURATIONS.items():
            result[column]=observed['api_ns'][key]/1e9 if row['calls'] and not observed['api_missing'][key] else None
        return result
    rows=[dict(id_proyecto=pid,tiempo_directo_proyecto_segundos=r['direct'],
        tiempo_inferencia_segundos=None if r.get('unknown_inference') else r['inference'],
        llamadas_llm=r['calls'],**tokens(r),pico_ram_proceso_mib=None if r['resources_ambiguous'] else mib(r['ram']),
        pico_vram_proceso_mib=None if r['resources_ambiguous'] or 'vram' in r['model_usage']['missing_vram'] else mib(r['vram']),
        estado=r['state'],**model_values(r)) for pid,r in sorted(projects.items())]
    total={key:sum(r[key] for r in projects.values()) for key in ('calls','input','output','missing_input','missing_output')}
    wall=sum(s['wall'] for s in sessions if not s.get('included_in_parent'));direct=[r['direct'] for r in projects.values() if r['direct'] is not None]
    samples=sum(s['gpu_samples'] for s in sessions if not s.get('included_in_parent'))
    peak=lambda key:max((s[key] for s in sessions if s[key] is not None),default=None)
    summary=dict(id_ejecucion=folder.parents[1].name,estado=sessions[-1]['status'],
        modelo=' | '.join(sorted({s['model'] for s in sessions if s['model']})),proyectos_seleccionados=len(rows),
        proyectos_procesados=sum(r['calls']>0 or r['direct'] is not None for r in projects.values()),
        proyectos_exitosos=sum(r['state']=='EXITOSO' for r in projects.values()),tiempo_total_activo_segundos=wall,
        tiempo_promedio_directo_proyecto_segundos=sum(direct)/len(direct) if direct else None,
        llamadas_llm=total['calls'],**tokens(total),cpu_proceso_promedio_porcentaje_un_nucleo=100*sum(s['cpu'] for s in sessions)/wall if wall else None,
        pico_ram_proceso_mib=mib(peak('ram')),gpu_dispositivo_promedio_porcentaje=sum(s['gpu_sum'] for s in sessions if not s.get('included_in_parent'))/samples if samples else None,
        pico_vram_dispositivos_mib=mib(peak('device_vram')),pico_vram_proceso_mib=mib(peak('vram')))
    resources=_model_usage()
    for session in sessions:
        observed=session.get('model_usage')
        if not observed:continue
        for key in RESOURCE_KEYS:resources['resources'][key]=_peak(resources['resources'][key],observed['resources'][key])
        resources['missing_vram']=sorted(set(resources['missing_vram'])|set(observed['missing_vram']))
        if not session.get('included_in_parent'):
            for key in resources['cpu_seconds']:
                resources['cpu_seconds'][key]+=observed['cpu_seconds'][key]
                resources['cpu_samples'][key]+=observed['cpu_samples'][key]
    for row in projects.values():
        for key in API_DURATIONS:
            resources['api_ns'][key]+=row['model_usage']['api_ns'][key]
            resources['api_missing'][key]+=row['model_usage']['api_missing'][key]
    summary.update(model_values(dict(model_usage=resources,calls=total['calls'])))
    legacy=any('model_usage' not in s for s in sessions if not s.get('included_in_parent'))
    for key,column in zip(('python','ollama','combined'),CPU_MODEL_COLUMNS):
        summary[column]=100*resources['cpu_seconds'][key]/wall if wall and resources['cpu_samples'][key] and not legacy else None
    if 'vram' in resources['missing_vram']:summary['pico_vram_proceso_mib']=None
    for stage,column in zip(STAGES,('tiempo_preparacion_segundos','tiempo_embeddings_segundos','tiempo_construccion_grafo_segundos',
                                  'tiempo_recuperacion_segundos','tiempo_inferencia_llm_segundos')):
        measured=[s['stages'][stage] for s in sessions if stage in s['stages']]
        summary[column]=sum(measured) if measured else None
    _csv(folder/'por_proyecto.csv',PROJECT_COLUMNS,rows);_csv(folder/'resumen.csv',SUMMARY_COLUMNS,[summary])


@contextmanager
def span(stage=None,project=None):
    run=_active_run
    if run is None:
        yield
        return
    pid=_pid(project) if project is not None else None
    previous=getattr(_local,'project',None)
    if pid==previous:pid=None
    start=time.perf_counter()
    shared=stage in ('preparacion','embeddings','grafo') and previous is not None
    shared_before=getattr(_local,'shared_elapsed',0.)
    if shared:
        if not getattr(_local,'shared_depth',0):_local.shared_started=start
        _local.shared_depth=getattr(_local,'shared_depth',0)+1
    if stage:_safe(lambda:run.stage_change(stage,1))
    if pid:
        _local.project=pid
        with run.mutex:
            run.active_projects[pid]+=1
            if len(run.active_projects)>1:
                for active_pid in run.active_projects:
                    run.data['projects'].setdefault(active_pid,_project())['resources_ambiguous']=True
        _safe(run.sample)
    try:yield
    finally:
        end=time.perf_counter()
        if stage:_safe(lambda:run.stage_change(stage,-1))
        if shared:
            _local.shared_depth-=1
            if not _local.shared_depth:
                _local.shared_elapsed=getattr(_local,'shared_elapsed',0.)+end-_local.shared_started
        if pid:
            _safe(run.sample)
            with run.mutex:
                row=run.data['projects'].setdefault(pid,_project())
                row['direct']=(row['direct'] or 0)+max(0.,end-start-(getattr(_local,'shared_elapsed',0.)-shared_before))
                run.active_projects[pid]-=1
                if not run.active_projects[pid]:del run.active_projects[pid]
            _local.project=previous


def timed(stage):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            with span(stage):return fn(*args,**kwargs)
        return wrapped
    return decorate


def record_call(call,path):
    if _active_run:_safe(lambda:_active_run.call(call,path))


def observe_projects(ids,model=''):
    if _active_run:
        with _active_run.mutex:
            for pid in ids or []:_active_run.data['projects'].setdefault(pid,_project())
            _active_run.data['model']=model or _active_run.data['model']


def project_states(verified):
    if _active_run:
        for row in verified.get('projects',[]):
            _safe(lambda row=row:_active_run.project_state(row['project_id'],'EXITOSO' if row['complete'] else 'PENDIENTE'))


@contextmanager
def run_session(run, included_in_parent=False):
    global _active_run
    if _active_run is not None:
        yield _active_run
        return
    measured=_safe(lambda:RunMeasurement(run,included_in_parent).__enter__())
    if measured is None:
        yield None
        return
    _active_run=measured
    status='FALLIDO'
    try:
        yield measured
        status=measured.data['status'] if measured.data['status']!='EN_CURSO' else 'COMPLETE'
    except KeyboardInterrupt:
        status='INTERRUMPIDO';raise
    finally:
        _safe(lambda:measured.finish(status));_active_run=None


def measured_pipeline(fn):
    @wraps(fn)
    def wrapped(root,**kwargs):
        # The native ETL creates the run directory; monitoring must not pre-create it.
        from scripts.pipeline_coordinator import configuration,find_run
        from datetime import datetime,timezone
        _,_,runs=configuration(Path(root).resolve(),kwargs.get('config_path','config/pipeline_manual.json'))
        name=kwargs.get('run_id') or 'run_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        kwargs['run_id']=name;run=find_run(Path(root).resolve(),runs,name)
        with run_session(run) as measurement:
            result=fn(root,**kwargs)
            if measurement:measurement.data['status']=result.get('status','COMPLETE')
        if (Path(run)/'resultados/indicadores.csv').exists():
            from run_storage import archive_export
            archive_export(root,run,result)
        return result
    return wrapped


def measured_run(fn):
    @wraps(fn)
    def wrapped(root,run,*args,**kwargs):
        with run_session(run) as measurement:
            result=fn(root,run,*args,**kwargs)
            if measurement and isinstance(result,dict):measurement.data['status']=result.get('status','COMPLETE')
        if isinstance(result,dict) and (Path(run)/'resultados/indicadores.csv').exists():
            from run_storage import archive_export
            archive_export(root,run,result)
        return result
    return wrapped


def measured_project(fn):
    @wraps(fn)
    def wrapped(self,project,*args,**kwargs):
        with span(project=project['project_id']):
            try:return fn(self,project,*args,**kwargs)
            except BaseException:
                if _active_run:_safe(lambda:_active_run.project_state(project['project_id'],'CON_ERROR'))
                raise
    return wrapped


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
