"""Prepare this fixture only. No process launch, model fabrication, or authorization."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")


def resolve_export_identity(manifest_path, legacy_id, source, target_names):
    """Fixture-only selector AFTER public review; never manufactures an existing solution.

    Logical registry id and actual solution id remain distinct. This minimal
    adapter supports actual solution_id == solver tag, otherwise stops explicitly.
    The generating parent is not consulted as the saved solution carrier.
    """
    manifest_path=Path(manifest_path).resolve(strict=True);data=read(manifest_path)
    def need(ok,msg):
        if not ok: raise ValueError(msg)
    def path_of(value):
        path=Path(value)
        return (path if path.is_absolute() else manifest_path.parent/path).resolve(strict=True)
    source=Path(source).resolve(strict=True);digest=sha(source)
    need(data.get('schema_version')=='2.0.0','Explicit v2 manifest required')
    need(path_of(data['model']['path'])==source and data['model']['sha256']==digest,'Wrong actual solution carrier')
    records=[x for x in data['legacy']['solutions'] if x['id']==legacy_id]
    need(len(records)==1,'Required legacy record missing or duplicated')
    record=records[0]
    need(record.get('validity')=='valid','Existing solution has not been reviewed valid')
    actual=record.get('solution_id');tag=record.get('tag')
    need(isinstance(actual,str) and actual.strip() and isinstance(tag,str) and tag.strip(),'Missing actual solution identity')
    need(actual==tag,'This slab adapter supports solution_id equal to solver tag only; review another adapter')
    need(record['applies_to']['model_sha256']==digest and record['applies_to']['source_model_sha256']==digest,'Wrong saved solution source hash')
    evidence=record.get('evidence');need(isinstance(evidence,list) and evidence,'Missing solution evidence')
    for ref in evidence:need(sha(path_of(ref['path']))==ref['sha256'],'Solution evidence hash mismatch')
    for name in target_names:
        matches=[t for t in data['target_outputs'] if t['name']==name]
        need(len(matches)==1,'Target missing or duplicate')
        required=matches[0]['required_solution']
        need(required.get('status')=='complete' and required.get('kind')=='existing' and required.get('id')==legacy_id,'Target does not request this logical existing solution')
    return {'legacy_solution_id':legacy_id,'solution_id':actual,'solution_tag':tag,
            'source':{'path':str(source),'sha256':digest},
            'manifest':{'path':str(manifest_path),'sha256':sha(manifest_path)},'evidence':evidence}


def validate_target_outputs(case):
    """Validate the exact scientific definitions implemented by this adapter.

    Java samples T and the global Cartesian flux components on selection.domain
    at stationary solnum 1, then integrates the right-boundary trace once with
    thickness. It does not implement alternate statistics, frames or positions.
    This is a fixture implementation contract, not a new public manifest schema.
    """
    selections=case['tags']['selections']
    expected={
        'temperature_field':{
            'expression':'T', 'unit':'K', 'selection':selections['domain'],
            'coordinate_system':'global Cartesian',
            'statistic':'pointwise field, no averaging',
            'positions':'stationary; no time/frequency/mode; fixed parameters from this case',
            'required_solution':'future stationary solution, owned by compute',
            'analytic':'T(x,y)=T_left+(T_right-T_left)*x/L'},
        'conductive_heat_flux':{
            'expression_definition':'q=(-k_slab*d(T,x),-k_slab*d(T,y))',
            'unit':'W/m^2', 'selection':selections['domain'],
            'coordinate_system':'global Cartesian',
            'statistic':'vector components pointwise; +x sign convention',
            'positions':'same stationary solution and fixed parameters',
            'analytic':'qx=k_slab*(T_left-T_right)/L, qy=0'},
        'through_heat_rate':{
            'expression_definition':'integral of qx over right boundary times thickness',
            'unit':'W', 'selection':selections['right'],
            'coordinate_system':'global Cartesian',
            'statistic':'outward +x flux integral, multiply thickness exactly once',
            'positions':'same stationary solution and fixed parameters',
            'analytic':'Q=k_slab*H*thickness*(T_left-T_right)/L'}}
    records=case.get('target_outputs')
    if not isinstance(records,list) or len(records)!=len(expected):
        raise ValueError('This slab adapter requires exactly the three supported targets')
    targets={}
    for target in records:
        if not isinstance(target,dict) or not isinstance(target.get('name'),str):
            raise ValueError('Target must be an object with a supported name')
        name=target['name']
        if name not in expected or name in targets:
            raise ValueError('Unknown or duplicate target: '+name)
        required={'name',*expected[name]}
        if set(target)!=required:
            missing=sorted(required-set(target));extra=sorted(set(target)-required)
            raise ValueError('Unsupported target fields for '+name+': missing='+str(missing)+', extra='+str(extra))
        for field,value in expected[name].items():
            if not isinstance(target[field],str) or not target[field].strip() or target[field]!=value:
                raise ValueError('Unsupported target '+name+'.'+field+'; adapter review required')
        targets[name]=target
    return targets


def properties(case, variant, level):
    if case['case_id'] != 'slab-steady-2d-20261101' or variant not in ('base', 'modified') or level not in ('coarse', 'fine'):
        raise ValueError('This adapter implements only the reviewed slab fixture and two mesh levels')
    tags = case['tags']; geo = case['geometry']; phys = case['physics']
    def val(key): return geo['parameters'][key]['expression']
    p = {key: tags[key] for key in ('component', 'geometry', 'physics', 'material','temperature_left','temperature_right','insulation')}
    p.update({'physics_type': 'HeatTransfer', 'mesh_tag': 'cmesh', 'study_tag': 'cstd', 'dataset_tag': 'cdset',
              'mesh_hmax': 'min(L,H)/'+('4' if level == 'coarse' else '8'),
              'mesh_hmin': 'min(L,H)/'+('40' if level == 'coarse' else '80'),
              'solver_rtol': '1e-8', 'sample_nx':'9', 'sample_ny':'5'})
    p.update({'selection.'+k:v for k,v in tags['selections'].items()})
    p.update({'boundary.'+k:tags[k] for k in ('temperature_left','temperature_right','insulation')})
    p.update({'expected.'+k: val(k) for k in ('L','H','thickness')})
    if variant == 'modified': p['expected.L'] = geo['modify']['new_expression']
    for field in ('conductivity', 'left_temperature', 'right_temperature'):
        item = phys[field]; p['expected.'+item['parameter']] = item['expression']
    targets = validate_target_outputs(case)
    # Explicit compilation of THIS fixture's formula; reject semantic changes.
    if (case['geometry']['dimension']!=2 or case['geometry']['coordinate_system']!='Cartesian x-y' or
        case['physics']['stationary'] is not True or case['physics']['conduction_only'] is not True):
        raise ValueError('Target formula changed; adapter review required')
    p.update({'target.temperature.expression': targets['temperature_field']['expression'],
              'target.temperature.unit': targets['temperature_field']['unit'],
              'target.flux_x.expression': '-k_slab*d(T,x)', 'target.flux_y.expression': '-k_slab*d(T,y)',
              'target.flux_x.unit': targets['conductive_heat_flux']['unit'], 'target.flux_y.unit': targets['conductive_heat_flux']['unit'],
              'target.heat_rate.expression': '-k_slab*mean(d(T,x))*thickness',
              'target.heat_rate.unit': targets['through_heat_rate']['unit']})
    return p


def execution_settings(case, variant, level):
    p=properties(case,variant,level)
    return {'parameters':{k:v for k,v in p.items() if k.startswith('expected.')},
            'solver_settings':{'mesh_hmax':p['mesh_hmax'],'mesh_hmin':p['mesh_hmin'],'rtol':p['solver_rtol'],
              'strategy':'fresh stationary auto-generated solver sequence; preserve modeled physics',
              'physical_initial_conditions':case['physics']['physical_initial_state'],
              'solver_initial_guess':'inherited initialization; no physical initial condition edited; actual generated sequence must be reviewed'}}


def runtime_layout(mode):
    if mode not in ('solve','readback','export'):raise ValueError('Unknown runtime phase')
    prefix='rt/'+{'solve':'s','readback':'r','export':'e'}[mode]
    return {key:prefix+'/'+name for key,name in
            (('launch','j'),('tmp','t'),('recovery','r'),('prefs','p'),('configuration','c'),('workspace','w'))}


def phase_logs(mode):
    return [mode+'-'+suffix+'.log' for suffix in ('stdout','stderr','batch','guard.stdout','guard.stderr')]


def phase_outputs(mode):
    return [{'path':mode+suffix,'role':role} for suffix,role in
            (('-resource.json','resource_evidence'),('-process.json','phase_process'),
             ('-job.properties','job_properties'),('-path-preflight.json','runtime_path_evidence'),
             ('-diagnostics.json','phase_diagnostics'))]+[{'path':runtime_layout(mode)['launch']+'/job.properties','role':'job_properties'}]


def prepare(case_path, destination):
    case_path = Path(case_path).resolve(); case = read(case_path)
    # Reject unsupported semantics before creating a partial preparation package.
    properties(case,'base','coarse')
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=False)
    binding = {'path': str(case_path), 'sha256': sha(case_path)}
    names = [x['name'] for x in case['target_outputs']]
    for variant in ('base', 'modified'):
        for level in ('coarse','fine'):
            record = {'status':'pending', 'authorization_granted':False, 'compilation':'not_run',
                      'case_spec':binding, 'variant':variant, 'mesh_level':level,
                      'model':None, 'manifest':None, 'input_record':None, 'operation_review':None,
                      'batch_executable':None, 'class_file':None, 'solution_tag':None,
                      'legacy_solution_id':None, 'solution_id':None, 'export_identity':None, 'log_encoding':None,
                      'runtime_path_policy':{'layout':'bundle_private_compact_v1','max_path_utf16_units':None,
                          'reserved_native_suffix_utf16_units':None,'review_basis':None},
                      'preferences_template':None, 'resource_guard':None, 'authorization_file':None,
                      'stage_resources':{'cores':None,'memory_mib':None,'timeout_seconds':None},
                      'properties':properties(case,variant,level),
                      'expected_positions':{n:[{'kind':'stationary','solnum':1}] for n in names},
                      'numerical_basis':'Fixture-only initial triangular meshes H/4 and H/8, hmin=hmax/10; requested sizes are not actual mesh evidence. rtol=1e-8 is an explicit engineering starting choice, not an accepted accuracy threshold.',
                      'missing':['authorized model build/check and immutable v2 manifest','current input record and two operation reviews','reviewed compiled class and current execution authorization','actual log encoding verification','export requires verified existing solution tag/id','per-source log encoding policy and reviewed private runtime path budget']}
            write_new(destination/(variant+'-'+level+'.json'),record)
            for operation in ('solve','export'):
                outputs=[{'path':'solution-readback.json','role':'solution_readback'},
                         {'path':'solver-observation.json','role':'solver_observation'},
                         {'path':'mesh-vertices.json','role':'mesh_evidence'},
                         {'path':'mesh-elements.json','role':'mesh_evidence'}]
                if operation=='solve': outputs += [{'path':'solved.mph','role':'solved_model'},{'path':'solve-metadata.json','role':'solve_metadata'}]
                phases=['solve','readback'] if operation=='solve' else ['export']
                outputs += [item for phase in phases for item in phase_outputs(phase)]
                logs=[name for phase in phases for name in phase_logs(phase)]
                policy={name:None for name in ['stdout.log','stderr.log',*logs]}
                settings_path=destination/(variant+'-'+level+'.'+operation+'.settings.json')
                write_new(settings_path,{**record,'operation':operation,'log_encodings':policy})
                config={'schema_version':'2.0.0','operation':operation,'execution_kind':'comsol',
                    'model':None,'manifest':None,'input_record':None,'operation_review':None,
                    'scope':['all'],'target_names':names,'scripts':[], 'dependencies':[],
                    'argv':['PENDING_ABSOLUTE_PYTHON','-X','utf8','-B','PENDING_ABSOLUTE_stage_driver.py','--bundle','{run_dir}',
                            '--settings',str(settings_path.resolve()),'--runner','PENDING_ABSOLUTE_run_bundle.py'],
                    'script_review':{'reviewed':False,'operation':operation,'calls_solver':operation=='solve','notes':'Pending source/compiled-class review and model inspection'},
                    'expected_positions':record['expected_positions'],'outputs':outputs,'evidence':'evidence.json',
                    'logs':logs,
                    'log_encoding':None,'log_encodings':policy,**execution_settings(case,variant,level),
                    'resources':{'timeout_seconds':None}}
                write_new(destination/(variant+'-'+level+'.'+operation+'.run-config.json'),config)
    write_new(destination/'preparation.json', {'status':'plan_prepared_not_executable','case_spec':binding,
              'real_comsol':'not_run','authorization_granted':False,'analytic_reference':case['analytic_reference'],
              'analytic_is_not_measured':True,'target_definitions':case['target_outputs']})
    write_new(destination/'readback.template.json', {'status':'pending','case_spec':binding,'mode':'readback',
              'input_mph':None,'solution_tag':None,'execution_authorized':False,
              'properties_source':'Select base/modified coarse/fine settings only after current input review',
              'entry':'SlabComputeAdapter.run(), fresh per-phase cwd/job.properties (UTF-8); original getenv entry was not tested as failing',
              'outputs':['solution-readback.json','mesh-vertices.json','mesh-elements.json'],
              'rule':'Independent process; missing/empty/nonstationary solution exits; no save or solver call. Standalone readback is an export-scoped operation needing its own current review and authorization.'})


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--case',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--manifest');ap.add_argument('--source');ap.add_argument('--legacy-id')
    a=ap.parse_args();prepare(a.case,a.out)
    if any((a.manifest,a.source,a.legacy_id)):
        if not all((a.manifest,a.source,a.legacy_id)):raise ValueError('Export identity preparation needs manifest/source/legacy-id together')
        identity=resolve_export_identity(a.manifest,a.legacy_id,a.source,[t['name'] for t in read(a.case)['target_outputs']])
        write_new(Path(a.out)/'export-identity.json',{'status':'pending_operation_reviews','identity':identity})
