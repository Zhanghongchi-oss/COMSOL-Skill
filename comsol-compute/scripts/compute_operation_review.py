#!/usr/bin/env python3
"""Compute-only execution assessment layered on the bundled public review.

No commands are executed. Readiness never grants authorization. The public
manifest/review formats are not extended or reinterpreted by this module.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import uuid

VERSION = "2.0.0"
REVISION = "candidate03"
TYPE = "comsol_compute_execution_review"
PHYSICS_KEYS = ("confirmed_physical_problem", "physical_initial_conditions", "solver_initial_guess",
                "physics_activation", "multistep_transfer", "continuation")
EXECUTION_KEYS = {"parameters", "solver_settings"}
POSITION_FIELDS = ("time", "frequency", "parameters", "mode")
TOOL_PIN_ROLES = {"public_contract_implementation", "public_contract_schema"}
NON_RUNTIME_ROLES = {"input_manifest", "input_model"} | TOOL_PIN_ROLES


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON: " + value)))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_ref(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Expected file: " + str(path))
    return {"path": str(path), "sha256": digest(path)}


def issue(code, path, message):
    return {"code": code, "instance_path": path, "message": message}


def _normalise_issues(items):
    """Public errors retain the source's stable declaration instance path."""
    return [{"code": item["code"], "instance_path": item.get("instance_path", item.get("path", "$")),
             "message": item["message"]} for item in items]


def _public_result(report, result, include_todos=True):
    if not isinstance(result.get("errors"), list):
        report["side_errors"].append(issue("COMPUTE_PUBLIC_INTERFACE", "$", "candidate03 errors array is required; rebuild older review records"))
        return
    report["errors"].extend(_normalise_issues(result["errors"]))
    report["side_errors"].extend(_normalise_issues(result.get("side_errors", [])))
    if include_todos:
        report["todos"].extend(_normalise_issues(result.get("todos", [])))


def _position_map_valid(value, names):
    return (isinstance(value, dict) and isinstance(names, list) and names
            and set(value) == set(names)
            and all(isinstance(points, list) and points
                    and len({canonical(point) for point in points}) == len(points)
                    for points in value.values()))


def _position_definitions(data, names):
    targets = {item["name"]: item for item in data.get("target_outputs") or []}
    return {name: {key: targets[name][key] for key in POSITION_FIELDS}
            for name in names if name in targets}


@contextmanager
def local_modules():
    """Use only same-skill releases and avoid creating __pycache__ on reads."""
    names = ("contract_v2", "operation_review", "input_record")
    old = {name: sys.modules.get(name) for name in names}
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    modules = {}
    try:
        for name in names:
            path = Path(__file__).resolve().with_name(name + ".py")
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None:
                raise ImportError("Bundled module unavailable: " + name)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
            modules[name] = module
        yield modules
    finally:
        for name, module in old.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.dont_write_bytecode = previous


