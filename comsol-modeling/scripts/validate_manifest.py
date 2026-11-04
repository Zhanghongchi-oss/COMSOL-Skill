#!/usr/bin/env python3
"""Receive a v2 manifest, or hash an MPH without inspecting its contents.
Uses this skill's shipped public contract copy. Never starts COMSOL.
"""
import argparse
import json
import sys
from pathlib import Path
from contract_v2 import digest, validate_manifest


def inspect_mph_path(path):
    path = Path(path).resolve()
    if path.suffix.lower() != '.mph' or not path.is_file():
        return {'status': 'rejected', 'errors': [
            {'code': 'FILE_MISSING', 'instance_path': '$.model.path', 'message': 'Expected an existing MPH file.'}], 'public_errors': [
            {'code': 'FILE_MISSING', 'path': str(path), 'message': 'Expected an existing MPH file.'}],
            'side_errors': [], 'todos': [], 'comsol_model_check_performed': False,
            'execution_readiness': 'not_assessed', 'authorization_granted': False}
    return {'schema_version': '2.0.0', 'record_type': 'mph_receipt',
        'status': 'pending_model_inspection',
        'model': {'path': str(path), 'sha256': digest(path)},
        'manifest': None, 'inventory_status': 'not_inspected',
        'errors': [], 'public_errors': [], 'side_errors': [],
        'todos': [{'code': 'MODEL_INSPECTION_REQUIRED', 'path': str(path),
                   'message': 'Only file bytes were hashed. Prepare an authorized read-only inventory; no model internals were checked.'}],
        'comsol_model_check_performed': False,
        'execution_readiness': 'not_assessed', 'authorization_granted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('legacy_positional_manifest', nargs='?', type=Path,
                        help='Path alias only; old schema versions are still rejected.')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--manifest', type=Path)
    source.add_argument('--mph', type=Path)
    parser.add_argument('--out', type=Path, help='Optional new receipt; existing files are never overwritten.')
    args = parser.parse_args()
    if args.legacy_positional_manifest and (args.manifest or args.mph):
        parser.error('Choose one input.')
    manifest = args.manifest or args.legacy_positional_manifest
    if not manifest and not args.mph:
        parser.error('Provide --manifest or --mph.')
    try:
        report = inspect_mph_path(args.mph) if args.mph else validate_manifest(manifest, side='modeling')
        if manifest:
            report['status'] = 'rejected' if report['public_errors'] or report['side_errors'] else 'input_files_verified'
            report['execution_readiness'] = 'not_assessed'
            report['authorization_granted'] = False
        content = json.dumps(report, ensure_ascii=False, indent=2)
        if args.out:
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(content)
        print(content)
        return 2 if report['public_errors'] or report['side_errors'] else (3 if args.mph else 0)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'errors': [], 'public_errors': [],
                          'side_errors': [{'code': 'RECEIPT_IO', 'path': str(args.out or manifest or args.mph), 'message': str(exc)}],
                          'todos': [], 'comsol_model_check_performed': False,
                          'execution_readiness': 'not_assessed', 'authorization_granted': False}, ensure_ascii=False, indent=2))
        return 2


if __name__ == '__main__':
    sys.exit(main())
