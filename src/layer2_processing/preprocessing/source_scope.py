"""Read-only record/identity indices for the existing ETL, never a second resolver.

Positive scope uses exact, unambiguous keys in their declared namespaces. Minimal
identity witnesses preserve the existing resolver's decisions without importing
other articles into the knowledge corpus. No titles or names select publications.
"""
from collections import defaultdict, deque
import re

from .normalize import identifier, text, name, email, doi, eid
from .identity import STRONG
from .canonicalize import entity_id


def plan_scope(root, raw, config, discovery, known):
    from .adapters import mapping_for, file_configuration, clean
    scope = config.get('processing_scope')
    if config.get('knowledge_scope')=='BASE_GLOBAL_V1':return None
    if not scope:
        return None
    if any(f['status'] != 'READY_FOR_VALIDATION' for f in discovery.values()):
        raise ValueError('El alcance no puede resolverse con fuentes estructuralmente invalidas o pendientes')
    records, candidates, articles = [], [], defaultdict(list)
    by_file = defaultdict(list)
    for rel, item in discovery.items():
        override = file_configuration(config, rel)
        spec = known[item['domain']]
        person_mapping = item['mapping'] if item['domain']=='investigadores' else mapping_for('optional', item['headers'],
            {'mapping':override.get('researcher_mapping',spec.get('researcher_mapping',{}))},None)
        person_mapping={f:cols for f,cols in person_mapping.items() if f in (*STRONG,'document_type','full_name','email')}
        unwrap = set(spec.get('unwrap_quoted_fields', []))
        for record in item['records']:
            original = record['original_values']
            def values(field, mapping, personal=False):
                result=[]
                for column in mapping.get(field, []):
                    if field == 'source_project_id' and item.get('project_contract'):
                        result.append(str(original[column]))
                        continue
                    v=text(original.get(column))
                    if personal and field in unwrap and v and len(v)>1 and v[0]==v[-1]=='"':
                        v=text(v[1:-1])
                    v=identifier(v)
                    if v:result.append(v)
                return sorted(set(result))
            project_ids=values('source_project_id',item['mapping'])
            row=dict(file=rel, row=record['row'], domain=item['domain'], record=record,
                     mapping=item['mapping'], person_mapping=person_mapping, spec=spec,
                     project_ids=project_ids, candidate=None)
            index=len(records);records.append(row);by_file[rel].append(index)
            if item['domain']=='articulos':
                fields={f:next((clean(original.get(c)) for c in item['mapping'].get(f,[]) if clean(original.get(c))),None)
                        for f in ('source_article_id','eid','doi')}
                fields.update(eid=eid(fields['eid']),doi=doi(fields['doi']))
                for field,pattern in (('eid',r'2-s2\.0-\d+'),('doi',r'10\.\d{4,9}/\S+')):
                    if fields[field] and not re.fullmatch(pattern,fields[field],re.I):fields[field]=None
                # Occurrence fallback remains ungrouped here; native ETL owns it.
                row['article_key']=entity_id('articulos',fields) if any(fields.values()) else 'OCC:'+rel+':'+str(record['row'])
                articles[row['article_key']].append(index)
            if person_mapping:
                fields={f:values(f,person_mapping,True) for f in (*STRONG,'document_type')}
                fullname=next((text(original.get(c)) for c in person_mapping.get('full_name',[]) if text(original.get(c))),None)
                if 'full_name' in unwrap and fullname and len(fullname)>1 and fullname[0]==fullname[-1]=='"':
                    fullname=text(fullname[1:-1])
                mail=next((email(original.get(c)) for c in person_mapping.get('email',[]) if email(original.get(c))),None)
                weak=(name(fullname),mail) if fullname and mail and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',mail) else None
                invalid=any(not re.fullmatch(r'[\w.:/-]+',v) or v.casefold() in {'nan','none','null'} for f in STRONG for v in fields[f])
                if item['domain']=='investigadores':
                    invalid|=any(not re.fullmatch(r'[\w.:/-]+',v) or v.casefold() in {'nan','none','null'} for v in project_ids)
                if (any(fields[f] for f in STRONG) or weak) and not invalid:
                    row['candidate']=len(candidates)
                    candidates.append(dict(index=index,fields=fields,weak=weak,fullname=fullname,mail=mail))
    primary=set(scope.get('primary_files') or discovery)
    explicit=scope.get('project_ids')
    available={p for rel in primary for i in by_file[rel] for p in records[i]['project_ids']}
    if explicit is not None and set(explicit)-available:
        raise ValueError('Proyectos no presentes en las fuentes seleccionadas: '+', '.join(sorted(set(explicit)-available)))
    projects=set(explicit) if explicit is not None else available
    included=set()
    project_members=defaultdict(set)
    primary_articles=set()
    for i,row in enumerate(records):
        linked=set(row['project_ids']) & projects
        if row['domain']=='proyectos' and linked:
            included.add(i)
        if row['domain']=='investigadores' and (linked or explicit is None and row['file'] in primary):
            included.add(i)
            for p in linked:project_members[p].add(i)
        if row['domain']=='articulos' and explicit is None and row['file'] in primary:
            primary_articles.add(row['article_key'])
    # Index only namespaces recognized by the current identity resolver.
    tokens=defaultdict(list)
    for c,candidate in enumerate(candidates):
        for field in STRONG:
            for value in candidate['fields'][field]:tokens[field,value].append(c)
        if candidate['weak']:tokens['name_email',candidate['weak']].append(c)
    project_article_keys={p:set() for p in projects}
    positive=defaultdict(set)
    for p,indices in project_members.items():
        for i in indices:
            c=records[i]['candidate']
            if c is None:continue
            for field in STRONG:
                vals=candidates[c]['fields'][field]
                if len(vals)==1:positive[field,vals[0]].add(p)
    for key,ps in positive.items():
        for c in tokens[key]:
            row=records[candidates[c]['index']]
            if row['domain']=='articulos':
                for p in ps:project_article_keys[p].add(row['article_key'])
    selected_keys=primary_articles.copy()
    for keys in project_article_keys.values():selected_keys.update(keys)
    for key in selected_keys:included.update(articles[key])
    # Preserve the entire source-ID group, including other authors/contradictions.
    seeds={records[i]['candidate'] for i in included if records[i]['candidate'] is not None}
    # Minimal exact-key witness paths: retain global ambiguity and the same strong
    # anchor, without canonicalizing the whole corpus or embedding context papers.
    parent=list(range(len(candidates)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    for indices in tokens.values():
        for c in indices[1:]:union(indices[0],c)
    groups=defaultdict(list)
    for c in range(len(candidates)):groups[find(c)].append(c)
    def witness_indices(seeds):
        seed_groups=defaultdict(list)
        for c in seeds:seed_groups[find(c)].append(c)
        witnesses=set(seeds)
        for group,group_seeds in seed_groups.items():
            values={f:defaultdict(list) for f in (*STRONG,'document_type')}
            for c in groups[group]:
                for f in values:
                    for v in candidates[c]['fields'][f]:values[f][v].append(c)
            conflict=next((f for f in values if len(values[f])>1),None)
            targets=([indices[0] for indices in list(values[conflict].values())[:2]] if conflict else
                     [next(iter(values[f].values()))[0] for f in STRONG if values[f]][:1])
            # BFS from each witness traverses each key once, not the all-pairs graph.
            for target in targets:
                previous={target:None};queue=deque([target]);visited_keys=set()
                pending=set(group_seeds)-{target}
                while queue and pending:
                    current=queue.popleft()
                    for f in STRONG:
                        for value in candidates[current]['fields'][f]:
                            key=f,value
                            if key in visited_keys:continue
                            visited_keys.add(key)
                            for neighbor in tokens[key]:
                                if neighbor not in previous:
                                    previous[neighbor]=current;queue.append(neighbor);pending.discard(neighbor)
                    weak=candidates[current]['weak']
                    if weak and ('name_email',weak) not in visited_keys:
                        visited_keys.add(('name_email',weak))
                        for neighbor in tokens['name_email',weak]:
                            if neighbor not in previous:
                                previous[neighbor]=current;queue.append(neighbor);pending.discard(neighbor)
                for seed in group_seeds:
                    c=seed
                    while c is not None:
                        witnesses.add(c);c=previous[c]
        return witnesses
    # Corroborate the candidate associations with the EXISTING resolver. Only
    # identity metadata and minimal witnesses enter this check, not paper texts.
    from .identity import resolve
    indexed=witness_indices(seeds)
    native=[]
    for c in sorted(indexed):
        candidate=candidates[c];row=records[candidate['index']];ref=row['record']
        person={f:vals[0] if len(vals)==1 else None for f,vals in candidate['fields'].items()}
        person.update(full_name=candidate['fullname'],email=candidate['mail'],
            _identity_values={f:vals for f,vals in candidate['fields'].items() if f in STRONG},
            _file=ref['file'],_row=ref['row'],_sheet=ref['sheet'],_raw=ref['original_values'],
            _candidate_domain='scope_index',_scope_index=c)
        native.append(person)
    entities,_,_=resolve(native,'SCOPE_IDENTITY_INDEX')
    resolved={r['_scope_index']:e['researcher_id'] for e in entities if e['identity_status']=='resolved' for r in e['_members']}
    identity_states={r['_scope_index']:e['identity_status'] for e in entities for r in e['_members']}
    candidate_project_article_keys=project_article_keys
    project_article_keys={p:set() for p in projects}
    link_status={}
    for p,indices in project_members.items():
        member_candidates={records[i]['candidate'] for i in indices if records[i]['candidate'] is not None}
        verified_ids={resolved[c] for c in member_candidates if c in resolved}
        for i in included:
            row=records[i]
            if row['domain']=='articulos' and resolved.get(row['candidate']) in verified_ids:
                project_article_keys[p].add(row['article_key'])
        link_status[p]=dict(member_occurrences=len(indices),resolved_occurrences=sum(c in resolved for c in member_candidates),
            ambiguous_occurrences=sum(identity_states.get(c)=='ambiguous' for c in member_candidates),
            verified_article_groups=len(project_article_keys[p]),candidate_article_groups=len(candidate_project_article_keys[p]))
    selected_keys=primary_articles.copy()
    for keys in project_article_keys.values():selected_keys.update(keys)
    unverified=[dict(file=records[i]['file'],row=records[i]['row'],article_key=records[i]['article_key'],
        reason='RESEARCHER_ASSOCIATION_NOT_CORROBORATED') for i in sorted(included)
        if records[i]['domain']=='articulos' and records[i]['article_key'] not in selected_keys]
    included={i for i in included if records[i]['domain']!='articulos'}
    for key in selected_keys:included.update(articles[key])
    seeds={records[i]['candidate'] for i in included if records[i]['candidate'] is not None}
    witnesses=witness_indices(seeds)
    contexts=[candidates[c]['index'] for c in sorted(witnesses) if candidates[c]['index'] not in included]
    rows={rel:[records[i]['row'] for i in by_file[rel] if i in included] for rel in discovery}
    summary=dict(version='PROJECT_SCOPE_V1', mode=scope['mode'], projects=sorted(projects),
        source_counts={d:sum(len(f['records']) for f in discovery.values() if f['domain']==d) for d in ('proyectos','articulos','investigadores')},
        selected_counts={d:sum(records[i]['domain']==d for i in included) for d in ('proyectos','articulos','investigadores')},
        identity_context_records=len(contexts), rows=rows, identity_links=link_status,
        unverified_production=unverified, candidate_project_article_keys={p:sorted(keys) for p,keys in candidate_project_article_keys.items()},
        project_article_keys={p:sorted(keys) for p,keys in project_article_keys.items()}, primary_article_keys=sorted(primary_articles),
        relation_basis='Production scope requires a resolved native researcher identity linked to a selected project. Candidate/ambiguous matches are excluded from corpus; no names/titles select records.')
    return dict(rows={k:set(v) for k,v in rows.items()}, summary=summary,
                contexts=[records[i] for i in contexts])
