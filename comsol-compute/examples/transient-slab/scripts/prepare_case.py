"""Exact fixture semantics, pure plan preparation. No native process launch."""
import argparse,hashlib,json
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def need(ok,msg):
    if not ok:raise ValueError(msg)
def scientific(case):
    return {'case_id':case['case_id'],'parameters':case['parameters'],'targets':case['target_outputs_by_kind'],'numerics':case['numerics']}
def validate(case):
    expected=read(Path(__file__).resolve().parents[1]/'case-spec.json')
    # Shipped contract is also fixed by semantic digest below; editing it is a new adapter review.
    digest=hashlib.sha256(json.dumps(scientific(expected),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    need(digest==SEMANTIC_SHA256,'Shipped fixture semantics changed; adapter review required')
    need(scientific(case)==scientific(expected),'Unsupported fixture semantics')
    return case
def validate_manifest_targets(manifest,case,kind,operation="solve"):
    need(operation in ("solve","resume","export"),"Unsupported operation")
    validate(case);need(kind in ('full','half','resume'),'Unsupported transient interval')
    targets=manifest['target_outputs'];need(len(targets)==1,'Exactly one temperature target supported')
    actual=targets[0];expected=case['target_outputs_by_kind'][kind]
    need(actual['name']==expected['name'] and actual['status']=='complete','Wrong/incomplete target')
    for key in ('expression','unit','coordinate_system','statistic','time','frequency','parameters','mode'):
        need(actual[key]['status']==expected[key]['status'] and actual[key]['value']==expected[key]['value'],'Unsupported target '+key)
    need(actual['selection_ref']==expected['selection_ref'],'Unsupported target selection')
    required=actual['required_solution']
    need(required['status']=='complete' and required['kind']==('existing' if operation=='export' else 'planned'),'Wrong requested solution kind for operation')
    if operation=='export':need(isinstance(required.get('id'),str) and bool(required['id'].strip()),'Explicit existing logical solution id required')
    return True

def properties(case,kind,source_solution_tag=''):
    validate(case);need(kind in ('full','half','resume'),'Unknown interval')
    start=.5 if kind=='resume' else 0.;end=.5 if kind=='half' else 1.
    times=[round(start+i*.1,1) for i in range(round((end-start)/.1)+1)]
    need((bool(source_solution_tag) if kind=='resume' else source_solution_tag==''),'Explicit source tag required only for resume')
    p={'component':'comp1','geometry':'geom1','physics':'ht','physics_type':'HeatTransfer','material':'mat1','temperature_left':'temp_left','temperature_right':'temp_right','insulation':'ins1',
       'mesh_tag':'mesh_cc','study_tag':'std_resume' if kind=='resume' else 'std_cc','dataset_tag':'ds_cc_read',**case['numerics'],
       'tlist':' '.join(map(str,times)),'start_time':str(start),'source_solution_tag':source_solution_tag}
    p.update({'expected.'+k:v for k,v in case['parameters'].items()})
    p.update({'selection.'+k:v for k,v in {'domain':'dom_slab','left':'bnd_left','right':'bnd_right','top':'bnd_top','bottom':'bnd_bottom','insulated':'bnd_insulated'}.items()})
    return p

SEMANTIC_SHA256 = '7ba5ed97a4f0d894d3b841062102ce3a0693ba62526dbb532ce6f83d8b4f88f3'

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--case',required=True,type=Path);ap.add_argument('--out',required=True,type=Path);a=ap.parse_args();case=validate(read(a.case));a.out.mkdir(parents=True,exist_ok=False)
    for kind in ('full','half','resume'):
        with (a.out/(kind+'-plan.json')).open('x',encoding='utf-8') as f:json.dump({'status':'plan_prepared_not_executable','authorization_granted':False,'case':{'path':str(a.case.resolve()),'sha256':sha(a.case)},'kind':kind,'targets':[case['target_outputs_by_kind'][kind]],'required_inputs':['inspected model and manifest','current authorization','reviewed numerical configuration','compiled adapter','source solution and checkpoint for resume']},f,ensure_ascii=False,indent=2)
