"""Compare actual reloaded meshes/results. Never synthesize a numerical solution."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from prepare_case import read, sha, write_new


def require(ok,msg):
    if not ok:raise ValueError(msg)


def measure(directory):
    """Unverified arithmetic helper for tests; use compare_verified for production."""
    directory=Path(directory)
    raw=read(directory/'solution-readback.json')
    vertices=read(directory/'mesh-vertices.json');elements=read(directory/'mesh-elements.json')
    return _measure_data(directory,raw,vertices,elements,
                         {n:sha(directory/n) for n in ('solution-readback.json','mesh-vertices.json','mesh-elements.json')})


def _measure_data(directory,raw,vertices,elements,input_hashes):
    from stage_driver import domain_quality
    quality=domain_quality(raw)
    require(elements.get('index_base')==0,'Connectivity index base must be documented as zero')
    coords=vertices['coordinate_rows'];require(len(coords)==2 and len(coords[0])==len(coords[1])>0,'Invalid coordinates')
    points=list(zip(*coords));require(all(math.isfinite(x) for p in points for x in p),'Nonfinite mesh')
    tri=elements['types']['tri']['connectivity_rows'];require(len(tri)==3,'Only linear mesh vertex triangles supported')
    require(len({len(row) for row in tri})==1 and len(tri[0])>0,'No triangles')
    lengths=[];local=[];signature=[];L=raw['parameters_si']['L']
    for ids in zip(*tri):
        require(all(type(i) is int and 0<=i<len(points) for i in ids),'Invalid mesh vertex index')
        cell=[points[i] for i in ids];signature.append(tuple(sorted(cell)))
        edges=[math.dist(cell[i],cell[(i+1)%3]) for i in range(3)]
        require(min(edges)>0,'Degenerate mesh edge');lengths.extend(edges)
        if sum(x for x,y in cell)/3 <= L/4: local.extend(edges)
    require(local,'No actual elements in left-quarter local region')
    require(raw['mesh']['num_tri']==len(tri[0]) and raw['mesh']['num_vertices']==len(points),'Mesh count/readback mismatch')
    p=raw['parameters_si'];qx=p['k_slab']*(p['T_left']-p['T_right'])/p['L'];Q=qx*p['H']*p['thickness']
    xy=raw['sample_coordinates'];values=raw['target_values'];T=values['temperature_field']['values'];flux=values['conductive_heat_flux']['values']
    require(len(T)==len(xy[0])==len(xy[1]) and len(flux)==2 and all(len(row)==len(T) for row in flux),'Field samples malformed')
    all_values=T+flux[0]+flux[1]+[values['through_heat_rate']['value']]
    require(all(type(x) in (int,float) and math.isfinite(x) for x in all_values),'Nonfinite result')
    analyticT=[p['T_left']+(p['T_right']-p['T_left'])*x/p['L'] for x in xy[0]]
    return {'directory':str(directory.resolve()),'raw':raw,'signature':sorted(signature),
            'observed_mesh':{'num_vertices':len(points),'num_tri':len(tri[0]),
              'edge_min_m':min(lengths),'edge_max_m':max(lengths),'edge_mean_m':sum(lengths)/len(lengths),
              'local_region':'triangle centroid x <= L/4','local_edge_max_m':max(local),'local_edge_mean_m':sum(local)/len(local),
              'quality':{**quality,'scope':'explicit dimension 2; all-domain and named-domain statistics agree'}},
            'analytic_reference_not_measurement':{'qx_W_per_m2':qx,'qy_W_per_m2':0,'Q_W':Q},
            'measured_errors':{'temperature_max_abs_K':max(abs(a-b) for a,b in zip(T,analyticT)),
              'qx_max_abs_W_per_m2':max(abs(v-qx) for v in flux[0]),'qy_max_abs_W_per_m2':max(abs(v) for v in flux[1]),
              'heat_rate_abs_W':abs(values['through_heat_rate']['value']-Q)},
            'input_hashes':input_hashes}


def compare(first,second):
    """Unverified arithmetic, never a runtime measurement acceptance entry."""
    return _compare_data(measure(first),measure(second))


def _compare_data(a,b):
    require(a['raw']['case_spec_sha256']==b['raw']['case_spec_sha256'],'Different case definitions')
    require(a['raw']['parameters_si']==b['raw']['parameters_si'],'Different physical variants cannot be a mesh refinement pair')
    require(a['raw']['sample_coordinates']==b['raw']['sample_coordinates'],'Sample coordinates differ')
    av=a['raw']['target_values'];bv=b['raw']['target_values']
    delta={'temperature_max_abs_K':max(abs(x-y) for x,y in zip(av['temperature_field']['values'],bv['temperature_field']['values'])),
           'heat_rate_abs_W':abs(av['through_heat_rate']['value']-bv['through_heat_rate']['value']),
           'flux_max_abs_W_per_m2':max(abs(x-y) for ar,br in zip(av['conductive_heat_flux']['values'],bv['conductive_heat_flux']['values']) for x,y in zip(ar,br))}
    changed=a.pop('signature')!=b.pop('signature')
    for item in (a,b):item.pop('raw')
    return {'status':'unverified_data_comparison','evidence_level':'unverified_inputs','actual_mesh_changed':changed,'coarse':a,'fine':b,'target_differences':delta,
            'acceptance':'not_assessed','numerical_convergence':'not_assessed','experimental_validity':'not_assessed',
            'limitation':'Linear analytic field may already be represented exactly by a coarse mesh. Zero target difference does not establish general mesh convergence. Set task-specific criteria before running.'}


def _same(a,b):
    return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)


def _digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def _json_bytes(data):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON key: '+key);result[key]=value
        return result
    def invalid(value):raise ValueError('Nonfinite JSON: '+value)
    return json.loads(data.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=invalid)


def verify_run(directory,runner):
    """Revalidate accepted runtime files and compute from their exact byte snapshots.

    This checks provenance consistency, not authenticity of the COMSOL adapter.
    No process is started. A simulated accepted run is never a measurement.
    """
    root=Path(directory).resolve(strict=True)
    watched={}
    def snapshot(path,expected=None):
        path=Path(path).resolve(strict=True);data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
        require(expected is None or digest==expected,'Accepted file hash mismatch: '+str(path))
        if str(path) in watched:require(watched[str(path)]==digest,'File changed during comparison: '+str(path))
        watched[str(path)]=digest
        return _json_bytes(data)
    def inside(relative):
        require(isinstance(relative,str) and relative.strip(),'Missing artifact path')
        p=Path(relative)
        require(not p.is_absolute() and not p.drive and '..' not in p.parts,'Artifact path escapes run')
        path=(root/p).resolve(strict=True)
        require(path.is_relative_to(root) and path!=root and path.is_file(),'Artifact path escapes run')
        return path
    # Track the acceptance inputs across inspect/load/snapshot calculation.
    for name in ('config.json','bundle.json','started.json','process.json'):
        path=root/name;watched[str(path)]=_digest(path)
    inspected=runner.inspect(root)
    require(inspected.get('completion_evidence_accepted') is True and inspected.get('status')=='completion_evidence_accepted',
            'Completion evidence not accepted')
    require(inspected.get('evidence_level')=='runtime_observation','Accepted simulation is not a runtime measurement')
    loaded_root,cfg,meta=runner.load_bundle(root)
    require(Path(loaded_root).resolve()==root,'Loaded run directory differs')
    require(cfg.get('execution_kind')=='comsol','Production comparison requires execution_kind=comsol')
    require(cfg.get('operation') in ('solve','export'),'Only stationary solve/export comparison supported')
    for key in ('run_id','fingerprint'):
        require(isinstance(meta.get(key),str) and meta[key] and inspected.get(key)==meta[key],'Acceptance identity mismatch: '+key)
    require(inspected.get('operation')==cfg['operation'],'Acceptance operation mismatch')
    hashes=inspected.get('output_hashes');require(isinstance(hashes,dict),'Acceptance output hashes missing')
    outputs={};physical_paths=set()
    for entry in cfg['outputs']:
        name=entry['path'];path=inside(name)
        require(name not in outputs and path not in physical_paths,'Duplicate/aliased output path')
        outputs[name]={'path':str(path),'role':entry['role'],'sha256':hashes.get(name)};physical_paths.add(path)
    require(set(outputs)==set(hashes),'Acceptance output set differs from declaration')
    for name,binding in outputs.items():
        require(isinstance(binding['sha256'],str) and _digest(binding['path'])==binding['sha256'],'Accepted output hash mismatch: '+name)
        watched[binding['path']]=binding['sha256']
    for name,role in [('solution-readback.json','solution_readback'),('mesh-vertices.json','mesh_evidence'),('mesh-elements.json','mesh_evidence')]:
        require(name in outputs and outputs[name]['role']==role,'Required declared output/role missing: '+name)
    obs_names=[n for n,o in outputs.items() if o['role']=='solver_observation']
    require(len(obs_names)==1,'One declared solver observation required')
    obs_name=obs_names[0];obs_binding=outputs[obs_name];accepted_obs=inspected.get('solver_observation',{})
    require(accepted_obs.get('evidence_level')=='runtime_observation','Observation evidence level is not runtime_observation')
    require(Path(accepted_obs.get('path','')).resolve()==Path(obs_binding['path']) and accepted_obs.get('sha256')==obs_binding['sha256'],
            'Accepted observation path/hash mismatch')
    evidence_path=inside(cfg['evidence']);require(evidence_path not in physical_paths,'Completion marker aliases an output')
    evidence=snapshot(evidence_path)
    observed=snapshot(obs_binding['path'],obs_binding['sha256'])
    raw=snapshot(outputs['solution-readback.json']['path'],hashes['solution-readback.json'])
    vertices=snapshot(outputs['mesh-vertices.json']['path'],hashes['mesh-vertices.json'])
    elements=snapshot(outputs['mesh-elements.json']['path'],hashes['mesh-elements.json'])
    for document in (evidence,observed,raw):
        for key in ('run_id','fingerprint'):require(document.get(key)==meta[key],'Evidence/readback identity mismatch: '+key)
    require(evidence.get('operation')==cfg['operation'] and evidence.get('status')=='completed','Completion marker state mismatch')
    require(_same(evidence.get('output_hashes'),hashes),'Completion output set/hash mismatch')
    require(observed.get('operation')==cfg['operation'],'Observation operation mismatch')
    require(observed.get('solver_status')==('completed' if cfg['operation']=='solve' else 'existing_solution_available'),'Observation solver status mismatch')
    for document in (evidence,observed,inspected):
        require(_same(document.get('completed_positions'),cfg['expected_positions']),'Accepted position coverage mismatch')
    require(observed.get('observation',{}).get('method')=='saved_solution_readback','This comparator requires independent saved-solution readback')
    def has_readback(refs):
        return isinstance(refs,list) and any(isinstance(x,dict) and x.get('path')=='solution-readback.json'
                   and x.get('sha256')==hashes['solution-readback.json'] for x in refs)
    require(has_readback(observed['observation'].get('evidence')),'Accepted observation does not reference this readback')
    require(raw.get('mesh_vertices_sha256')==hashes['mesh-vertices.json'] and raw.get('mesh_elements_sha256')==hashes['mesh-elements.json'],
            'Readback/mesh hash relationship mismatch')
    require(raw.get('status')=='independent_saved_solution_readback' and raw.get('mode')==('readback' if cfg['operation']=='solve' else 'export'),
            'Readback phase/state mismatch')
    # Case identity is bound through the exact runner argument and its pins, not
    # inferred from whichever nearby case file happens to exist.
    argv=cfg['argv'];locations=[i for i,x in enumerate(argv) if x=='--settings']
    require(len(locations)==1 and locations[0]+1<len(argv),'Unique pinned --settings argument required')
    def pinned_json(raw_path):
        path=Path(raw_path);require(path.is_absolute(),'Absolute pinned input path required')
        path=path.resolve(strict=True);expected=meta['pins'].get(str(path))
        require(isinstance(expected,str),'Comparison input is not pinned: '+str(path))
        return path,snapshot(path,expected)
    settings_path,settings=pinned_json(argv[locations[0]+1])
    require(settings.get('status')=='reviewed_for_execution','Settings are not reviewed')
    case_path,case=pinned_json(settings['case_spec']['path']);case_hash=watched[str(case_path)]
    require(settings['case_spec']['sha256']==case_hash and raw.get('case_spec_sha256')==case_hash,'Case binding mismatch')
    if 'case_spec_sha256' in observed:require(observed['case_spec_sha256']==case_hash,'Observation case mismatch')
    from prepare_case import properties
    from stage_driver import check_raw,check_execution_settings,check_mesh_geometry,check_solution_mesh_binding,resolve_export_for_settings
    require(settings['properties']==properties(case,settings['variant'],settings['mesh_level']),'Settings no longer match case')
    check_execution_settings(cfg,settings,case)
    require(raw.get('solution_mesh_tag')==settings['properties']['mesh_tag'],'Solution mesh differs from reviewed mesh')
    require(_same(settings['expected_positions'],cfg['expected_positions']),'Settings positions mismatch')
    input_path=Path(cfg['model']).resolve(strict=True);input_hash=meta['pins'].get(str(input_path))
    require(input_hash==_digest(input_path) and observed.get('input_model_sha256')==input_hash,'Input model binding mismatch')
    watched[str(input_path)]=input_hash
    source=Path(raw['source_mph']);require(source.is_absolute(),'Absolute source MPH path required');source=source.resolve(strict=True)
    source_hash=_digest(source);require(raw.get('source_sha256')==source_hash,'Readback source hash mismatch');watched[str(source)]=source_hash
    if cfg['operation']=='solve':
        require(any(Path(o['path'])==source and o['role']=='solved_model' and o['sha256']==source_hash for o in outputs.values()),'Source is not an accepted solved-model output')
    else:
        require(meta['pins'].get(str(source))==source_hash,'Export source is not pinned')
        manifest_path,manifest=pinned_json(cfg['manifest'])
        identity=resolve_export_for_settings(cfg,settings,source)
        for ref in identity['evidence']:
            ep=Path(ref['path']);ep=ep if ep.is_absolute() else manifest_path.parent/ep
            require(_digest(ep)==ref['sha256'],'Export evidence changed');watched[str(ep.resolve())]=ref['sha256']
    targets=set(cfg['target_names']);require(targets==set(raw['target_values']),'Raw target set mismatch')
    position={'kind':'stationary','solnum':raw['inner_solnum']};covered=set()
    for mapping in observed['solutions']:
        names=mapping.get('target_names',[]);require(names and set(names)<=targets,'Observation target mismatch')
        mapped_source=mapping.get('source',{});path=Path(mapped_source.get('path',''))
        path=path.resolve() if path.is_absolute() else inside(str(path))
        require(path==source and mapped_source.get('sha256')==source_hash,'Source differs between observation and readback')
        require(mapping.get('solution_tag')==raw['solution_tag'],'Solution differs between observation and readback')
        require(mapping.get('dataset_tag')==raw['dataset_tag'],'Dataset differs between observation and readback')
        require(type(mapping.get('solution_count')) is int and mapping['solution_count']==raw['solution_count']==1,'Solution count mismatch')
        require(_same(mapping.get('positions'),[position]),'Solution position mismatch')
        for name in names:require(_same(cfg['expected_positions'][name],[position]),'Target position mismatch')
        if cfg['operation']=='export':
            require(mapping.get('solution_id')==settings['solution_id']==raw['solution_tag']==settings['solution_tag'] and mapping.get('legacy_id')==settings['legacy_solution_id'],'Reviewed export solution mismatch')
            require(has_readback(mapping.get('selection_evidence')),'Export selection readback differs')
        covered.update(names)
    require(covered==targets,'Readback does not cover all accepted targets')
    check_raw(raw,source,{**settings,'solution_tag':raw['solution_tag']},meta)
    check_mesh_geometry(raw,vertices,elements,case['geometry']['audit_tolerance_m'])
    check_solution_mesh_binding(raw,vertices,elements,settings)
    result=_measure_data(root,raw,vertices,elements,{n:hashes[n] for n in ('solution-readback.json','mesh-vertices.json','mesh-elements.json')})
    result['provenance']={'run_id':meta['run_id'],'fingerprint':meta['fingerprint'],'operation':cfg['operation'],
        'execution_kind':'comsol','evidence_level':'runtime_observation','completion_evidence_accepted':True,
        'case':{'path':str(case_path),'sha256':case_hash},'settings':{'path':str(settings_path),'sha256':watched[str(settings_path)]},
        'input_model':{'path':str(input_path),'sha256':input_hash},'source':{'path':str(source),'sha256':source_hash},
        'solution':{'solution_tag':raw['solution_tag'],'inner_solnum':raw['inner_solnum'],'solution_count':raw['solution_count'],
                    'mesh_tag':raw['solution_mesh_tag']},
        'dataset':{'dataset_tag':raw['dataset_tag']},'output_bindings':outputs,
        'completion_evidence':{'path':str(evidence_path),'sha256':watched[str(evidence_path)]}}
    for path,digest in watched.items():require(_digest(path)==digest,'File changed during comparison: '+path)
    result['_watched']=watched
    result['_acceptance']=inspected
    return result


def compare_verified(first,second,runner):
    a=verify_run(first,runner);b=verify_run(second,runner)
    require(a['provenance']['input_model']['sha256']==b['provenance']['input_model']['sha256'],
            'Mesh pair must begin from the same unchanged input MPH')
    watched=[a.pop('_watched'),b.pop('_watched')]
    acceptances=[a.pop('_acceptance'),b.pop('_acceptance')]
    result=_compare_data(a,b)
    # A log or a reviewed dependency may have changed after initial inspection.
    # Reinspect the complete runner acceptance, not just files used in arithmetic.
    for directory,initial in zip((first,second),acceptances):
        final=runner.inspect(directory)
        require(final.get('completion_evidence_accepted') is True and final.get('evidence_level')=='runtime_observation'
                and _same(final,initial),'Run acceptance changed during comparison')
    # Recheck both snapshots after the second run was accepted and arithmetic
    # completed; never reload arbitrary neighboring files to compute metrics.
    for files in watched:
        for path,digest in files.items():require(_digest(path)==digest,'File changed during comparison: '+path)
    result.update(status='measured_comparison_only',evidence_level='runtime_observation',execution_kind='comsol')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--coarse',required=True);ap.add_argument('--fine',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--runner',required=True,help='Absolute path to this skill run_bundle.py; inspect only, never execute')
    a=ap.parse_args()
    from stage_driver import load_runner
    runner=load_runner(a.runner)
    write_new(a.out,compare_verified(a.coarse,a.fine,runner))
