"""Bounded nonlinear stationary Joule adapter: solve then separate reload, or export only.

Reuse the shipped resource/log/path and straight-triangle mesh checks. This
module supplies the distinct nine-target scientific contract. No model-physics
setter is exposed; public and compute reviews plus current authorization remain
required by the production runner.
"""
import argparse
import importlib.util
import math
from pathlib import Path
import sys
from prepare_case import (read, sha, write_new, properties, execution_settings,
                          validate_manifest_targets, SHARED_DIR, shared)

# Load the shared module with its own sibling imports, without allowing the
# Joule helper to impersonate the slab helper via an accidental sys.path match.
_previous = sys.modules.get('prepare_case')
try:
    sys.modules['prepare_case'] = shared
    _spec = importlib.util.spec_from_file_location('nonlinear_shared_stage', SHARED_DIR / 'stage_driver.py')
    stage = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(stage)
finally:
    if _previous is None:
        sys.modules.pop('prepare_case', None)
    else:
        sys.modules['prepare_case'] = _previous
require = stage.require


def check_raw(raw, source, settings, meta):
    require(raw['run_id'] == meta['run_id'] and raw['fingerprint'] == meta['fingerprint'], 'Readback identity mismatch')
    require(raw['case_spec_sha256'] == settings['case_spec']['sha256'], 'Readback case mismatch')
    require(Path(raw['source_mph']).resolve() == Path(source).resolve() and raw['source_sha256'] == sha(source), 'Readback source mismatch')
    require(raw['solver_type'] == 'Stationary' and type(raw['solution_count']) is int and raw['solution_count'] == 1, 'One stationary solution required')
    require(type(raw['inner_solnum']) is int and raw['inner_solnum'] == 1, 'Unexpected observed position')
    require(raw['solution_tag'] == settings['solution_tag'] and raw['dataset_tag'] == settings['properties']['dataset_tag'], 'Solution/dataset mismatch')
    require(raw.get('dataset_persisted') is False, 'This readback only creates an in-memory dataset')
    coords = raw['sample_coordinates']
    require(raw['coordinate_unit'] == 'm' and len(coords) == 2 and len(coords[0]) == len(coords[1]) == 45, 'Expected 45 Cartesian SI samples')
    target = raw['target_values']
    require(set(target) == set(settings['expected_positions']), 'Missing or extra scientific target')
    p = settings['properties']
    values = coords[0] + coords[1]
    fields = {'temperature_field': 'temperature', 'potential_field': 'potential', 'joule_density': 'joule_density'}
    scalar = {'through_heat_rate': 'heat_rate', 'joule_power': 'joule_power', 'outward_heat_left': 'heat_left', 'electrical_power': 'electrical_power'}
    for name, key in {**fields, **scalar}.items():
        t = target[name]
        require(t['expression'] == p['target.' + key + '.expression'] and t['unit'] == p['target.' + key + '.unit'], 'Expression/unit mismatch: ' + name)
        if name in fields:
            require(len(t['values']) == 45, 'Wrong sample shape: ' + name)
            values += t['values']
        else:
            values.append(t['value'])
    for name, keys in {'conductive_heat_flux': ('flux_x', 'flux_y'), 'electric_current_density': ('current_x', 'current_y')}.items():
        t = target[name]
        require(t['expressions'] == [p['target.' + k + '.expression'] for k in keys] and t['unit'] == p['target.' + keys[0] + '.unit'], 'Vector expression/unit mismatch')
        require(len(t['values']) == 2 and all(len(row) == 45 for row in t['values']), 'Wrong vector sample shape')
        values += t['values'][0] + t['values'][1]
    power = target['electrical_power']
    values += [power['left_value'], power['right_value']]
    require(all(type(x) in (int, float) and math.isfinite(x) for x in values), 'Nonfinite or non-numeric output')
    require(power['value'] == power['left_value'] + power['right_value'], 'Electric power is not the sum of recorded electrodes')
    L, H = raw['parameters_si']['L'], raw['parameters_si']['H']
    for j in range(5):
        for i in range(9):
            n = j * 9 + i
            require(coords[0][n] == L * i / 8 and coords[1][n] == H * j / 4, 'Sampling grid differs from target definition')
    stage.domain_quality(raw)
    require(raw['mesh']['num_tri'] > 0 and raw['mesh']['num_vertices'] > 0, 'Missing actual mesh')


