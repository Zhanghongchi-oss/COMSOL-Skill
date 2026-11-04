"""Scoped transient saved-field restart adapter. Solve/restart or strictly read-only saved export; no authorization inference."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys

SHARED = Path(__file__).resolve().parents[2] / 'steady-slab/scripts'
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m);return m
helper=load('transient_shared_prepare',SHARED/'prepare_case.py')
old=sys.modules.get('prepare_case');sys.modules['prepare_case']=helper
try: shared=load('transient_shared_stage',SHARED/'stage_driver.py')
finally:
    if old is None:sys.modules.pop('prepare_case',None)
    else:sys.modules['prepare_case']=old
read,sha,write=helper.read,helper.sha,helper.write_new
need=shared.require
fixture=load('transient_fixture_contract',Path(__file__).with_name('prepare_case.py'))

def positions(times):
    return [{'kind':'time','value':t,'unit':'s'} for t in times]

def execute(bundle,settings_path,runner_path):
    runner=shared.load_runner(runner_path);root,cfg,meta=runner.load_bundle(bundle)
    start=read(root/'started.json');settings=read(settings_path)
    need(start['run_id']==meta['run_id'] and start['fingerprint']==meta['fingerprint'] and start['authorization'].strip(),'No current matching authorization')
    need(cfg['operation'] in ('solve','resume','export') and cfg['execution_kind']=='comsol','Unsupported operation')
    need(settings['operation']==cfg['operation'] and settings['status']=='reviewed_for_execution','Wrong settings operation/status')
    for path in [__file__,Path(__file__).with_name('prepare_case.py'),settings_path,runner_path,SHARED/'prepare_case.py',SHARED/'stage_driver.py',settings['class_file'],settings['batch_executable'],settings['resource_guard'],settings['preferences_template'],settings['case_spec']['path']]:
        need(meta['pins'].get(str(Path(path).resolve()))==sha(path),'Unpinned runtime input: '+str(path))
    need(cfg['parameters']==settings['parameters'] and cfg['solver_settings']==settings['solver_settings'],'Numerical settings mismatch')
    case=fixture.validate(read(settings['case_spec']['path']))
    fixture.validate_manifest_targets(read(cfg['manifest']),case,settings['kind'],cfg['operation'])
    need(cfg['parameters']==case['parameters'],'Fixture physical parameters differ')
    need(settings['properties']==fixture.properties(case,settings['kind'],settings['properties']['source_solution_tag']),'Actual phase properties differ from reviewed fixture')
    for key,value in case['numerics'].items():need(settings['properties'][key]==value,'Unsupported numeric fixture setting: '+key)
    source=Path(cfg['model']);original=sha(source)
    props={**settings['properties'],'operation':cfg['operation'],'input_mph':str(source),'input_sha256':original,
           'run_id':meta['run_id'],'fingerprint':meta['fingerprint'],'execution_authorized':'true','case_spec_sha256':settings['case_spec']['sha256'],
           'output_mph':str(root/'solved.mph'),'solve_metadata':str(root/'solve-metadata.json'),'raw_readback':str(root/'solution-readback.json'),
           'mesh_vertices':str(root/'mesh-vertices.json'),'mesh_elements':str(root/'mesh-elements.json')}
    if cfg['operation']=='resume':
        state=read(cfg['checkpoint'])['state']
        need(state==cfg['resume_expected'],'Checkpoint mismatch')
        need(state['solution_source']['sha256']==original and Path(state['solution_source']['path']).resolve()==source.resolve(),'Checkpoint carrier mismatch')
        need(state['solution_source']['solution_tag']==props['source_solution_tag'],'Checkpoint source solution mismatch')
        need(state['position']=={'time_s':float(props['start_time'])},'Checkpoint time mismatch')
    if cfg['operation']=='export':
        shared.resolve_export_for_settings(cfg,settings,source)
        props['solution_tag']=settings['solution_tag']
        job=shared.phase('export',root,settings,props,runner,cfg)
        saved=None
    else:
        job=shared.phase('solve',root,settings,props,runner,cfg)
        saved=read(root/'solve-metadata.json');source=root/'solved.mph'
        for k in ('run_id','fingerprint'):need(saved[k]==meta[k],'Solve identity mismatch')
        need(saved['job_properties_sha256']==sha(job) and saved['status']=='solve_saved_pending_independent_readback','Solve metadata mismatch')
        need(saved['source_sha256']==original and saved['output_sha256']==sha(source),'Source/output binding mismatch')
        need(positions(saved['times'])==cfg['expected_positions']['temperature_field'],'Saved actual times differ from requested positions')
        if cfg['operation']=='resume':
            need(saved['source_solution_tag']==props['source_solution_tag'] and saved['source_times'][-1]==float(props['start_time']),'Observed initial source mismatch')
            initial=saved['initialization']
            need({k:initial[k] for k in ('method','source','solnum','control')}=={'method':'sol','source':props['source_solution_tag'],'solnum':'last','control':'user'},'Observed initialization differs')
            need((initial['useinitsol_property_available'] is True and initial['useinitsol']=='on') or (initial['useinitsol_property_available'] is False and initial['useinitsol'] is None),'Missing property must not masquerade as on/off')
        props.update(input_mph=str(source),input_sha256=sha(source),solution_tag=saved['solution_tag'])
        job=shared.phase('readback',root,settings,props,runner,cfg)
    raw=read(root/'solution-readback.json')
    for k in ('run_id','fingerprint'):need(raw[k]==meta[k],'Readback identity mismatch')
    need(raw['status']=='independent_saved_solution_readback' and raw['mode']==('export' if cfg['operation']=='export' else 'readback'),'Wrong readback mode')
    need(raw['job_properties_sha256']==sha(job) and raw['source_sha256']==sha(source),'Readback source/job mismatch')
    need(Path(raw['source_mph']).resolve()==source.resolve() and raw['case_spec_sha256']==settings['case_spec']['sha256'],'Readback path/case mismatch')
    need(raw['solution_tag']==(settings['solution_tag'] if saved is None else saved['solution_tag']),'Actual saved solution mismatch')
    if saved is not None:need(raw['times']==saved['times'],'Actual saved times mismatch')
    need(raw['temperature_expression']=='T' and raw['temperature_unit']=='K' and raw['coordinate_unit']=='m','Export expression/unit mismatch')
    need(raw['dataset_solution_tag']==raw['solution_tag'],'Actual dataset binds a different solution')
    need(raw['inner_solnums']==list(range(1,len(raw['times'])+1)),'Actual time/solnum mapping mismatch')
    need(raw['dataset_tag']==props['dataset_tag'] and raw['dataset_persisted'] is False,'Dataset mapping/lifetime mismatch')
    xy=raw['sample_coordinates'];need(len(xy)==2 and all(len(row)==45 for row in xy),'Coordinate shape mismatch')
    expected_xy=[[.02*i/8 for j in range(5) for i in range(9)],[.01*j/4 for j in range(5) for i in range(9)]]
    need(xy==expected_xy,'Actual coordinates differ from scientific target')
    need(len(raw['temperature_K'])==len(raw['solution_vectors'])==len(raw['times'])==raw['solution_count'],'Incomplete time fields')
    need(all(len(row)==45 and all(type(v) in (int,float) and math.isfinite(v) for v in row) for row in raw['temperature_K']),'Invalid temperature readback')
    need(all(len(row)==raw['dofs'] and all(type(v) in (int,float) and math.isfinite(v) for v in row) for row in raw['solution_vectors']),'Invalid saved vector readback')
    need(raw['physical_initial_expression']=='T_base+T_amp*sin(pi*x/L)','Physical IC changed')
    if cfg['operation']=='resume':need(raw['saved_initialization']==saved['initialization'],'Saved initialization differs from actual execution')
    if saved is not None:need(raw['time_solver_rtol']==saved['time_solver_rtol'] and raw['time_solver_tlist']==saved['time_solver_tlist'],'Saved time solver differs')
    need(raw['mesh_vertices_sha256']==sha(root/'mesh-vertices.json') and raw['mesh_elements_sha256']==sha(root/'mesh-elements.json'),'Mesh evidence mismatch')
    shared.check_solution_mesh_binding(raw,read(root/'mesh-vertices.json'),read(root/'mesh-elements.json'),settings)
    need(sha(cfg['model'])==original,'Original source changed')
    pos={'temperature_field':positions(raw['times'])};need(pos==cfg['expected_positions'],'Actual target/time coverage mismatch')
    ref={'path':'solution-readback.json','sha256':sha(root/'solution-readback.json')}
    observation={'schema_version':'2.0.0','run_id':meta['run_id'],'fingerprint':meta['fingerprint'],'operation':cfg['operation'],
        'input_model_sha256':original,'solver_status':'existing_solution_available' if cfg['operation']=='export' else 'completed','completed_positions':pos,
        'observation':{'method':'saved_solution_readback','detail':'Separate COMSOL process reads saved actual getPVals/getU and T at explicit solnum; unchanged-mesh saved-field restart only, no integrator-history restoration.','evidence':[ref]},
        'solutions':[{'target_names':['temperature_field'],'solution_tag':raw['solution_tag'],'dataset_tag':raw['dataset_tag'],'solution_count':len(raw['times']),
            'available_solution_count':len(raw['times']),'positions':pos['temperature_field'],'source':{'path':str(source),'sha256':sha(source)}}]}
    if cfg['operation']=='export':
        need(settings['solution_id']==raw['solution_tag'],'Actual existing solution id differs')
        observation['solutions'][0].update(solution_id=settings['solution_id'],legacy_id=settings['legacy_solution_id'],selection_evidence=[ref])
    write(root/'solver-observation.json',observation)
    hashes={o['path']:sha(runner.inside(root,o['path'])) for o in cfg['outputs']}
    runner.validate_solver_observation(root,cfg,meta,start['started_ns'],hashes)
    write(root/cfg['evidence'],{'run_id':meta['run_id'],'fingerprint':meta['fingerprint'],'operation':cfg['operation'],'status':'completed','completed_positions':pos,'output_hashes':hashes})

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',required=True);ap.add_argument('--settings',required=True);ap.add_argument('--runner',required=True);a=ap.parse_args()
    try:execute(a.bundle,a.settings,a.runner)
    except Exception as exc:print('Transient adapter failure: '+str(exc),file=sys.stderr);raise SystemExit(2)
