#!/usr/bin/env python3
"""Read-only operation and input-binding gate; never launches commands."""
import argparse
import json
import re
from pathlib import Path
from operation_review import verify_review, read_json, digest


def side_issue(code, path, message):
    return {'code': code, 'path': str(path), 'message': message}


def read_job(path):
    """Shared strict subset used by this gate and the bundled Java inspector.

    UTF-8/BOM, comments and key=value are supported. Escapes, continuation,
    duplicate keys and whitespace/separators in keys are deliberately rejected.
    """
    result = {}
    java_trim = ''.join(chr(i) for i in range(33))
    for number, raw in enumerate(Path(path).read_text(encoding='utf-8-sig').split('\n'), 1):
        line = raw.strip(java_trim)
        if not line or line.startswith(('#', '!')):
            continue
        if '\\' in line or '\r' in line or '=' not in line:
            raise ValueError('Job line %d must use key=value without escapes or continuation; use forward-slash paths.' % number)
        key, value = line.split('=', 1)
        key, value = key.strip(java_trim), value.strip(java_trim)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', key) or key in result:
            raise ValueError('Job line %d contains an invalid or duplicate key.' % number)
        result[key] = value
    return result


def input_snapshot(required_files=(), job_path=None, input_model=None, run_directory=None, require_model=False):
    """Hash declared inputs, reporting binding failures without inspecting MPH."""
    result = {'inputs': [], 'input_model': None, 'audit_output': None, 'side_errors': [],
              'job_contract': 'utf8_key_equals_value_no_escapes',
              'comsol_model_check_performed': False, 'authorization_granted': False}
    files = {str(Path(p).resolve()): 'runtime_input' for p in required_files}
    job_model = None
    if job_path:
        job_path = Path(job_path).resolve()
        files[str(job_path)] = 'job'
        try:
            job = read_job(job_path)
            if 'input_model' in job:
                if not job['input_model'] or not Path(job['input_model']).is_absolute():
                    raise ValueError('job.input_model must be an absolute path; copying a job must not rebase its model.')
                job_model = Path(job['input_model']).resolve()
            if 'audit_output' in job:
                if not job['audit_output'] or run_directory is None:
                    raise ValueError('audit_output requires a nonempty path and explicit RunDirectory.')
                base = Path(run_directory).resolve()
                audit = Path(job['audit_output'])
                audit = (audit if audit.is_absolute() else base / audit).resolve()
                if not audit.is_relative_to(base) or audit == base or audit.suffix.lower() != '.tsv':
                    raise ValueError('audit_output must be a new TSV inside RunDirectory.')
                if audit.exists():
                    raise ValueError('audit_output must not already exist.')
                result['audit_output'] = str(audit)
        except (OSError, ValueError, TypeError) as exc:
            result['side_errors'].append(side_issue('MODELING_JOB_INVALID', job_path, str(exc)))
    explicit = Path(input_model).resolve() if input_model else None
    if job_model is not None and explicit is not None and job_model != explicit:
        result['side_errors'].append(side_issue('MODELING_INPUT_CONFLICT', job_path, 'Job and explicit input model differ.'))
    actual = job_model or explicit
    if actual is not None:
        files[str(actual)] = 'input_model'
        if actual.suffix.lower() != '.mph':
            result['side_errors'].append(side_issue('MODELING_INPUT_INVALID', actual, 'Input model must be an MPH file.'))
        if actual.is_file():
            result['input_model'] = {'path': str(actual), 'sha256': digest(actual)}
    elif require_model:
        result['side_errors'].append(side_issue('MODELING_INPUT_REQUIRED', 'input_model', 'Inspect/modify requires job.input_model or explicit InputModel.'))
    for raw, role in sorted(files.items()):
        path = Path(raw)
        exists = path.is_file()
        result['inputs'].append({'path': str(path), 'sha256': digest(path) if exists else None,
                                 'role': role, 'status': 'hashed' if exists else 'missing'})
        if not exists:
            result['side_errors'].append(side_issue('MODELING_INPUT_MISSING', path, 'Declared runtime input is missing.'))
    return result


def check(review_path, operation, scope, required_files, job_path=None, input_model=None,
          run_directory=None, strict_bindings=False):
    try:
        result = verify_review(review_path, operation=operation, scope=scope)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'blocked', 'errors': [], 'public_errors': [],
                'side_errors': [side_issue('MODELING_REVIEW_INVALID', review_path, str(exc))],
                'todos': [], 'authorization_granted': False, 'comsol_model_check_performed': False}
    if operation not in ('build', 'modify', 'inspect'):
        result['side_errors'].append(side_issue('MODELING_OPERATION', 'operation', 'Modeling supports only build, modify and inspect.'))
    # Older callers that list a .properties input still receive the actual-model check.
    jobs = [p for p in required_files if Path(p).suffix.lower() == '.properties']
    if job_path is None and len(jobs) == 1:
        job_path = jobs[0]
    if job_path is None and len(jobs) > 1:
        result['side_errors'].append(side_issue('MODELING_JOB_AMBIGUOUS', 'job', 'Specify the actual runtime job explicitly.'))
    snapshot = input_snapshot(required_files, job_path, input_model, run_directory,
                              require_model=strict_bindings and operation in ('inspect', 'modify'))
    result['side_errors'].extend(snapshot['side_errors'])
    result['input_bindings'] = snapshot
    try:
        review = read_json(review_path)
        pins = {str(Path(pin['path']).resolve()): pin['sha256'] for pin in review['pins']}
        for item in snapshot['inputs']:
            if item['path'] not in pins:
                result['side_errors'].append(side_issue('MODELING_PIN_MISSING', item['path'], 'Every actual source, model, job, configuration and helper must be pinned.'))
            elif item['sha256'] != pins[item['path']]:
                result['side_errors'].append(side_issue('MODELING_PIN_CHANGED', item['path'], 'A required runtime input changed after preparation.'))
        actual = snapshot['input_model']
        expected = review.get('model')
        if strict_bindings and expected and not actual and not any(x['code'] == 'MODELING_INPUT_REQUIRED' for x in result['side_errors']):
            result['side_errors'].append(side_issue('MODELING_INPUT_REQUIRED', 'input_model', 'A model-bound review requires an explicit actual input model, including build operations.'))
        if actual and (not expected or Path(expected['path']).resolve() != Path(actual['path']) or expected['sha256'] != actual['sha256']):
            result['side_errors'].append(side_issue('MODELING_INPUT_MISMATCH', 'input_model', 'Actual primary input model does not match operation_review.model path and hash.'))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['side_errors'].append(side_issue('MODELING_REVIEW_INVALID', review_path, str(exc)))
    if result.get('errors') or result.get('public_errors') or result['side_errors']:
        result['status'] = 'blocked'
    result['authorization_granted'] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--operation', required=True)
    parser.add_argument('--scope', nargs='+', default=['all'])
    parser.add_argument('--require-file', action='append', default=[])
    parser.add_argument('--job')
    parser.add_argument('--input-model')
    parser.add_argument('--run-directory')
    parser.add_argument('--describe-inputs', action='store_true')
    args = parser.parse_args()
    if args.describe_inputs:
        result = input_snapshot(args.require_file, args.job, args.input_model, args.run_directory,
                                require_model=args.operation in ('inspect', 'modify'))
    else:
        if not args.review:
            parser.error('--review is required unless --describe-inputs is used')
        result = check(args.review, args.operation, args.scope, args.require_file,
                       args.job, args.input_model, args.run_directory, strict_bindings=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (args.describe_inputs or result['status'] == 'ready') else 2


if __name__ == '__main__':
    raise SystemExit(main())