def execute(bundle, settings_path, runner_path):
    runner = stage.load_runner(runner_path)
    root, cfg, meta = runner.load_bundle(bundle)
    start = read(root / 'started.json')
    require(start['run_id'] == meta['run_id'] and start['fingerprint'] == meta['fingerprint'], 'No matching runner start')
    require(isinstance(start.get('authorization'), str) and start['authorization'].strip(), 'No separately recorded execution authorization')
    require(cfg['execution_kind'] == 'comsol' and cfg['operation'] in ('solve', 'export'), 'Unsupported operation')
    settings = read(settings_path)
    require(settings['status'] == 'reviewed_for_execution', 'Preparation remains pending')
    runtime = (settings_path, runner_path, __file__, Path(__file__).with_name('prepare_case.py'),
               SHARED_DIR / 'prepare_case.py', SHARED_DIR / 'stage_driver.py', settings['class_file'],
               settings['batch_executable'], settings['case_spec']['path'], settings['resource_guard'],
               settings['authorization_file'], settings['preferences_template'])
    for path in runtime:
        require(meta['pins'].get(str(Path(path).resolve())) == sha(path), 'Unpinned runtime input: ' + str(path))
    case = read(settings['case_spec']['path'])
    require(sha(settings['case_spec']['path']) == settings['case_spec']['sha256'], 'Case changed')
    require(settings['properties'] == properties(case, settings['variant'], settings['mesh_level']), 'Unreviewed case/numerical properties')
    for key, value in execution_settings(case, settings['variant'], settings['mesh_level']).items():
        require(cfg[key] == value, 'Reviewed execution settings differ: ' + key)
    validate_manifest_targets(read(Path(cfg['manifest'])), case, settings['variant'], cfg['operation'])
    require(cfg['expected_positions'] == settings['expected_positions'], 'Position plan differs')
    source = Path(cfg['model']).resolve()
    original_hash = sha(source)
    if cfg['operation'] == 'export':
        stage.resolve_export_for_settings(cfg, settings, source)
    stage.stage_budget(settings)
    stage.check_phase_log_policy(runner, cfg, settings)
    props = {**settings['properties'], 'input_mph': str(source), 'input_sha256': original_hash,
             'run_id': meta['run_id'], 'fingerprint': meta['fingerprint'], 'execution_authorized': 'true',
             'case_spec_sha256': settings['case_spec']['sha256'], 'output_mph': str(root / 'solved.mph'),
             'solve_metadata': str(root / 'solve-metadata.json'), 'raw_readback': str(root / 'solution-readback.json'),
             'mesh_vertices': str(root / 'mesh-vertices.json'), 'mesh_elements': str(root / 'mesh-elements.json')}
    if cfg['operation'] == 'solve':
        solve_job = stage.phase('solve', root, settings, props, runner, cfg)
        observed = read(root / 'solve-metadata.json')
        source = root / 'solved.mph'
        require(all(observed[k] == props[k] for k in ('run_id', 'fingerprint', 'case_spec_sha256')), 'Solve metadata identity mismatch')
        require(observed['job_properties_sha256'] == sha(solve_job) and observed['status'] == 'solve_saved_pending_independent_readback', 'Solve metadata phase mismatch')
        require(Path(observed['output_mph']).resolve() == source and observed['output_sha256'] == sha(source), 'Saved solution binding mismatch')
        require(observed['source_sha256'] == original_hash, 'Solve input binding mismatch')
        stage.check_solver_discovery(observed, settings)
        settings = {**settings, 'solution_tag': observed['solution_tag']}
        props.update(input_mph=str(source), input_sha256=observed['output_sha256'], solution_tag=observed['solution_tag'])
        job = stage.phase('readback', root, settings, props, runner, cfg)
    else:
        require(settings.get('solution_tag') and settings.get('legacy_solution_id'), 'Reviewed existing solution identity required')
        props['solution_tag'] = settings['solution_tag']
        job = stage.phase('export', root, settings, props, runner, cfg)
    require(sha(Path(cfg['model']).resolve()) == original_hash, 'Input MPH changed')
    raw = read(root / 'solution-readback.json')
    check_raw(raw, source, settings, meta)
    require(raw['status'] == 'independent_saved_solution_readback' and raw['mode'] == ('readback' if cfg['operation'] == 'solve' else 'export'), 'Readback phase mismatch')
    require(raw['job_properties_sha256'] == sha(job), 'Readback job mismatch')
    require(raw['mesh_vertices_sha256'] == sha(root / 'mesh-vertices.json') and raw['mesh_elements_sha256'] == sha(root / 'mesh-elements.json'), 'Mesh evidence binding mismatch')
    vertices, elements = read(root / 'mesh-vertices.json'), read(root / 'mesh-elements.json')
    stage.check_mesh_geometry(raw, vertices, elements, case['geometry_audit_tolerance_m'])
    stage.check_solution_mesh_binding(raw, vertices, elements, settings)
    positions = {name: [{'kind': 'stationary', 'solnum': raw['inner_solnum']}] for name in raw['target_values']}
    require(positions == cfg['expected_positions'], 'Observed positions differ from target coverage')
    ref = {'path': 'solution-readback.json', 'sha256': sha(root / 'solution-readback.json')}
    mapping = {'target_names': list(raw['target_values']), 'solution_tag': raw['solution_tag'], 'dataset_tag': raw['dataset_tag'],
               'solution_count': raw['solution_count'], 'available_solution_count': raw['solution_count'],
               'positions': [{'kind': 'stationary', 'solnum': raw['inner_solnum']}], 'source': {'path': str(source), 'sha256': raw['source_sha256']}}
    if cfg['operation'] == 'export':
        require(settings['solution_id'] == raw['solution_tag'], 'Actual existing solution identity mismatch')
        mapping.update(solution_id=settings['solution_id'], legacy_id=settings['legacy_solution_id'], selection_evidence=[ref])
    write_new(root / 'solver-observation.json', {'schema_version': '2.0.0', 'run_id': meta['run_id'], 'fingerprint': meta['fingerprint'],
        'operation': cfg['operation'], 'input_model_sha256': meta['pins'][cfg['model']],
        'solver_status': 'completed' if cfg['operation'] == 'solve' else 'existing_solution_available',
        'completed_positions': positions, 'observation': {'method': 'saved_solution_readback',
            'detail': 'Separate COMSOL process loaded saved coupled solution and read all nine targets.', 'evidence': [ref]}, 'solutions': [mapping]})
    hashes = {item['path']: sha(runner.inside(root, item['path'])) for item in cfg['outputs']}
    runner.validate_solver_observation(root, cfg, meta, start['started_ns'], hashes)
    write_new(root / cfg['evidence'], {'run_id': meta['run_id'], 'fingerprint': meta['fingerprint'], 'operation': cfg['operation'],
        'status': 'completed', 'completed_positions': positions, 'output_hashes': hashes})


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', required=True)
    ap.add_argument('--settings', required=True)
    ap.add_argument('--runner', required=True)
    a = ap.parse_args()
    try:
        execute(a.bundle, a.settings, a.runner)
    except Exception as exc:
        print('Joule adapter failure: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
