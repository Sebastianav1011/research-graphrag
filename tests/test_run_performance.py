"""Small real-clock/resource observations with mocked transport; never an LLM."""
import csv
import json
from copy import deepcopy
from pathlib import Path
import time

import pytest

from layer4_evaluation.indicators import performance as p, ollama_provider as transport
from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import write
from .test_ollama_provider import sample, provider_case
from .test_manual_pipeline import sandbox


def csv_rows(run,name):
    path=run/'resultados/performance'/name
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream,delimiter=';'))


def number(value):
    return float(value.replace(',','.'))


class NoGpu:
    def __init__(self):
        self.info=p.environment() | dict(gpu=[],sample_seconds=1)
    def sample(self):
        return dict(ram=p.resident_bytes())  # Real native RSS; GPU deliberately unavailable.
    def close(self):pass


def test_exact_call_counters_and_resume_do_not_repeat_cached_usage(tmp_path,provider_case,monkeypatch):
    monkeypatch.setattr(p,'Resources',NoGpu)
    run=tmp_path/'run'
    provider,client,project,profile,_,_=provider_case
    with p.run_session(run) as measurement:
        p.observe_projects([project['project_id']])
        with p.span('preparacion'):
            time.sleep(.005)
            with p.span('embeddings'):time.sleep(.005)
        provider.evaluate(project,[profile])
        # Repeated receipt observation is idempotent within an invocation.
        p.record_call(provider.calls[0],provider.directory/project['project_id']/'attempt_1/call.json')
        measurement.project_state(project['project_id'],'EXITOSO')
    summary=csv_rows(run,'resumen.csv')[0];rows=csv_rows(run,'por_proyecto.csv')
    assert len(rows)==1 and rows[0]['estado']=='EXITOSO'
    assert summary['llamadas_llm']==rows[0]['llamadas_llm']=='1'
    for column,expected in (('tokens_entrada','100'),('tokens_salida','50'),('tokens_totales','150')):
        assert summary[column]==rows[0][column]==expected
    assert rows[0]['conteo_tokens']=='EXACTO_PROVEEDOR'
    assert number(rows[0]['tiempo_inferencia_segundos'])>=0
    assert number(rows[0]['tiempo_directo_proyecto_segundos'])>=number(rows[0]['tiempo_inferencia_segundos'])
    assert summary['gpu_dispositivo_promedio_porcentaje']==rows[0]['pico_vram_proceso_mib']==''
    stages=[number(summary[k]) for k in summary if k.startswith('tiempo_') and k.endswith('_segundos')
            and k not in ('tiempo_total_activo_segundos','tiempo_promedio_directo_proyecto_segundos') and summary[k]]
    assert sum(stages)<=number(summary['tiempo_total_activo_segundos'])+1e-5
    assert number(rows[0]['pico_ram_proceso_mib'])>0
    # A resume with no new inference must retain previous counters and success.
    with p.run_session(run):p.observe_projects([project['project_id']])
    assert csv_rows(run,'resumen.csv')[0]['llamadas_llm']=='1'
    assert csv_rows(run,'por_proyecto.csv')[0]['estado']=='EXITOSO'
    assert client.request.call_count==1


def test_timeout_keeps_call_and_unknown_tokens_blank(tmp_path,provider_case,monkeypatch):
    monkeypatch.setattr(p,'Resources',NoGpu)
    run=tmp_path/'failed'
    provider,client,project,profile,_,_=provider_case
    client.request.side_effect=transport.OllamaError('TIMEOUT','Controlled transport fixture')
    with pytest.raises(transport.OllamaError):
        with p.run_session(run):provider.evaluate(project,[profile])
    summary=csv_rows(run,'resumen.csv')[0];row=csv_rows(run,'por_proyecto.csv')[0]
    assert summary['estado']=='FALLIDO' and row['estado']=='CON_ERROR'
    assert summary['llamadas_llm']==row['llamadas_llm']=='1'
    assert summary['tokens_totales']==row['tokens_totales']==''
    assert row['conteo_tokens']=='NO_DISPONIBLE'
    assert number(summary['tiempo_total_activo_segundos'])>0


def test_overlapping_projects_have_no_exclusive_resource_claim(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'Resources',NoGpu)
    with p.run_session(tmp_path/'parallel'):
        with p.span(project='A'):
            with p.span(project='B'):time.sleep(.002)
    rows=csv_rows(tmp_path/'parallel','por_proyecto.csv')
    assert all(r['pico_ram_proceso_mib']=='' for r in rows)


def test_shared_preparation_is_excluded_from_project_time(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'Resources',NoGpu)
    run=tmp_path/'shared'
    with p.run_session(run):
        start=time.perf_counter()
        with p.span(project='P1'):
            with p.span('preparacion'):time.sleep(.02)
            time.sleep(.002)
        elapsed=time.perf_counter()-start
    summary=csv_rows(run,'resumen.csv')[0];row=csv_rows(run,'por_proyecto.csv')[0]
    assert number(row['tiempo_directo_proyecto_segundos'])+number(summary['tiempo_preparacion_segundos'])<=elapsed+.002


