"""Future authorized runner child. Never compile; solve then independent reload, or export only."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from prepare_case import read, sha, write_new, properties, execution_settings, resolve_export_identity, runtime_layout, phase_logs, phase_outputs


def require(condition, message):
    if not condition: raise ValueError(message)


def load_runner(path):
    spec=importlib.util.spec_from_file_location('slab_runner',path)
    module=importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(),str(path),'exec'),module.__dict__)
    return module


def check_execution_settings(cfg, settings, case):
    expected=execution_settings(case,settings['variant'],settings['mesh_level'])
    for key,value in expected.items():
        require(json.dumps(cfg[key],sort_keys=True,allow_nan=False)==json.dumps(value,sort_keys=True,allow_nan=False),
                'Reviewed '+key+' differs from actual case/mesh settings')


def check_solver_discovery(observed, settings):
    discovery=observed['solver_discovery'];study=settings['properties']['study_tag']
    require(isinstance(discovery.get('filtered'),list) and isinstance(discovery.get('all_related'),list),'Missing original solver discovery observations')
    tags=discovery['actual_tags'];owners=discovery['owning_studies']
    require(isinstance(tags,list) and len(tags)==len(set(tags)) and set(owners)==set(tags),'Ambiguous actual solver enumeration')
    candidates=[tag for tag in tags if owners[tag]==study]
    require(len(tags)==len(candidates)==1 and candidates[0]==observed['solution_tag'] and observed['study_tag']==study,'Unsupported/ambiguous actual owning-study solver')


def check_solution_mesh_binding(raw,vertices,elements,settings):
    """Independently compare saved sequence with actual solution FE corner cells."""
    from collections import Counter
    b=raw['solution_mesh_binding'];p=settings['properties']
    require(b.get('scope')=='slab_2d_straight_triangle_corners_only','Unsupported mesh correspondence scope')
    for key in ('run_id','fingerprint','case_spec_sha256','source_sha256'):
        require(b.get(key)==raw.get(key) and isinstance(raw.get(key),str) and bool(raw[key]),'Mesh proof identity mismatch: '+key)
    require(b['study_tag']==p['study_tag'],'Mesh proof study mismatch')
    require(b['method']=='exact_triangle_corner_coordinate_multiset','Unsupported solution mesh identity method')
    require(b['solution_tag']==raw['solution_tag'] and b['geometry_tag']==p['geometry'],'Solution mesh identity mismatch')
    require(b['sequence_tag']==b['study_mesh_tag']==raw['solution_mesh_tag']==p['mesh_tag'],'Sequence/study mesh mismatch')
    require(b['get_mesh_returned'] in ('',b['sequence_tag']),'Getter contradicts proven mesh')
    require(b['solution_geometry_tags']==[p['geometry']] and b['mesh_cases']==['main'],'Unexpected solution mesh geometry/cases')
    local=b['triangle_local_coordinates'];tri=b['triangle_node_indices'];nodes=b['node_coordinates']
    require(len(local)==2 and len(local[0])==len(local[1])==len(tri) and len(tri) in (3,6),'Unsupported local triangle layout')
    require(len({tuple(x) for x in zip(*local)})==len(tri),'Duplicate local nodes')
    require(set(zip(*local))==({(0,0),(1,0),(0,1)} if len(tri)==3 else {(0,0),(1,0),(0,1),(0.5,0),(0,0.5),(0.5,0.5)}),'Unsupported higher-order layout')
    corners=[]
    for xy in ((0,0),(1,0),(0,1)):
        matches=[i for i,v in enumerate(zip(*local)) if v==xy]
        require(len(matches)==1,'Missing/duplicate actual reference corner');corners.append(matches[0])
    require(corners==b['corner_rows'],'Reported corner row mapping differs from actual local coordinates')
    def cells(coords,conn):
        require(len(coords)==2 and len(coords[0])==len(coords[1])>0 and len(conn)==3,'Invalid triangle arrays')
        require(all(len(row)==len(conn[0]) for row in conn),'Ragged triangles')
        result=[]
        for inds in zip(*conn):
            require(all(type(i) is int and 0<=i<len(coords[0]) for i in inds),'Invalid actual node index')
            points=tuple(sorted((coords[0][i],coords[1][i]) for i in inds))
            require(len(set(points))==3 and all(math.isfinite(x) for xy in points for x in xy),'Invalid triangle corner coordinates')
            result.append(points)
        return Counter(result)
    actual=cells(nodes,[tri[i] for i in corners])
    require(all(len(row)==len(tri[0]) for row in tri),'Ragged FE cells')
    for e in range(len(tri[0])):
        for r,(x,y) in enumerate(zip(*local)):
            ni=tri[r][e];require(type(ni) is int and 0<=ni<len(nodes[0]),'Invalid FE node index')
            for d in (0,1):
                expected=(1-x-y)*nodes[d][tri[corners[0]][e]]+x*nodes[d][tri[corners[1]][e]]+y*nodes[d][tri[corners[2]][e]]
                require(nodes[d][ni]==expected,'Non-affine FE nodes unsupported by corner proof')
    sequence=cells(vertices['coordinate_rows'],elements['types']['tri']['connectivity_rows'])
    require(actual and actual==sequence,'Actual solution FE triangles differ from saved sequence')
    require(sum(actual.values())==b['matched_triangles'],'Matched element count mismatch')


def write_properties(path, values):
    def esc(v):
        v=str(v);require('\n' not in v and '\r' not in v,'Newlines not supported in properties')
        return v.replace('\\','\\\\').replace('=','\\=').replace(':','\\:').replace(' ','\\ ')
    with Path(path).open('x',encoding='utf-8',newline='\n') as out:
        for key,value in sorted(values.items()):out.write(esc(key)+'='+esc(value)+'\n')


def check_raw(raw, source, settings, meta):
    require(raw['run_id']==meta['run_id'] and raw['fingerprint']==meta['fingerprint'],'Readback identity mismatch')
    require(raw['case_spec_sha256']==settings['case_spec']['sha256'],'Readback case mismatch')
    require(Path(raw['source_mph']).resolve()==Path(source).resolve() and raw['source_sha256']==sha(source),'Readback source mismatch')
    require(raw['solver_type']=='Stationary' and type(raw['solution_count']) is int and raw['solution_count']==1,'Not one existing stationary solution')
    require(type(raw['inner_solnum']) is int and raw['inner_solnum']==1,'Unexpected observed position')
    require(raw['solution_tag']==settings['solution_tag'],'Readback solution differs from requested existing tag')
    require(raw['dataset_tag']==settings['properties']['dataset_tag'],'Readback dataset mismatch')
    coords=raw['sample_coordinates']; require(len(coords)==2 and len(coords[0])==len(coords[1])>0,'Coordinate shape')
    targets=raw['target_values'];require(set(targets)==set(settings['expected_positions']),'Missing target')
    temp=targets['temperature_field'];flux=targets['conductive_heat_flux'];q=targets['through_heat_rate']
    n=len(coords[0]);require(len(temp['values'])==n and len(flux['values'])==2 and all(len(x)==n for x in flux['values']),'Target sample shape')
    pairs=[('temperature',temp),('heat_rate',q)]
    for key,t in pairs:
        require(t['expression']==settings['properties']['target.'+key+'.expression'] and t['unit']==settings['properties']['target.'+key+'.unit'],'Target expression/unit mismatch')
    require(flux['expressions']==[settings['properties']['target.flux_x.expression'],settings['properties']['target.flux_y.expression']] and flux['unit']==settings['properties']['target.flux_x.unit'],'Flux definition mismatch')
    values=coords[0]+coords[1]+temp['values']+flux['values'][0]+flux['values'][1]+[q['value']]
    require(all(type(x) in (int,float) and math.isfinite(x) for x in values),'Nonfinite/non-numeric output')
    domain_quality(raw)
    require(raw['mesh']['num_tri']>0 and raw['mesh']['num_vertices']>0,'Missing actual mesh')


def check_mesh_geometry(raw, vertices, elements, tolerance):
    require(vertices['coordinate_unit']=='m' and elements['index_base']==0,'Unverified mesh units/indices')
    xy=vertices['coordinate_rows'];require(len(xy)==2 and len(xy[0])==len(xy[1]),'Mesh coordinate shape')
    L=raw['parameters_si']['L'];H=raw['parameters_si']['H'];selections=raw['selection_entities']
    edge=elements['types']['edg'];rows=edge['connectivity_rows'];entities=edge['entity_ids']
    require(len(rows)==2 and len(rows[0])==len(rows[1])==len(entities),'Boundary edge mapping shape')
    for name,axis,expected in [('left',0,0),('right',0,L),('bottom',1,0),('top',1,H)]:
        selected=[i for i,e in enumerate(entities) if e in selections[name]]
        require(selected,'No mesh edges for named boundary '+name)
        for i in selected:
            for row in rows:
                v=row[i];require(type(v) is int and 0<=v<len(xy[0]),'Boundary vertex index')
                require(abs(xy[axis][v]-expected)<=tolerance,'Mesh boundary coordinate mismatch: '+name)
    tri=elements['types']['tri']
    require(tri['entity_ids'] and all(e in selections['domain'] for e in tri['entity_ids']),'Mesh domain/entity mismatch')


def domain_quality(raw):
    """Consume explicitly read domain statistics; reject relabeled boundary data."""
    mesh=raw['mesh'];domain=mesh['local_selection_stats']['domain']
    require(mesh.get('entity_dimension')==2 and domain.get('entity_dimension')==2,'Domain statistics dimension absent or wrong')
    require(domain['num_elements']==mesh['num_tri'],'Domain statistic count differs from actual triangles')
    for key in ('min_quality','mean_quality'):
        require(type(domain[key]) in (int,float) and math.isfinite(domain[key]),'Nonfinite domain quality')
        require(mesh[key]==domain[key],'All-domain quality differs from named domain')
    require(mesh['quality_measure']==domain['quality_measure'],'Domain quality measure differs')
    for name,stats in mesh['local_selection_stats'].items():
        require(stats.get('entity_dimension')==(2 if name=='domain' else 1),'Local statistics dimension mismatch')
    return {k:domain[k] for k in ('min_quality','mean_quality','quality_measure','entity_dimension')}


def resolve_export_for_settings(cfg, settings, source):
    identity=resolve_export_identity(cfg['manifest'],settings.get('legacy_solution_id'),source,cfg['target_names'])
    for key in ('legacy_solution_id','solution_id','solution_tag'):
        require(settings.get(key)==identity[key],'Reviewed export identity mismatch: '+key)
    require(settings.get('export_identity')==identity,'Reviewed export identity/evidence changed')
    return identity


def stage_budget(settings):
    b=settings.get('stage_resources',{})
    require(type(b.get('cores')) is int and b['cores']>0,'Explicit positive CPU core budget required')
    require(type(b.get('memory_mib')) is int and b['memory_mib']>0,'Explicit positive memory budget required')
    require(type(b.get('timeout_seconds')) in (int,float) and math.isfinite(b['timeout_seconds']) and b['timeout_seconds']>0,'Explicit finite timeout required')
    return b


def validate_resource_record(record, stage, argv, cwd, budget, started_ns):
    require(record.get('stage')==stage and record.get('argv')==argv and Path(record.get('cwd','')).resolve()==Path(cwd).resolve(),'Resource stage/input binding mismatch')
    require(record.get('status')=='exited' and type(record.get('exit_code')) is int and record['exit_code']==0 and not record.get('error'),'Resource guard did not finish successfully')
    require(type(record.get('remaining_owned_processes')) is int and record['remaining_owned_processes']==0,'Owned process cleanup not established')
    require(record.get('memory_limit_bytes')==budget['memory_mib']*1024**2 and record.get('timeout_seconds')==budget['timeout_seconds'],'Resource budget mismatch')
    mask=record.get('affinity_mask');require(type(mask) is int and mask>0 and mask.bit_count()==budget['cores'],'Resource CPU affinity mismatch')
    start=record.get('started_ns');end=record.get('finished_ns')
    require(type(start) is int and type(end) is int and started_ns<=start<=end,'Resource record missing/stale time binding')


def prepare_runtime_paths(root, mode, policy):
    """An explicit Python path probe, NOT evidence that native COMSOL I/O works."""
    root=Path(root).resolve(strict=True)
    report={'mode':mode,'status':'rejected','native_comsol_probe':'not_run',
            'proof_limit':'Python create/read/delete and reviewed length budget only; native suffix length is an estimate',
            'policy':policy,'paths':{},'probes':[],'cleanup_scope':[]}
    record_path=root/(mode+'-path-preflight.json')
    try:
        require(isinstance(policy,dict) and set(policy)=={'layout','max_path_utf16_units','reserved_native_suffix_utf16_units','review_basis'},'Explicit reviewed runtime path policy required')
        require(policy['layout']=='bundle_private_compact_v1','Unsupported private runtime layout')
        maximum=policy['max_path_utf16_units'];reserve=policy['reserved_native_suffix_utf16_units']
        require(type(maximum) is int and type(reserve) is int and 16<=reserve<maximum,'Explicit path length budget and native suffix reserve required')
        require(isinstance(policy['review_basis'],str) and policy['review_basis'].strip(),'Path budget review basis required')
        layout=runtime_layout(mode)
        paths={key:(root/relative).resolve() for key,relative in layout.items()}
        for key,path in paths.items():
            require(path.is_relative_to(root) and path!=root,'Runtime path escaped run root')
            units=len(str(path).encode('utf-16-le'))//2
            report['paths'][key]={'relative':layout[key],'actual':str(path),'utf16_units':units,
                                  'with_reserved_native_suffix':units+1+reserve}
            require(units+1+reserve<=maximum,'Runtime path budget exceeded: '+key+'; prepare a new bundle under an approved shorter task root')
        phase_root=paths['launch'].parent
        require(not phase_root.exists(),'Runtime phase directory already exists; new run required')
        phase_root.parent.mkdir(exist_ok=True)
        phase_root.mkdir()
        report['cleanup_scope']=[str(phase_root)]
        for key,path in paths.items():
            path.mkdir()
            # Exercise a nested suffix of exactly the reviewed UTF-16 length.
            parts=[];left=reserve
            while left>180:parts.append('d'*100);left-=101
            parts.append('p'*left)
            probe=path.joinpath(*parts);created=[]
            probe_record={'path':str(probe),'status':'planned','cleanup_status':'not_attempted',
                          'utf16_units':len(str(probe).encode('utf-16-le'))//2}
            report['probes'].append(probe_record)
            try:
                parent=path
                for part in parts[:-1]:
                    parent=parent/part;parent.mkdir();created.append(parent)
                with probe.open('xb') as stream:stream.write(b'PRIVATE PATH PROBE ONLY');stream.flush();os.fsync(stream.fileno())
                require(probe.read_bytes()==b'PRIVATE PATH PROBE ONLY','Path probe readback failed')
                probe_record.update(sha256=sha(probe),status='created_read_pending_cleanup')
            except Exception as exc:
                probe_record.update(status='probe_failed',probe_error={'type':type(exc).__name__,'message':str(exc)})
                raise
            finally:
                try:
                    require(probe.resolve().is_relative_to(phase_root),'Probe cleanup escaped owned phase')
                    if probe.exists():probe.unlink()
                    for directory in reversed(created):directory.rmdir()
                    probe_record['cleanup_status']='completed'
                    if probe_record['status']=='created_read_pending_cleanup':probe_record['status']='created_read_deleted'
                except Exception as exc:
                    probe_record.update(cleanup_status='failed',cleanup_error={'type':type(exc).__name__,'message':str(exc)})
                    raise
        report['status']='python_path_probe_passed_not_native_validation'
        write_new(record_path,report)
        return paths
    except Exception as exc:
        report['error']={'type':type(exc).__name__,'message':str(exc)}
        write_new(record_path,report)
        raise


def check_phase_log_policy(runner,cfg,settings):
    """Compare the exact reviewed policies; do not silently select a fallback."""
    keys=('log_encoding','log_encodings')
    require({k:cfg[k] for k in keys if k in cfg}=={k:settings[k] for k in keys if k in settings},'Settings and run-config log policies differ')
    return runner.validate_log_policy(cfg)


def phase(mode, root, settings, props, runner, cfg):
    root=Path(root).resolve(strict=True)
    required_logs=phase_logs(mode)
    declared={x['path']:x['role'] for x in cfg['outputs']}
    require(all(declared.get(x['path'])==x['role'] for x in phase_outputs(mode)),'Declare phase diagnostic/path/input artifacts with correct roles')
    require(set(required_logs)<=set(cfg['logs']),'Declare all native and guard logs before execution')
    check_phase_log_policy(runner,cfg,settings)
    paths=prepare_runtime_paths(root,mode,settings.get('runtime_path_policy'))
    path=root/(mode+'-job.properties');write_properties(path,{**props,'mode':mode});job_hash=sha(path)
    env=os.environ.copy();env.pop('COMSOL_COMPUTE_JOB',None)
    launch=paths['launch'];launch_job=launch/'job.properties';shutil.copyfile(path,launch_job)
    require(sha(launch_job)==job_hash,'Per-phase job copy mismatch')
    preferences=Path(settings['preferences_template']);preferences_sha=sha(preferences)
    shutil.copyfile(preferences,paths['prefs']/'comsol.prefs')
    require(sha(paths['prefs']/'comsol.prefs')==preferences_sha,'Private preference copy mismatch')
    budget=stage_budget(settings)
    argv=[settings['batch_executable'],'-migrateprefs','off','-np',str(budget['cores']),'-tmpdir',str(paths['tmp']),
          '-recoverydir',str(paths['recovery']),'-prefsdir',str(paths['prefs']),
          '-configuration',str(paths['configuration']),'-data',str(paths['workspace']),'-inputfile',settings['class_file'],
          '-nosave','-batchlog',str(root/(mode+'-batch.log'))]
    guard=Path(settings['resource_guard']);stage='compute-'+props['run_id']+'-'+mode
    guarded=[sys.executable,'-X','utf8','-B',str(guard),'--name',stage,
             '--runner',str(Path(runner.__file__).resolve()),'--run-root',str(root),
             '--timeout',str(budget['timeout_seconds']),'--cores',str(budget['cores']),
             '--memory-mb',str(budget['memory_mib']),'--cwd',str(launch),'--',*argv]
    phase_started_ns=time.time_ns();code=None;errors=[]
    try:
        with (root/(mode+'-guard.stdout.log')).open('xb') as stdout,(root/(mode+'-guard.stderr.log')).open('xb') as stderr:
            result=subprocess.run(guarded,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,check=False)
            code=result.returncode
    except Exception as exc:errors.append({'stage':'guard_launch','type':type(exc).__name__,'message':str(exc)})
    resources=root/'resource-records'
    for stream in ('stdout','stderr'):
        source=resources/(stage+'.'+stream+'.log')
        try:
            if source.is_file():shutil.copyfile(source,root/(mode+'-'+stream+'.log'))
        except Exception as exc:errors.append({'stage':'raw_log_copy','source':str(source),'type':type(exc).__name__,'message':str(exc)})
    # Scan every source BEFORE checking exit status or the resource receipt.
    # No decoder failure may suppress a native error in another source.
    scans=runner.scan_logs(root,cfg,required_logs)
    resource_record=resources/(stage+'.json')
    try:
        require(resource_record.is_file() and resource_record.stat().st_size>0,'Missing resource evidence')
        resource=read(resource_record)
        shutil.copyfile(resource_record,root/(mode+'-resource.json'))
        validate_resource_record(resource,stage,argv,launch,budget,phase_started_ns)
    except Exception as exc:errors.append({'stage':'resource_evidence','type':type(exc).__name__,'message':str(exc)})
    if code!=0:errors.append({'stage':'guard_exit','exit_code':code,'message':'Phase guard did not exit successfully'})
    for target,expected,label in ((launch_job,job_hash,'phase job copy'),(path,job_hash,'phase job'),(preferences,preferences_sha,'preference template')):
        try:require(sha(target)==expected,label+' changed during execution')
        except Exception as exc:errors.append({'stage':'input_integrity','type':type(exc).__name__,'message':str(exc)})
    bad_logs=[x for x in scans if x['status']!='scanned' or x['findings'] or x.get('raw_ascii_indicators')]
    diagnosis={'mode':mode,'run_id':props['run_id'],'fingerprint':props['fingerprint'],'native_exit_success_is_not_completion':True,
               'log_policy':check_phase_log_policy(runner,cfg,settings),'logs':scans,'errors':errors,
               'status':'rejected' if errors or bad_logs else 'phase_process_and_logs_checked_not_solution_acceptance'}
    write_new(root/(mode+'-diagnostics.json'),diagnosis)
    write_new(root/(mode+'-process.json'),{'argv':argv,'guard_argv':guarded,'exit_code':code,'job_sha256':job_hash,
        'job_copy':str(launch_job),'preferences_template_sha256':preferences_sha,'mode':mode,
        'diagnostics_sha256':sha(root/(mode+'-diagnostics.json')),'runtime_path_preflight_sha256':sha(root/(mode+'-path-preflight.json'))})
    require(not errors and not bad_logs,'Phase rejected; native/log/reading diagnostics preserved in '+mode+'-diagnostics.json')
    return path


def execute(bundle, settings_path, runner_path):
    runner=load_runner(runner_path);root,cfg,meta=runner.load_bundle(bundle)
    start=read(root/'started.json')
    require(start['run_id']==meta['run_id'] and start['fingerprint']==meta['fingerprint'],'No matching authorized runner start')
    require(isinstance(start.get('authorization'),str) and start['authorization'].strip(),'No separately recorded execution authorization')
    require(cfg['execution_kind']=='comsol' and cfg['operation'] in ('solve','export'),'Unsupported operation')
    settings=read(settings_path)
    require(settings['status']=='reviewed_for_execution','Preparation remains pending')
    for path in (settings_path,runner_path,__file__,Path(__file__).with_name('prepare_case.py'),settings['class_file'],settings['batch_executable'],settings['case_spec']['path'],settings['resource_guard'],settings['authorization_file'],settings['preferences_template']):
        require(meta['pins'].get(str(Path(path).resolve()))==sha(path),'Unpinned runtime input: '+str(path))
    case=read(settings['case_spec']['path']);require(sha(settings['case_spec']['path'])==settings['case_spec']['sha256'],'Case changed')
    require(settings['properties']==properties(case,settings['variant'],settings['mesh_level']),'Case/numerical properties changed without preparation')
    check_execution_settings(cfg,settings,case)
    require(cfg['expected_positions']==settings['expected_positions'],'Runner position plan differs')
    # Exact policy is checked after source resolution and before any phase launch.
    source=Path(cfg['model']).resolve()
    original_source_hash=sha(source)
    if cfg['operation']=='export':resolve_export_for_settings(cfg,settings,source)
    stage_budget(settings)
    check_phase_log_policy(runner,cfg,settings)
    props={**settings['properties'],'input_mph':str(source),'run_id':meta['run_id'],'fingerprint':meta['fingerprint'],
           'execution_authorized':'true','input_sha256':original_source_hash,
           'case_spec_sha256':settings['case_spec']['sha256'],'output_mph':str(root/'solved.mph'),
           'solve_metadata':str(root/'solve-metadata.json'),'raw_readback':str(root/'solution-readback.json'),
           'mesh_vertices':str(root/'mesh-vertices.json'),'mesh_elements':str(root/'mesh-elements.json')}
    if cfg['operation']=='solve':
        solve_job=phase('solve',root,settings,props,runner,cfg)
        observed=read(root/'solve-metadata.json');source=root/'solved.mph'
        require(observed['run_id']==meta['run_id'] and observed['fingerprint']==meta['fingerprint'] and observed['case_spec_sha256']==settings['case_spec']['sha256'],'Solve metadata identity mismatch')
        require(observed['job_properties_sha256']==sha(solve_job) and observed['status']=='solve_saved_pending_independent_readback','Solve metadata phase mismatch')
        require(Path(observed['output_mph']).resolve()==source and observed['output_sha256']==sha(source),'Solved output binding')
        require(observed['source_sha256']==meta['pins'][cfg['model']],'Solve input binding')
        check_solver_discovery(observed,settings)
        settings={**settings,'solution_tag':observed['solution_tag']}
        props.update(input_mph=str(source),input_sha256=observed['output_sha256'],solution_tag=observed['solution_tag'])
        job=phase('readback',root,settings,props,runner,cfg)  # fresh COMSOL process reloads saved MPH
    else:
        require(isinstance(settings['solution_tag'],str) and settings['solution_tag'],'Export requires known existing solution')
        require(isinstance(settings['legacy_solution_id'],str) and settings['legacy_solution_id'],'Export requires reviewed legacy id')
        props['solution_tag']=settings['solution_tag']
        job=phase('export',root,settings,props,runner,cfg)  # no fallback to solve
    require(sha(Path(cfg['model']).resolve())==original_source_hash,'Input/source MPH changed during operation')
    raw=read(root/'solution-readback.json');check_raw(raw,source,settings,meta)
    require(raw['status']=='independent_saved_solution_readback' and raw['mode']==('readback' if cfg['operation']=='solve' else 'export'),'Readback phase/status mismatch')
    require(raw['job_properties_sha256']==sha(job),'Readback job mismatch')
    require(raw['mesh_vertices_sha256']==sha(root/'mesh-vertices.json') and raw['mesh_elements_sha256']==sha(root/'mesh-elements.json'),'Mesh/readback binding mismatch')
    vertices=read(root/'mesh-vertices.json');elements=read(root/'mesh-elements.json')
    check_mesh_geometry(raw,vertices,elements,case['geometry']['audit_tolerance_m'])
    check_solution_mesh_binding(raw,vertices,elements,settings)
    observed_positions={n:[{'kind':'stationary','solnum':raw['inner_solnum']}] for n in raw['target_values']}
    require(observed_positions==cfg['expected_positions'],'Observed position coverage mismatch')
    ref={'path':'solution-readback.json','sha256':sha(root/'solution-readback.json')}
    mapping={'target_names':list(raw['target_values']),'solution_tag':raw['solution_tag'],'dataset_tag':raw['dataset_tag'],
             'solution_count':raw['solution_count'],'available_solution_count':raw['solution_count'],
             'positions':[{'kind':'stationary','solnum':raw['inner_solnum']}],
             'source':{'path':str(source),'sha256':raw['source_sha256']}}
    if cfg['operation']=='export':
        require(settings['solution_id']==raw['solution_tag'],'Reviewed actual solution id does not match this case readback')
        mapping.update(solution_id=settings['solution_id'],legacy_id=settings['legacy_solution_id'],selection_evidence=[ref])
    observation={'schema_version':'2.0.0','run_id':meta['run_id'],'fingerprint':meta['fingerprint'],'operation':cfg['operation'],
                 'input_model_sha256':meta['pins'][cfg['model']],
                 'solver_status':'completed' if cfg['operation']=='solve' else 'existing_solution_available',
                 'completed_positions':observed_positions,'observation':{'method':'saved_solution_readback',
                 'detail':'Separate batch class process loaded the saved MPH and queried stationary solution and numerical results.',
                 'evidence':[ref]},'solutions':[mapping]}
    write_new(root/'solver-observation.json',observation)
    hashes={o['path']:sha(runner.inside(root,o['path'])) for o in cfg['outputs']}
    runner.validate_solver_observation(root,cfg,meta,start['started_ns'],hashes)
    write_new(root/cfg['evidence'],{'run_id':meta['run_id'],'fingerprint':meta['fingerprint'],'operation':cfg['operation'],
              'status':'completed','completed_positions':observed_positions,'output_hashes':hashes})


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--bundle',required=True);ap.add_argument('--settings',required=True);ap.add_argument('--runner',required=True)
    a=ap.parse_args()
    try:execute(a.bundle,a.settings,a.runner)
    except Exception as exc:
        print('Adapter failure: '+str(exc),file=sys.stderr);raise SystemExit(2)
