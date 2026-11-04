"""Pure preparation for the explicitly reviewed, bounded nonlinear Joule fixture.

The digest freezes this adapter's scientific contract, including sampling,
selection, units and statistics. It is not a public manifest schema or a claim
that other COMSOL problems must use these parameters. A changed case needs an
adapter review; never silently reinterpret it through this narrow implementation.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED_DIR = HERE.parent.parent / 'steady-slab' / 'scripts'
spec = importlib.util.spec_from_file_location('nonlinear_shared_prepare', SHARED_DIR / 'prepare_case.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
read, sha, write_new = shared.read, shared.sha, shared.write_new
runtime_layout, phase_logs, phase_outputs = shared.runtime_layout, shared.phase_logs, shared.phase_outputs
resolve_export_identity = shared.resolve_export_identity

SUPPORTED_CASE_DIGEST = 'fd0b320476106e74c36437d0084baac3986bc54fc542e51321de83e377c6d21d'
TARGET_PROPERTIES = {
    'temperature': ('T', 'K'),
    'flux_x': ('-k_slab*d(T,x)', 'W/m^2'),
    'flux_y': ('-k_slab*d(T,y)', 'W/m^2'),
    'heat_rate': ('-k_slab*mean(d(T,x))*thickness', 'W'),
    'potential': ('V', 'V'),
    'current_x': ('ec.Jx', 'A/m^2'),
    'current_y': ('ec.Jy', 'A/m^2'),
    'joule_density': ('ec.Qh', 'W/m^3'),
    'joule_power': ('ec.Qh*thickness', 'W'),
    'heat_left': ('k_slab*mean(d(T,x))*thickness', 'W'),
    'electric_left': ('-sigma_slab/(1+beta*(T-T_ref))*V*mean(d(V,x))*thickness', 'W'),
    'electric_right': ('sigma_slab/(1+beta*(T-T_ref))*V*mean(d(V,x))*thickness', 'W'),
    'electrical_power': ('-V*(ec.Jx*nx+ec.Jy*ny)*thickness', 'W'),
}


def case_digest(case):
    return hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def properties(case, variant, level):
    if case_digest(case) != SUPPORTED_CASE_DIGEST:
        raise ValueError('Unsupported Joule scientific contract; review adapter before changing case')
    if variant not in ('base', 'modified') or level not in ('coarse', 'fine'):
        raise ValueError('Unsupported Joule variant or mesh level')
    tags = case['tags']
    p = {k: v for k, v in tags.items() if k != 'selections'}
    p.update({'selection.' + k: v for k, v in tags['selections'].items()})
    p.update({'expected.' + k: v for k, v in case['variants'][variant]['parameters'].items()})
    p.update(mesh_tag='cmesh', study_tag='cstd', dataset_tag='cdset',
             mesh_hmax='min(L,H)/' + ('4' if level == 'coarse' else '8'),
             mesh_hmin='min(L,H)/' + ('40' if level == 'coarse' else '80'),
             solver_rtol='1e-8', sample_nx='9', sample_ny='5')
    for name, (expression, unit) in TARGET_PROPERTIES.items():
        p['target.' + name + '.expression'] = expression
        p['target.' + name + '.unit'] = unit
    return p


def execution_settings(case, variant, level):
    p = properties(case, variant, level)
    return {'parameters': {k: v for k, v in p.items() if k.startswith('expected.')},
            'solver_settings': {'mesh_hmax': p['mesh_hmax'], 'mesh_hmin': p['mesh_hmin'],
                'rtol': p['solver_rtol'],
                'strategy': 'fresh stationary auto-generated coupled solver; preserve modeled physics',
                'physical_initial_conditions': case['physical_initial_state'],
                'solver_initial_guess': 'inherited generated stationary initialization; no physical initial state edited'}}


def validate_manifest_targets(manifest, case, variant, operation):
    """Reject semantic drift before launch, including statistics and selections."""
    if operation not in ('solve', 'export'):
        raise ValueError('This adapter supports solve and existing-solution export only')
    properties(case, variant, 'coarse')
    expected = {t['name']: t for t in case['variants'][variant]['target_outputs']}
    rows = manifest.get('target_outputs', [])
    if len(rows) != len(expected) or {t.get('name') for t in rows} != set(expected):
        raise ValueError('Exactly the nine reviewed Joule targets are required')
    fields = ('expression', 'unit', 'coordinate_system', 'statistic', 'time',
              'frequency', 'parameters', 'mode')
    for target in rows:
        reference = expected[target['name']]
        if target.get('status') != 'complete' or target.get('selection_ref') != reference['selection_ref']:
            raise ValueError('Target status/selection changed: ' + target['name'])
        for field in fields:
            actual = target.get(field, {})
            for key in ('status', 'value', 'unresolved_ids'):
                if actual.get(key) != reference[field].get(key):
                    raise ValueError('Unsupported target semantics: ' + target['name'] + '.' + field + '.' + key)
        required = target.get('required_solution', {})
        kind = 'planned' if operation == 'solve' else 'existing'
        if required.get('status') != 'complete' or required.get('kind') != kind or required.get('unresolved_ids'):
            raise ValueError('Target solution requirement does not match operation')


def prepare(case_path, destination):
    """Create honest unready plans; current reviews/authorization are never inferred."""
    case_path = Path(case_path).resolve(strict=True)
    case = read(case_path)
    properties(case, 'base', 'coarse')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for variant in ('base', 'modified'):
        names = [t['name'] for t in case['variants'][variant]['target_outputs']]
        for level in ('coarse', 'fine'):
            for operation in ('solve', 'export'):
                phases = ['solve', 'readback'] if operation == 'solve' else ['export']
                logs = [name for phase in phases for name in phase_logs(phase)]
                codecs = {name: None for name in ['stdout.log', 'stderr.log', *logs]}
                stem = variant + '-' + level + '.' + operation
                settings_path = destination / (stem + '.settings.json')
                positions = {name: [{'kind': 'stationary', 'solnum': 1}] for name in names}
                settings = {'status': 'pending', 'authorization_granted': False, 'compilation': 'not_run',
                    'case_spec': {'path': str(case_path), 'sha256': sha(case_path)},
                    'variant': variant, 'mesh_level': level, 'operation': operation,
                    'properties': properties(case, variant, level), 'expected_positions': positions,
                    'batch_executable': None, 'class_file': None, 'solution_tag': None,
                    'solution_id': None, 'legacy_solution_id': None, 'export_identity': None,
                    'resource_guard': None, 'authorization_file': None, 'preferences_template': None,
                    'stage_resources': {'cores': None, 'memory_mib': None, 'timeout_seconds': None},
                    'runtime_path_policy': {'layout': 'bundle_private_compact_v1',
                        'max_path_utf16_units': None, 'reserved_native_suffix_utf16_units': None, 'review_basis': None},
                    'log_encodings': codecs}
                write_new(settings_path, settings)
                outputs = [{'path': n, 'role': role} for n, role in (
                    ('solution-readback.json', 'solution_readback'), ('solver-observation.json', 'solver_observation'),
                    ('mesh-vertices.json', 'mesh_evidence'), ('mesh-elements.json', 'mesh_evidence'))]
                if operation == 'solve':
                    outputs += [{'path': 'solved.mph', 'role': 'solved_model'}, {'path': 'solve-metadata.json', 'role': 'solve_metadata'}]
                outputs += [item for phase in phases for item in phase_outputs(phase)]
                cfg = {'schema_version': '2.0.0', 'operation': operation, 'execution_kind': 'comsol',
                    'model': None, 'manifest': None, 'input_record': None, 'operation_review': None,
                    'scope': ['target:' + name for name in names], 'target_names': names,
                    'scripts': [], 'dependencies': [],
                    'argv': ['PENDING_PYTHON', '-X', 'utf8', '-B', str(HERE / 'stage_driver.py'),
                             '--bundle', '{run_dir}', '--settings', str(settings_path), '--runner', 'PENDING_RUNNER'],
                    'script_review': {'reviewed': False, 'operation': operation, 'calls_solver': operation == 'solve',
                                      'notes': 'Needs current inspected model, exact source/class review, runtime pins and authorization'},
                    'expected_positions': positions, 'outputs': outputs, 'evidence': 'evidence.json',
                    'logs': logs, 'log_encodings': codecs, **execution_settings(case, variant, level),
                    'resources': {'timeout_seconds': None}}
                write_new(destination / (stem + '.run-config.json'), cfg)
    write_new(destination / 'preparation.json', {'status': 'plan_prepared_not_executable',
        'compilation': 'not_run', 'comsol_execution': 'not_run', 'authorization_granted': False,
        'case_spec': {'path': str(case_path), 'sha256': sha(case_path)},
        'required_runtime_inputs': ['current inspected MPH and v2 manifest', 'public and compute operation reviews',
            'current source and compiled class', 'both Joule and shared slab Python modules in pins',
            'explicit resource/path/codec policies and private prefs', 'current execution authorization',
            'for export: actual reviewed existing solution carrier and identity'],
        'scope': 'This fixed constant-isotropic Cartesian stationary nonlinear Joule fixture only; no general convergence or resume claim'})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    prepare(args.case, args.out)