def test_small_pipeline_dry_run_reports_only_measured_stages(sandbox):
    root,_,config=sandbox
    write(root/'config/pipeline_manual.json',config)
    write(root/'data/layer1_sources/base/descriptores.json',[
        dict(id_actividad='P1',resumen='Controlled synthetic project narrative')])
    result=runner.execute_pipeline(root,all_projects=True,dry_run=True,run_id='performance_dry')
    assert result['status']=='VALIDATED_SELECTION'
    run=root/'outputs/runs/performance_dry'
    summary=csv_rows(run,'resumen.csv')[0];rows=csv_rows(run,'por_proyecto.csv')
    assert list(summary)==list(p.SUMMARY_COLUMNS) and list(rows[0])==list(p.PROJECT_COLUMNS)
    assert summary['llamadas_llm']==summary['tokens_totales']=='0'
    assert summary['proyectos_procesados']==summary['proyectos_exitosos']=='0'
    assert rows[0]['estado']=='VALIDADO_SIN_INFERENCIA'
    assert rows[0]['tiempo_directo_proyecto_segundos']==''
    assert summary['tiempo_inferencia_llm_segundos']==summary['tiempo_embeddings_segundos']==summary['tiempo_construccion_grafo_segundos']==''
    assert number(summary['tiempo_preparacion_segundos'])>0
    assert number(summary['tiempo_total_activo_segundos'])>=number(summary['tiempo_preparacion_segundos'])
    assert json.loads((run/'resultados/performance/metadatos.json').read_text(encoding='utf-8'))['model_status']=='CONFIGURED_WITHOUT_CALLS'


def test_native_durations_are_exact_and_missing_values_stay_blank(tmp_path,provider_case,monkeypatch):
    monkeypatch.setattr(p,'Resources',NoGpu)
    provider,client,project,profile,_,_=provider_case
    native=client.request.return_value
    native.update(total_duration=3_000_000_000,load_duration=1_000_000_000,
                  prompt_eval_duration=250_000_000,eval_duration=1_500_000_000)
    run=tmp_path/'api_durations'
    with p.run_session(run):provider.evaluate(project,[profile])
    row=csv_rows(run,'por_proyecto.csv')[0];summary=csv_rows(run,'resumen.csv')[0]
    assert provider.calls[0]['ollama_durations_ns']['total_duration']==native['total_duration']
    for column,expected in zip(p.API_DURATIONS.values(),(3,1,.25,1.5)):
        assert number(row[column])==number(summary[column])==expected
    # Durations from the API are descriptive submetrics, not added to pipeline stages.
    assert number(summary['tiempo_total_activo_segundos'])<3


def test_process_groups_count_unique_pids_and_detect_runner(monkeypatch):
    sensor=p.ProcessSampler();sensor.started=100
    root=p.os.getpid()
    inventory={root:dict(name='python.exe',parent=1),20:dict(name='ollama.exe',parent=root),
        21:dict(name='ollama.exe',parent=20),22:dict(name='python.exe',parent=root)}
    counters={root:(50.,1.,100),20:(50.,2.,200),21:(101.,.5,300),22:(101.,.25,50)}
    monkeypatch.setattr(sensor,'inventory',lambda:inventory)
    monkeypatch.setattr(sensor,'counters',lambda pid:counters[pid])
    first=sensor.sample()
    assert sensor.python_pids=={root,22} and sensor.ollama_pids=={20,21}
    assert first['ram_python']==150 and first['ram_ollama']==500 and first['ram_combined']==650
    counters[root]=(50.,1.2,90);counters[20]=(50.,2.1,180);counters[21]=(101.,1.,310)
    second=sensor.sample()
    assert second['cpu_combined_delta']==pytest.approx(second['cpu_python_delta']+second['cpu_ollama_delta'])
    assert second['ram_combined']==sum(counters[pid][2] for pid in counters)


def test_nvidia_smi_without_bindings_handles_wddm_na(monkeypatch):
    from types import SimpleNamespace
    sensor=p.Resources.__new__(p.Resources)
    sensor.process=None;sensor.nv=None;sensor.handles=[];sensor.smi=True;sensor.gpu_last=-float('inf');sensor.info={}
    sensor.processes=SimpleNamespace(sample=lambda:{},observed_ollama={20},python_pids={p.os.getpid()},ollama_pids={20})
    def command(args):
        output='80, 4500\n' if 'query-gpu' in args[1] else '20, [N/A]\n'
        return SimpleNamespace(returncode=0,stdout=output)
    monkeypatch.setattr(p,'_command',command)
    values=sensor._sample()
    assert values['gpu']==80 and values['device_vram']==4500*1024**2
    assert values['vram_ollama'] is None and values['vram_combined'] is None


def test_total_ram_peak_is_simultaneous_not_sum_of_peaks(tmp_path,monkeypatch):
    class AlternatePeaks(NoGpu):
        def __init__(self):super().__init__();self.n=0
        def sample(self):
            self.n+=1
            a,b=(100,10) if self.n%2 else (10,100)
            return dict(ram=a,ram_python=a,ram_ollama=b,ram_combined=a+b,
                        cpu_python_delta=.001,cpu_ollama_delta=.002,cpu_combined_delta=.003)
    monkeypatch.setattr(p,'Resources',AlternatePeaks)
    run=tmp_path/'distinct_peaks'
    with p.run_session(run) as measurement:
        with p.span(project='P1'):measurement.sample()
    row=csv_rows(run,'resumen.csv')[0]
    # Bytes -> MiB; values are controlled sensor observations, not benchmark results.
    assert number(row['pico_ram_python_ollama_mib'])==pytest.approx(110/1024**2,abs=1e-6)
    assert number(row['pico_ram_python_ollama_mib'])<number(row['pico_ram_python_mib'])+number(row['pico_ram_ollama_mib'])