def _normalise_assessment(value, base):
    """Normalize evidence paths only; never fill missing statuses or facts."""
    if isinstance(value, list):
        return [_normalise_assessment(x, base) for x in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "evidence" and isinstance(item, list):
            entries = []
            for entry in item:
                if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                    path = Path(entry["path"])
                    entries.append({**entry, "path": str(path.resolve() if path.is_absolute() else (base / path).resolve())})
                else:
                    entries.append(entry)
            result[key] = entries
        else:
            result[key] = _normalise_assessment(item, base)
    return result


def _empty_report():
    return {"status": "pending", "public_errors": [], "side_errors": [], "todos": [],
            "errors": [], "required_runtime_files": [], "required_review_files": [],
            "allowed_solution_sources": [], "target_position_definitions": {},
            "authorization_granted": False, "comsol_model_check_performed": False,
            "scientific_validity_verified": False, "resume_reliability": "not_assessed"}


def _finish(report):
    for key in ("errors", "side_errors", "todos"):
        report[key] = _normalise_issues(report[key])
    report["public_errors"] = [{"code": item["code"], "path": item["instance_path"], "message": item["message"]}
                               for item in report["errors"]]
    report["status"] = "blocked" if report["errors"] or report["side_errors"] else "pending" if report["todos"] else "ready"
    for key in ("required_runtime_files", "required_review_files"):
        by_path = {}
        for item in report[key]:
            old = by_path.get(item["path"])
            if old and old["sha256"] != item["sha256"]:
                report["side_errors"].append(issue("COMPUTE_REVIEW_FILE_CONFLICT", item["path"], "Conflicting file hashes"))
            by_path[item["path"]] = item
        report[key] = sorted(by_path.values(), key=lambda x: x["path"])
    if report["side_errors"]:
        report["status"] = "blocked"
    return report


def _check_ref(ref, report, label, role="review_evidence"):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
        report["side_errors"].append(issue("COMPUTE_REVIEW_FILE_FORMAT", label, "Expected path and lowercase SHA256"))
        return None
    path = Path(ref["path"])
    if not path.is_absolute():
        report["side_errors"].append(issue("COMPUTE_REVIEW_FILE_FORMAT", label, "Stored review paths must be absolute"))
        return None
    path = path.resolve()
    report["required_review_files"].append({"path": str(path), "sha256": ref["sha256"], "role": role})
    try:
        if not path.is_file() or digest(path) != ref["sha256"]:
            raise ValueError("Referenced file is missing or changed")
    except OSError as exc:
        report["side_errors"].append(issue("COMPUTE_REVIEW_FILE_CHANGED", label, str(exc)))
        return None
    except ValueError as exc:
        report["side_errors"].append(issue("COMPUTE_REVIEW_FILE_CHANGED", label, str(exc)))
        return None
    return path


def _decision(value, report, label, allow_na=False):
    if not isinstance(value, dict) or set(value) != {"status", "reason", "evidence"}:
        report["todos"].append(issue("COMPUTE_ASSESSMENT_PENDING", label, "Explicit status/reason/evidence decision is required"))
        return
    status = value["status"]
    if status not in {"complete", "pending", "blocked", "not_applicable"} or not isinstance(value["reason"], str) or not value["reason"].strip() or not isinstance(value["evidence"], list):
        report["side_errors"].append(issue("COMPUTE_ASSESSMENT_FORMAT", label, "Decision has invalid status, reason or evidence"))
        return
    for index, ref in enumerate(value["evidence"]):
        _check_ref(ref, report, f"{label}.evidence[{index}]")
    if status == "blocked":
        report["side_errors"].append(issue("COMPUTE_ASSESSMENT_BLOCKED", label, value["reason"]))
    elif status == "pending":
        report["todos"].append(issue("COMPUTE_ASSESSMENT_PENDING", label, value["reason"]))
    elif status == "not_applicable" and not allow_na:
        report["side_errors"].append(issue("COMPUTE_ASSESSMENT_NOT_APPLICABLE", label, "This decision is required for the requested operation"))
    elif status == "complete" and not value["evidence"]:
        report["todos"].append(issue("COMPUTE_ASSESSMENT_EVIDENCE", label, "Completed manual review needs traceable evidence"))


def _evaluate(record, *, manifest_path, model_path, operation, scope, input_record_path,
              target_names, expected_positions, execution_config, pins=None, review_path=None):
    report = _empty_report()
    expected_keys = {"schema_version", "review_revision", "record_type", "review_id", "created_at", "binding", "operation", "scope",
                     "target_names", "expected_positions", "target_position_definitions", "execution_config", "assessment", "status", "authorization_granted"}
    if not isinstance(record, dict) or set(record) != expected_keys or record.get("schema_version") != VERSION or record.get("record_type") != TYPE or record.get("review_revision") != REVISION:
        report["side_errors"].append(issue("COMPUTE_REVIEW_FORMAT", "$", "Expected candidate03 compute review; create a new record from original inputs, never rewrite candidate02"))
        return _finish(report)
    if record.get("authorization_granted") is not False:
        report["side_errors"].append(issue("COMPUTE_REVIEW_AUTHORIZATION", "authorization_granted", "Review cannot grant authorization"))
    if operation not in {"solve", "resume", "export"} or record["operation"] != operation:
        report["side_errors"].append(issue("COMPUTE_REVIEW_OPERATION", "operation", "Review operation mismatch"))
    if not isinstance(scope, list) or not scope or not all(isinstance(x, str) and x.strip() for x in scope) or sorted(scope) != record["scope"]:
        report["side_errors"].append(issue("COMPUTE_REVIEW_SCOPE", "scope", "Review scope mismatch"))
    if not isinstance(target_names, list) or not target_names or not all(isinstance(name, str) and name.strip() for name in target_names) or len(set(target_names)) != len(target_names) or canonical(record["target_names"]) != canonical(target_names):
        report["side_errors"].append(issue("COMPUTE_REVIEW_EXECUTION_BINDING", "$.target_names", "Explicit target names differ from review"))
        return _finish(report)
    if not _position_map_valid(expected_positions, target_names) or canonical(record["expected_positions"]) != canonical(expected_positions):
        report["side_errors"].append(issue("COMPUTE_REVIEW_EXECUTION_BINDING", "$.expected_positions", "Expected a nonempty duplicate-free position array for every requested target; candidate02 global arrays are not accepted"))
    if not isinstance(execution_config, dict) or set(execution_config) != EXECUTION_KEYS or not all(isinstance(v, dict) for v in execution_config.values()) or canonical(record["execution_config"]) != canonical(execution_config):
        report["side_errors"].append(issue("COMPUTE_REVIEW_EXECUTION_BINDING", "execution_config", "Parameters/solver_settings must match the reviewed configuration"))
    binding = record["binding"]
    if not isinstance(binding, dict) or set(binding) != {"public_review", "manifest", "model", "input_record"}:
        report["side_errors"].append(issue("COMPUTE_REVIEW_BINDING", "binding", "Four input bindings are required"))
        return _finish(report)
    resolved = {key: _check_ref(value, report, "binding." + key, key) for key, value in binding.items()}
    for key, expected in (("manifest", manifest_path), ("model", model_path), ("input_record", input_record_path)):
        if expected is None or resolved.get(key) != Path(expected).resolve():
            report["side_errors"].append(issue("COMPUTE_REVIEW_BINDING", "binding." + key, "Input path does not match the current operation"))
    if any(path is None for path in resolved.values()):
        return _finish(report)
    if review_path is not None:
        report["required_review_files"].append({**file_ref(review_path), "role": "compute_execution_review"})
    with local_modules() as modules:
        public = modules["operation_review"].verify_review(resolved["public_review"], resolved["manifest"], operation, scope)
        _public_result(report, public)
        if public.get("status") not in {"ready", "pending", "blocked"}:
            report["side_errors"].append(issue("COMPUTE_PUBLIC_REVIEW_INVALID", "binding.public_review", "Public verifier returned an invalid status"))
        elif public["status"] != "ready" and not (report["errors"] or report["side_errors"] or report["todos"]):
            report["todos"].append(issue("COMPUTE_PUBLIC_REVIEW_PENDING", "binding.public_review", "Public operation review is not ready"))
        saved_public = read_json(resolved["public_review"])
        if saved_public.get("input_kind") != "manifest" or not isinstance(target_names, list) or sorted(saved_public.get("target_names", [])) != sorted(target_names):
            report["side_errors"].append(issue("COMPUTE_REVIEW_TARGET_BINDING", "target_names", "Execution targets differ from the public manifest review"))
        for pin in saved_public.get("pins", []):
            if isinstance(pin, dict) and all(key in pin for key in ("path", "sha256", "roles")):
                runtime_roles = [role for role in pin["roles"] if role not in NON_RUNTIME_ROLES]
                if runtime_roles:
                    report["required_runtime_files"].append({"path": pin["path"], "sha256": pin["sha256"], "roles": runtime_roles})
                review_roles = [role for role in pin["roles"] if role in NON_RUNTIME_ROLES]
                if review_roles:
                    report["required_review_files"].append({"path": pin["path"], "sha256": pin["sha256"],
                                                           "role": "toolchain" if set(review_roles) & TOOL_PIN_ROLES else "input_binding",
                                                           "roles": review_roles})
        report["unresolved_decisions"] = saved_public.get("unresolved_decisions", [])
        report["target_reviews"] = saved_public.get("target_reviews", [])
        current = modules["input_record"].build_record(manifest_path=resolved["manifest"])
        _public_result(report, current, include_todos=False)
        original = read_json(resolved["input_record"])
        if not isinstance(original.get("errors"), list) or original.get("authorization_granted") is not False or original.get("shared_validator_sha256") != current.get("shared_validator_sha256") or original.get("shared_schema_sha256") != current.get("shared_schema_sha256"):
            report["side_errors"].append(issue("COMPUTE_INPUT_RECORD_REVISION", "$.binding.input_record", "Input receipt must use the current published schema/core and candidate03 error interface; rebuild instead of editing an old receipt"))
        if original.get("record_schema_version") != "comsol-compute-input/2.0.0" or original.get("status") != "input_files_verified" or original.get("source_manifest_sha256") != binding["manifest"]["sha256"] or original.get("source_manifest_path") != str(resolved["manifest"]) or original.get("model", {}).get("sha256") != binding["model"]["sha256"] or original.get("model", {}).get("resolved_path") != str(resolved["model"]) or original.get("errors") or original.get("side_errors"):
            report["side_errors"].append(issue("COMPUTE_INPUT_RECORD_BINDING", "binding.input_record", "Input record does not bind the current verified manifest/model"))
        if current.get("status") != "input_files_verified":
            report["side_errors"].append(issue("COMPUTE_INPUT_NOT_VERIFIED", "binding.input_record", "Current input file-contract is not verified"))
            return _finish(report)
        data = current.get("supplied_manifest", {})
        definitions = _position_definitions(data, target_names)
        report["target_position_definitions"] = definitions
        if canonical(record["target_position_definitions"]) != canonical(definitions) or set(definitions) != set(target_names):
            report["side_errors"].append(issue("COMPUTE_POSITION_DEFINITION_BINDING", "$.target_position_definitions", "Position mapping must retain each target's exact common time/frequency/parameters/mode definitions"))
        # Map the public, already revalidated source declarations to observations.
        # Do not infer legacy validity here or accept any merely pinned MPH.
        if operation == "export":
            outputs = {item["name"]: item for item in data.get("target_outputs") or []}
            legacy = {item["id"]: item for item in data.get("legacy", {}).get("solutions") or []}
            for name in target_names or []:
                required = outputs.get(name, {}).get("required_solution", {})
                if required.get("kind") == "none":
                    report["todos"].append(issue("COMPUTE_EXPORT_NO_SOLUTION_UNSUPPORTED", "target_outputs." + name,
                                                 "This runner currently verifies existing-solution exports only; do not invent a solution source"))
                elif required.get("kind") == "existing" and required.get("id") in legacy:
                    source = legacy[required["id"]]
                    source_hash = source["applies_to"]["source_model_sha256"]
                    files = [{"path": pin["path"], "sha256": pin["sha256"]} for pin in saved_public.get("pins", [])
                             if pin.get("sha256") == source_hash
                             and set(pin.get("roles", [])) & {"input_model", "source_model", "source_solution"}
                             and not set(pin.get("roles", [])) & TOOL_PIN_ROLES]
                    if not files:
                        report["side_errors"].append(issue("COMPUTE_SOLUTION_SOURCE_UNSUPPORTED", "$.target_outputs." + name,
                                                           "No scientific source file is available; public code and schemas cannot serve as solution sources"))
                    report["allowed_solution_sources"].append({"target_name": name, "legacy_id": source["id"],
                                                               "solution_id": source["solution_id"], "solution_tag": source["tag"],
                                                               "source_model_sha256": source_hash, "files": files})
    assessment = record["assessment"]
    required = {"reviewer", "scope_review", "input_inspection", "dependency_inventory", "target_reviews", "physics_scope", "solution_source"}
    if not isinstance(assessment, dict) or set(assessment) != required or not isinstance(assessment.get("reviewer"), str) or not assessment["reviewer"].strip():
        report["todos"].append(issue("COMPUTE_ASSESSMENT_PENDING", "assessment", "Named reviewer and all explicit assessment sections are required"))
    else:
        for key in ("scope_review", "input_inspection", "dependency_inventory"):
            _decision(assessment[key], report, "assessment." + key)
        targets = assessment["target_reviews"]
        if not isinstance(targets, dict) or set(targets) != set(target_names or []):
            report["side_errors"].append(issue("COMPUTE_ASSESSMENT_TARGETS", "assessment.target_reviews", "Manual target reviews must exactly cover the requested targets"))
        else:
            for name, review in targets.items():
                _decision(review, report, "assessment.target_reviews." + name)
        physics = assessment["physics_scope"]
        if not isinstance(physics, dict) or set(physics) != set(PHYSICS_KEYS):
            report["todos"].append(issue("COMPUTE_PHYSICS_REVIEW_PENDING", "assessment.physics_scope", "Separate physical initial conditions, initial guess and three study-change reviews"))
        else:
            for key in PHYSICS_KEYS:
                _decision(physics[key], report, "assessment.physics_scope." + key,
                          allow_na=key != "confirmed_physical_problem" or operation == "export")
        # A planned solve can have no pre-existing solution. Resume/export cannot.
        selected = [x for x in data.get("target_outputs") or [] if x.get("name") in (target_names or [])]
        existing = any(x.get("required_solution", {}).get("kind") == "existing" for x in selected)
        _decision(assessment["solution_source"], report, "assessment.solution_source", allow_na=operation == "solve" and not existing)
        # Scope applicability belongs to the public review. The explicit,
        # evidence-backed physical-initial-condition decision above is for this
        # scope; an unrelated component's inventory must not become a global veto.
    if pins is not None:
        if not isinstance(pins, dict):
            report["side_errors"].append(issue("COMPUTE_PIN_FORMAT", "pins", "Runner pins must map absolute file paths to SHA256"))
        else:
            for ref in report["required_runtime_files"] + report["required_review_files"]:
                if pins.get(ref["path"]) != ref["sha256"]:
                    report["side_errors"].append(issue("COMPUTE_REQUIRED_PIN_MISSING", ref["path"], "Required runtime/review input missing from pins or has a different hash"))
    return _finish(report)


def build_execution_review(public_review_path, manifest_path, input_record_path, operation, scope,
                           target_names, expected_positions, execution_config, assessment, assessment_base=None):
    """Build a compute-side record from an existing public review; never runs it."""
    manifest = Path(manifest_path).resolve(strict=True)
    data = read_json(manifest)
    model = Path(data["model"]["path"])
    model = model.resolve() if model.is_absolute() else (manifest.parent / model).resolve()
    base = Path(assessment_base).resolve() if assessment_base is not None else manifest.parent
    record = {"schema_version": VERSION, "review_revision": REVISION, "record_type": TYPE, "review_id": uuid.uuid4().hex,
              "created_at": datetime.now(timezone.utc).isoformat(), "operation": operation,
              "scope": sorted(scope), "target_names": target_names, "expected_positions": expected_positions,
              "target_position_definitions": _position_definitions(data, target_names),
              "execution_config": execution_config, "assessment": _normalise_assessment(assessment, base),
              "binding": {"public_review": file_ref(public_review_path), "manifest": file_ref(manifest),
                          "model": file_ref(model), "input_record": file_ref(input_record_path)},
              "status": "pending", "authorization_granted": False}
    report = _evaluate(record, manifest_path=manifest, model_path=model, operation=operation, scope=scope,
                       input_record_path=input_record_path, target_names=target_names, expected_positions=expected_positions,
                       execution_config=execution_config)
    record["status"] = report["status"]
    return record


def validate_operation_review(review_path, manifest_path, model_path, operation, scope, pins=None,
                              input_record_path=None, target_names=None, expected_positions=None, execution_config=None):
    """Recompute both public and compute readiness; do not trust saved ready."""
    try:
        record = read_json(review_path)
        report = _evaluate(record, manifest_path=manifest_path, model_path=model_path, operation=operation, scope=scope,
                           input_record_path=input_record_path, target_names=target_names, expected_positions=expected_positions,
                           execution_config=execution_config, pins=pins, review_path=review_path)
        if record.get("status") != report["status"]:
            report["side_errors"].append(issue("COMPUTE_REVIEW_STALE", "status", "Saved readiness differs from the current checks; create a new review"))
        return _finish(report)
    except (OSError, ImportError, ValueError, KeyError, TypeError, AttributeError) as exc:
        report = _empty_report()
        report["side_errors"].append(issue("COMPUTE_REVIEW_INVALID", "$", str(exc)))
        return _finish(report)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--manifest", required=True)
        item.add_argument("--input-record", required=True)
        item.add_argument("--operation", choices=("solve", "resume", "export"), required=True)
        item.add_argument("--scope", nargs="+", required=True)
        item.add_argument("--targets", nargs="+", required=True)
        item.add_argument("--positions", required=True, help="JSON object mapping each requested target name to its explicit position array")
        item.add_argument("--execution-config", required=True, help="JSON object containing parameters and solver_settings")
        if name == "create":
            item.add_argument("--public-review", required=True)
            item.add_argument("--assessment", required=True)
            item.add_argument("--out", required=True)
        else:
            item.add_argument("--review", required=True)
            item.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    try:
        positions = read_json(args.positions)
        execution_config = read_json(args.execution_config)
        if args.command == "create":
            result = build_execution_review(args.public_review, args.manifest, args.input_record, args.operation, args.scope,
                                            args.targets, positions, execution_config, read_json(args.assessment),
                                            Path(args.assessment).resolve().parent)
            with Path(args.out).open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        else:
            result = validate_operation_review(args.review, args.manifest, args.model, args.operation, args.scope,
                                               input_record_path=args.input_record, target_names=args.targets,
                                               expected_positions=positions, execution_config=execution_config)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result["status"] == "ready" else 2
    except (OSError, ImportError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({"status": "blocked", "errors": [], "public_errors": [], "todos": [],
                          "side_errors": [issue("COMPUTE_REVIEW_INVALID", "$", str(exc))],
                          "authorization_granted": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
