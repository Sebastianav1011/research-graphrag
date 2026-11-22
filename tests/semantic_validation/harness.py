"""Test-only corpus, independent expectations and immutable historical access.

This module never changes production policy. Literal fixture annotations are
authored from institutional definitions before inference, not from model scores.
"""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import csv,json,hashlib,sys
from functools import lru_cache

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
RUN=ROOT/'outputs/runs/local/run_20261116_094429_222507'
AUDIT=ROOT/'outputs/audits/run_20261116_094429_222507_precision'
OUT=ROOT/'outputs/audits/validacion_semantica_graphrag'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,data):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def filehash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def csvwrite(path,rows):
    if not rows:return
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=';');w.writeheader();w.writerows(rows)
def plans():return [read(p) for p in sorted(RUN.glob('evaluation/batch_*/plan.json'))]
@lru_cache(maxsize=1)
def catalog():
    p=read(next(RUN.glob('evaluation/batch_*/plan.json')));return p['profiles'],p['rubrics']
def corpus():
    seeds=read(Path(__file__).with_name('catalog_cases.json'));profiles,_=catalog();assert set(seeds)==set(profiles)
    result=[]
    ambiguous={'ASC-03','COL-03','CUL-01','DIV-04','ECO-06','POL-05','SOC-04'}
    for iid,x in sorted(seeds.items()):
        positive=x['context']+' '+x['action'];critical=x['action'];context=x['context']
        scenarios=[
          ('positivo',positive,'SUPPORTED','Se documentan actuación propia, actores y condiciones del indicador; revisar todos los requisitos antes de aprobación humana.'),
          ('tematico',context+' Se revisa bibliografía sobre el tema. Esta fuente no aporta evidencia de las actuaciones del proyecto.','INSUFFICIENT_EVIDENCE','Tema y actores no prueban la actuación obligatoria.'),
          ('prospectivo_vago',context+' Se propone investigar si algún día sería posible alcanzar esta situación hipotética: «'+critical+'». Es una hipótesis para estudiar, no un protocolo comprometido ni un resultado propio.','INSUFFICIENT_EVIDENCE','Una hipótesis vaga no demuestra el mecanismo ni el resultado; no equivale a propuesta concreta.'),
          ('parcial',context+' Se identifica el ámbito y sus actores, pero el texto suministrado no documenta la siguiente condición: '+profiles[iid]['indicator_name']+'.','INSUFFICIENT_EVIDENCE','Se conservan contexto y afinidad sin acreditar el requisito crítico '+x['criterion']+'.'),
          ('sin_informacion','No se suministraron objetivos, metodología ni resultados. Sólo existe un identificador de proyecto.','INSUFFICIENT_EVIDENCE','Sin evidencia ni exclusión documentada: aplicabilidad indeterminada, no NOT_APPLICABLE.'),
          ('negacion',context+' La siguiente atribución fue expresamente negada por el informe: «'+critical+'». No describe una contribución del proyecto.','INSUFFICIENT_EVIDENCE','La negación explícita invalida el único cumplimiento; tema no cambia.'),
          ('otro_proyecto',context+' Antecedente: la siguiente actuación pertenece exclusivamente al proyecto Q, ajeno a P: «'+critical+'». El documento no atribuye esa actuación a P.','INSUFFICIENT_EVIDENCE','No transferir logros de otra investigación, aun con afinidad temática.'),
          ('sin_condicion',context,'INSUFFICIENT_EVIDENCE','Par mínimo: se elimina únicamente el bloque que acredita '+x['criterion']+'; no basta el contexto restante.')]
        for scenario,text,expected,reason in scenarios:
            result.append(dict(case_id=iid+'__'+scenario,indicator_id=iid,scenario=scenario,text=text,expected=expected,
                mode='PROSPECTIVE_V2',oracle_status='PENDING_HUMAN' if scenario=='positivo' and iid in ambiguous else 'SYNTHETIC_EXPLICIT',
                oracle_author='TEST_AUTHOR_FROM_CATALOG_NOT_MODEL_OUTPUT',rationale=reason,critical_criterion=x['criterion'],critical_span=critical,
                pair_id=iid+'__positivo',data_type='SYNTHETIC_TEST_ONLY',origin_project='Q' if scenario=='otro_proyecto' else 'P',
                evidence_stage='UNSPECIFIED_MODEL_MUST_JUDGE',reference_definition=profiles[iid]['descripcion_ampliada']))
    futures={
      'ECO-02':'La cooperativa A implementará control térmico en el secado de café; comparará costos por lote de igual volumen y calidad con el trimestre previo. El ahorro esperado del 18 % se fundamenta en ensayo energético y presupuesto de esa mejora. Es un plan comprometido, sin ahorro realizado.',
      'CUL-02':'El proyecto P conservará los cantos reconocidos por la comunidad A como su patrimonio cultural inmaterial mediante registro acordado y archivo comunitario, con acceso de sus portadores. Las tareas y responsables están definidos, aún no ejecutados.',
      'ASC-01':'El proyecto P establecerá mesas mensuales entre agrónomos y agricultores, en las que ambos propondrán, discutirán y acordarán criterios del protocolo de semillas, incorporando de forma recíproca saber local y conocimiento agronómico. Es un método previsto, no ejecutado.',
      'TEC-02':'El proyecto P validará su sensor de riego con agricultores usuarios destinatarios en sus parcelas: ejecutarán tareas de lectura y ajuste, registrarán dificultades y valorarán la utilidad; sus aportes modificarán el informe de validación. Las tareas están previstas, no realizadas.',
      'TEC-07':'La cooperativa A incorporará a su operación semanal el software de planificación generado por P, adaptará los turnos y asignará responsables de mantenimiento. El plan de apropiación identifica actor, acciones y contexto; no afirma adopción ya ocurrida.',
      'SAL-03':'El proyecto P implementará adecuaciones de acceso y entrenamiento de movilidad para personas con discapacidad motora de A, con responsables y sesiones definidas para mejorar autonomía cotidiana. Es una intervención concreta prevista, sin ejecución aún.'}
    for iid,text in futures.items():
        for mode in ('DEMONSTRATED','PROSPECTIVE_V2'):
            # Explicitly keep operational reinterpretation separate from institutional result.
            expected='SUPPORTED' if mode=='PROSPECTIVE_V2' else ('PENDING_HUMAN' if iid in ('ASC-01','TEC-02') else 'INSUFFICIENT_EVIDENCE')
            result.append(dict(case_id=iid+'__plan_concreto__'+mode,indicator_id=iid,scenario='plan_concreto',text=text,expected=expected,mode=mode,
                oracle_status='PENDING_HUMAN' if expected=='PENDING_HUMAN' else 'SYNTHETIC_EXPLICIT',oracle_author='INDEPENDENT_MODE_DISTINCTION',
                rationale='Misma evidencia, interpretación temporal diferente: no equivale a logro ejecutado. La contraparte operativa prospectiva admite un plan concreto.',critical_criterion=seeds[iid]['criterion'],critical_span=text,pair_id=iid+'__plan_concreto',data_type='SYNTHETIC_TEST_ONLY',origin_project='P',evidence_stage='FUTURE_EXPLICIT',reference_definition=profiles[iid]['descripcion_ampliada']))
    extras=[
      ('TEC-07','exclusion','El proyecto P se limita expresamente a historia de manuscritos; excluye desarrollar, entregar o aplicar cualquier solución tecnológica y no tiene actores adoptantes externos.','NOT_APPLICABLE','Alcance positivamente incompatible con apropiación tecnológica.'),
      ('SOC-04','financiador','La Fundación A financió el proyecto P. No se identifica qué beneficio recibió ni personas beneficiarias o conteo; sólo consta el monto financiado.','INSUFFICIENT_EVIDENCE','Financiador no implica beneficiario; faltan recepción y conteo.'),
      ('SOC-03','region_sin_impacto','El proyecto P estudia desigualdad en Nariño. Sólo se describe la región y población; no hay acción propia ni aporte documentado frente a exclusión.','INSUFFICIENT_EVIDENCE','Ubicación no demuestra contribución social.'),
      ('TEC-07','publicacion_sin_adopcion','El artículo de P describe su software y su arquitectura. No presenta uso, adaptación o sostenimiento por actores extraacadémicos ni una ruta concreta prevista para ello.','INSUFFICIENT_EVIDENCE','Publicar/describir no equivale a adopción, tampoco como propuesta.'),
      ('COL-02','actores_mencionados','El proyecto P menciona una junta, una empresa y el municipio en antecedentes. No describe roles, aportes o participación de estos actores en ninguna etapa.','INSUFFICIENT_EVIDENCE','Presencia de nombres no es colaboración.'),
      ('POL-04','financiador_validador','La entidad estatal A financió y certificó técnicamente el software de P. El texto no documenta adopción en sus prácticas ni plan de uso por ella.','INSUFFICIENT_EVIDENCE','Validación y financiación no prueban adopción.'),
      ('SAL-04','mortalidad_negada','El proyecto P implementó una intervención en A; la tasa anual de mortalidad no disminuyó: permaneció en 20 por mil habitantes antes y después. No se reporta otra mejora.','INSUFFICIENT_EVIDENCE','Negación específica de descenso, aun con intervención y tasa.'),
      ('ECO-02','palabras_clave','Palabras clave: ahorro, reducción de costos, innovación, costos productivos. El contenido disponible es una bibliografía, sin implementación, comparación ni mecanismo propio.','INSUFFICIENT_EVIDENCE','Palabras del indicador sin cumplimiento.')]
    for iid,name,text,expected,reason in extras:
        result.append(dict(case_id=iid+'__'+name,indicator_id=iid,scenario=name,text=text,expected=expected,mode='PROSPECTIVE_V2',oracle_status='SYNTHETIC_EXPLICIT',oracle_author='EXPLICIT_LOGICAL_CONTRAST',rationale=reason,critical_criterion=seeds[iid]['criterion'],critical_span='',pair_id='',data_type='SYNTHETIC_TEST_ONLY',origin_project='P',evidence_stage='MODEL_MUST_JUDGE',reference_definition=profiles[iid]['descripcion_ampliada']))
    return result

