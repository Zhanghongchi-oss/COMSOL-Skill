#!/usr/bin/env python3
"""Read-only v2 handoff receiver; hashing is not a COMSOL model inspection.

The public validator is an independently bundled release from handoff-review.
No sibling skill is imported, no COMSOL process is created, and no v1 input is
implicitly migrated. Operation readiness is a separate review, not this record.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import uuid

VERSION = "2.0.0"
SCHEMA = Path(__file__).resolve().parents[1] / "references" / "model-manifest.schema.json"
CONTRACT = Path(__file__).resolve().with_name("contract_v2.py")


def read_json(path):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def no_nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=no_duplicates, parse_constant=no_nonfinite)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def resolved_path(raw, base):
    candidate = Path(raw)
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()


def issue(code, path, message):
    return {"code": code, "path": path, "message": message}


def _public_validator():
    """Load only this skill's public-contract release, never another skill."""
    spec = importlib.util.spec_from_file_location("comsol_compute_public_contract_v2", CONTRACT)
    if spec is None or spec.loader is None:
        raise ImportError("Bundled public contract module unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Loading a validator must not create cache files in the skill package.
    exec(compile(CONTRACT.read_bytes(), str(CONTRACT), "exec"), module.__dict__)
    return module


def validate(path):
    """Return authoritative public/side/todo classes for this consumer."""
    return _public_validator().validate_manifest(Path(path).resolve(), side="compute")


def _summaries(record):
    # Text projections are for display, never public conformance or run gates.
    record["error_messages"] = [x["message"] for x in record["errors"] + record["side_errors"]]
    record["pending_checks"] = [x["message"] for x in record["todos"]]
    return record


def build_record(*, manifest_path=None, mph_path=None):
    """Inspect file declarations and produce a new provenance envelope."""
    if (manifest_path is None) == (mph_path is None):
        raise ValueError("Supply exactly one of manifest_path and mph_path")
    record = {
        "record_schema_version": "comsol-compute-input/" + VERSION,
        "record_id": str(uuid.uuid4()),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "rejected", "manifest_file_check": "not_performed",
        "verification_scope": "Public contract, declared files and hashes only; no COMSOL model content or scientific validity check",
        "comsol_model_check_performed": False,
        "execution_readiness": "not_assessed",
        "authorization": "not_assessed",
        "authorization_granted": False,
        "errors": [], "public_errors": [], "side_errors": [], "todos": [],
        "runtime_dependencies": None,
        "runtime_dependency_inventory": {"status": "not_inspected", "reason": "No validated manifest inventory yet"},
    }
    if mph_path is not None:
        path = Path(mph_path).resolve()
        record["mode"] = "mph_only"
        record["model"] = {"resolved_path": str(path), "sha256": None}
        try:
            if path.suffix.lower() != ".mph":
                raise ValueError("Input model must be an MPH file")
            record["model"]["sha256"] = digest(path)
        except (OSError, ValueError) as exc:
            record["side_errors"].append(issue("COMPUTE_MPH_INPUT_INVALID", "$.model", str(exc)))
            return _summaries(record)
        record["status"] = "pending_model_inspection"
        record["inspection"] = {"status": "pending", "source": "File hash only; COMSOL was not opened"}
        record["todos"] = [
            issue("COMPUTE_MODEL_INSPECTION_PENDING", "$.model", "Read-only model inventory is pending; a file hash does not inspect MPH contents"),
            issue("COMPUTE_OPERATION_REVIEW_PENDING", "$", "Prepare an operation-specific review and verify current authorization separately before execution"),
        ]
        return _summaries(record)

    path = Path(manifest_path).resolve()
    record.update(mode="manifest", source_manifest_path=str(path))
    try:
        # Public parser errors retain the exact shared classification.
        try:
            before = digest(path)
        except OSError:
            before = None
        record["source_manifest_sha256"] = before
        validator = _public_validator()
        report = validator.validate_manifest(path, side="compute")
        for key in ("errors", "public_errors", "side_errors", "todos"):
            record[key] = list(report[key])
        record["manifest_file_check"] = report["manifest_file_check"]
        # The public release also supports a schema adjacent to its module.
        # Bind the file actually read by that module, not a guessed layout.
        record["shared_schema_path"] = str(validator.SCHEMA.resolve())
        record["shared_schema_sha256"] = digest(validator.SCHEMA)
        record["shared_validator_sha256"] = digest(CONTRACT)
        try:
            data = read_json(path)
        except (ValueError, OSError):
            return _summaries(record)
        record["supplied_manifest"] = data
        if isinstance(data, dict):
            record["manifest_schema_version"] = data.get("schema_version")
        if before is None or digest(path) != before:
            record["side_errors"].append(issue("COMPUTE_INPUT_CHANGED_DURING_CHECK", "$", "Manifest changed during validation; create a new input record"))
        if record["errors"] or record["side_errors"]:
            return _summaries(record)
        # An incorrectly packaged validator must not bypass version rejection.
        if not isinstance(data, dict) or data.get("schema_version") != VERSION:
            record["side_errors"].append(issue("COMPUTE_PROTOCOL_VERSION_UNSUPPORTED", "$.schema_version", "This receiver consumes only explicit v2.0.0; migrate separately while preserving the source"))
            return _summaries(record)
        model = data["model"]
        model_path = resolved_path(model["path"], path.parent)
        record["model"] = {**model, "resolved_path": str(model_path), "status": "hash_verified"}
        if model_path.suffix.lower() != ".mph":
            record["side_errors"].append(issue("COMPUTE_MODEL_EXTENSION", "$.model.path", "Input model path must identify an MPH file"))
            return _summaries(record)
        record["declared_inspection"] = data["checks"]
        record["runtime_dependency_inventory"] = data["inventory"]["dependencies"]
        dependencies = data["dependencies"]
        record["runtime_dependencies"] = None if dependencies is None else [
            {**item, "declared_path": item["path"],
             "path": str(resolved_path(item["path"], path.parent))}
            for item in dependencies if item["category"] == "runtime"
        ]
        record["status"] = "input_files_verified"
        record["todos"].append(issue("COMPUTE_OPERATION_REVIEW_PENDING", "$", "File-contract success is not execution readiness; operation_review and current authorization remain separate"))
    except (OSError, ImportError, ValueError, KeyError, TypeError) as exc:
        record["side_errors"].append(issue("COMPUTE_RECEIVER_FAILURE", "$", str(exc)))
    return _summaries(record)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--manifest", type=Path)
    group.add_argument("--mph", type=Path)
    parser.add_argument("--out", type=Path, help="New UTF-8 JSON record; refuses to overwrite any existing file")
    args = parser.parse_args(argv)
    record = build_record(manifest_path=args.manifest, mph_path=args.mph)
    content = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out:
        try:
            with args.out.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except OSError as exc:
            print("Cannot create output record: " + str(exc), file=sys.stderr)
            return 2
    print(content, end="")
    return 2 if record["status"] == "rejected" else 3 if record["status"] == "pending_model_inspection" else 0


if __name__ == "__main__":
    raise SystemExit(main())