def original_attempts():
    for planpath in sorted(RUN.glob('evaluation/batch_*/plan.json')):
        plan=read(planpath)
        projects={p['project_id']:p for p in plan['projects']}
        batch=planpath.parent
        for rp in batch.glob('calls/*/*/records/assessment/*.json'):
            record=read(rp);base=rp.parents[2];dirs=sorted(base.glob('assessment/ollama_runs/*/attempt_*'),key=lambda d:int(d.name.split('_')[-1]))
            iid=read(dirs[0]/'selection.json')['assessments'][0]['indicator_id'];pid=record['project_id']
            yield plan,projects[pid],iid,base,record,dirs

def compare_expected(case,actual):
    """No semantic classification here: compare to a frozen independent label."""
    if case['expected']=='PENDING_HUMAN' or case['oracle_status']=='PENDING_HUMAN':return 'PENDING_HUMAN'
    return 'PASS' if actual==case['expected'] else 'FAIL'

def promotion_findings(before,after,evidence_before,evidence_after):
    """Monitor changes, not an alternative classifier; does not amend the result."""
    order={'NOT_DEMONSTRATED':0,'PARTIAL':1,'CLEAR':2}
    old={x['criterion_id']:x for x in before['criterion_assessments']}
    changed=[x['criterion_id'] for x in after['criterion_assessments'] if x['criterion_id'] in old and
        (order[x['support']]>order[old[x['criterion_id']]['support']] or x.get('coverage',0)>old[x['criterion_id']].get('coverage',0))]
    return dict(promoted_criteria=changed,same_evidence=digest(evidence_before)==digest(evidence_after),
        requires_adjudication=bool(changed) and digest(evidence_before)==digest(evidence_after))

def binary_metrics(rows):
    """Only independent validated labels enter; blocked outputs are abstentions."""
    eligible=[r for r in rows if r.get('validated') is True and r.get('expected') in ('SUPPORTED','INSUFFICIENT_EVIDENCE')]
    scored=[r for r in eligible if r.get('actual') in ('SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_APPLICABLE')]
    tp=sum(r['expected']=='SUPPORTED' and r['actual']=='SUPPORTED' for r in scored)
    fp=sum(r['expected']=='INSUFFICIENT_EVIDENCE' and r['actual']=='SUPPORTED' for r in scored)
    fn=sum(r['expected']=='SUPPORTED' and r['actual']!='SUPPORTED' for r in scored)
    tn=sum(r['expected']=='INSUFFICIENT_EVIDENCE' and r['actual']!='SUPPORTED' for r in scored)
    precision=tp/(tp+fp) if tp+fp else None;recall=tp/(tp+fn) if tp+fn else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return dict(validated=len(eligible),scored=len(scored),abstentions=len(eligible)-len(scored),TP=tp,FP=fp,FN=fn,TN=tn,precision=precision,recall=recall,F1=f1)
