#!/usr/bin/env python3
"""Public v2 operation preparation/revalidation. Never executes any command.

Published alongside contract_v2.py; no dependency on another skill's scripts.
Readiness is declaration/evidence consistency, never authorization or scientific proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone

import contract_v2

VERSION = "2.0.0"
OPERATIONS = {"prepare", "inspect", "build", "modify", "solve", "resume", "export"}


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON number: " + value)))


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def file_ref(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Expected file: " + str(path))
    return {"path": str(path), "sha256": digest(path)}


def resolve(base, raw):
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def issue(code, path, message):
    return {"code": code, "path": path, "message": message}


def normalize_scope(scope):
    if not isinstance(scope, list) or not scope or not all(isinstance(x, str) and x.strip() == x and x for x in scope):
        raise ValueError("Scope must be an explicit nonempty identifier array")
    if len(scope) != len(set(scope)) or ("all" in scope and scope != ["all"]):
        raise ValueError("Duplicate scope or all combined with other scopes")
    return sorted(scope)


def overlaps(left, right):
    # No substring matching: unrelated labels must not silently suppress an issue.
    return bool({"all", "model"} & set(left)) or bool({"all", "model"} & set(right)) or bool(set(left) & set(right))


def spec_scope_overlap(left, right):
    """Only declared, disjoint component IDs establish independence in a spec.

    New-model specs have no model dependency graph. Unqualified/new target IDs
    therefore cannot be assumed independent merely because their text differs.
    """
    if overlaps(left, right):
        return True
    def components(values):
        result = set()
        for value in values:
            prefix, _, suffix = value.partition(":")
            if prefix == "component" and suffix:
                result.add(suffix)
            elif prefix in {"geometry", "physics", "selection", "pair", "material", "coordinate_system"} and "/" in suffix:
                result.add(suffix.split("/", 1)[0])
            else:
                return None
        return result
    left_components, right_components = components(left), components(right)
    return left_components is None or right_components is None or bool(left_components & right_components)


def _base_record(input_kind, operation, scope):
    if operation not in OPERATIONS:
        raise ValueError("Unsupported operation: " + str(operation))
    record = {
        "schema_version": VERSION, "record_type": "operation_review", "review_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(), "input_kind": input_kind,
        "input_status": {"manifest": "pending_contract_check", "mph_only": "pending_model_inspection", "new_model": "new_model_definition"}[input_kind],
        "operation": operation, "scope": normalize_scope(scope), "status": "pending",
        "manifest": None, "model": None, "model_spec": None, "target_names": [],
        "runtime_files": [], "pins": [], "unresolved_decisions": [], "target_reviews": [],
        "dependency_verification": [], "errors": [], "public_errors": [], "side_errors": [], "todos": [],
        "authorization_granted": False, "comsol_model_check_performed": False,
        "scientific_validity_verified": False,
        "limitations": ["Ready is based on declared inputs and recorded evidence, not runtime permission.",
                        "Hash/source consistency does not establish spatial, physical, or legacy-solution validity."],
    }
    here = Path(__file__).resolve().parent
    review_schema = here / "operation-review.schema.json"
    if not review_schema.is_file():
        review_schema = here.parent / "references" / "operation-review.schema.json"
    for path, role in ((Path(contract_v2.__file__), "public_contract_implementation"),
                       (Path(__file__), "public_contract_implementation"),
                       (contract_v2.SCHEMA, "public_contract_schema"),
                       (review_schema, "public_contract_schema")):
        _add_pin(record, path, role)
    return record


def _add_pin(record, path, role, expected=None, required=True):
    path = Path(path).resolve()
    check = {"path": str(path), "role": role, "required": bool(required), "status": "verified", "sha256": None}
    if not path.is_file():
        check["status"] = "missing"
        if required:
            record["public_errors"].append(issue("OP_DEPENDENCY_MISSING", str(path), "Required runtime input is missing"))
    else:
        actual = digest(path)
        check["sha256"] = actual
        if expected is not None and actual != expected:
            check["status"] = "changed"
            record["public_errors"].append(issue("OP_PIN_CHANGED", str(path), "Runtime input hash differs from manifest"))
        existing = next((pin for pin in record["pins"] if pin["path"] == str(path)), None)
        if existing:
            if role not in existing["roles"]:
                existing["roles"].append(role)
        else:
            record["pins"].append({"path": str(path), "sha256": actual, "roles": [role]})
    record["dependency_verification"].append(check)


def _runtime_inputs(record, base, runtime_files):
    if runtime_files is None:
        runtime_files = []
    if not isinstance(runtime_files, list):
        raise ValueError("runtime_files must be an array")
    for item in runtime_files:
        if not isinstance(item, dict) or set(item) != {"path", "role"} or not all(isinstance(item[k], str) and item[k].strip() for k in item):
            raise ValueError("Each runtime input requires path and role only")
        path = resolve(base, item["path"])
        record["runtime_files"].append({"path": str(path), "role": item["role"]})
        _add_pin(record, path, item["role"])


def _finish(record):
    record["pins"].sort(key=lambda x: x["path"])
    for pin in record["pins"]:
        pin["roles"].sort()
    record["status"] = "blocked" if record["public_errors"] or record["side_errors"] else "pending" if record["todos"] else "ready"
    return contract_v2.public_report(record)


def _runtime_entry(record):
    entry_roles = {"java_source", "class", "runner", "script", "adapter"}
    if record["operation"] != "prepare" and not any(entry_roles & set(pin["roles"]) for pin in record["pins"]):
        record["todos"].append(issue("OP_RUNTIME_UNDECLARED", "runtime_files", "No runtime source, class, script, or runner has been pinned"))


def _known_scope_ids(data):
    return contract_v2.known_scope_ids(data)


def _scope_expanded(data, scope):
    return contract_v2.expand_scope(data, scope)


def _inventory(record, data, groups):
    inventory = data.get("inventory", {})
    for group in groups:
        entry = inventory.get(group, {})
        if entry.get("status") != "complete":
            record["todos"].append(issue("OP_INVENTORY_PENDING", "inventory." + group,
                                         "Inventory is not complete for this operation"))


def _unresolved(record, data, requested):
    for item in data.get("unresolved") or []:
        affected = item.get("affected_scope", [])
        unknown = set(affected) - _known_scope_ids(data)
        if unknown and record["operation"] != "inspect":
            record["todos"].append(issue("OP_ISSUE_SCOPE_UNKNOWN", "unresolved." + item["id"],
                                         "Affected scope is not registered: " + ", ".join(sorted(unknown))))
        relevant = overlaps(requested, affected)
        if affected and all(value.startswith("target:") for value in affected) and all(value.startswith("target:") for value in record["scope"]):
            relevant = bool({"target:" + name for name in record["target_names"]} & set(affected))
        if record["operation"] == "inspect":
            record["unresolved_decisions"].append({"id": item["id"], "relevant": relevant, "impact": "not_applicable",
                                                   "reason": "This operation only inventories declared input; unresolved physical definitions are not changed or computed.",
                                                   "affected_scope": affected})
            continue
        impact_operation = record["operation"] if record["operation"] in ("solve", "resume", "export") else None
        impacts = item.get("impacts", {})
        effect = impacts.get(impact_operation, {}) if impact_operation else {}
        status = effect.get("effect", "unknown")
        reason = effect.get("reason", "This issue requires a scope-specific decision before modeling execution.")
        decision = {"id": item["id"], "relevant": relevant, "impact": status if relevant else "not_applicable",
                    "reason": reason if relevant else "Declared affected_scope does not intersect this explicit operation scope.",
                    "affected_scope": affected}
        record["unresolved_decisions"].append(decision)
        if not relevant:
            continue
        if status in ("blocked", "blocks"):
            record["side_errors"].append(issue("OP_UNRESOLVED_BLOCKED", "unresolved." + item["id"], reason))
        elif status not in ("none", "not_applicable"):
            record["todos"].append(issue("OP_UNRESOLVED_PENDING", "unresolved." + item["id"], reason))


def _target_state(value):
    if isinstance(value, dict):
        return value.get("status", "pending")
    return "pending"


def _targets(record, data, target_names):
    outputs = {item["name"]: item for item in data.get("target_outputs") or []}
    explicit_targets = {x[7:] for x in record["scope"] if x.startswith("target:")}
    if record["scope"] == ["all"] or "model" in record["scope"]:
        required_names = set(outputs)
    elif explicit_targets and all(x.startswith("target:") for x in record["scope"]):
        required_names = explicit_targets
    else:
        expanded = _scope_expanded(data, record["scope"])
        required_names = {name for name, output in outputs.items()
                          if output["selection_ref"]["kind"] == "global" or
                          "component:" + output["selection_ref"].get("component", "") in expanded} | explicit_targets
        if not required_names and record["operation"] in ("solve", "resume", "export"):
            required_names = set(outputs)
    if target_names is not None:
        if not isinstance(target_names, list) or len(target_names) != len(set(target_names)):
            raise ValueError("target_names must be a unique array")
        if set(target_names) != required_names:
            record["public_errors"].append(issue("OP_TARGET_SCOPE", "target_names", "Target names must cover exactly the explicit operation scope; use target:<name> scope for an intentional subset"))
    names = sorted(required_names)
    record["target_names"] = names
    if record["operation"] == "export" and not names:
        record["todos"].append(issue("OP_TARGET_UNDECLARED", "target_outputs", "Export must name at least one declared target"))
    for name in names:
        if name not in outputs:
            record["public_errors"].append(issue("OP_TARGET_UNKNOWN", "target_outputs." + str(name), "Requested target is not registered"))
            continue
        item = outputs[name]
        pending_fields = [key for key in ("expression", "unit", "coordinate_system", "statistic", "time", "frequency", "parameters", "mode", "required_solution")
                          if _target_state(item.get(key)) == "pending"]
        if item.get("selection_ref", {}).get("kind") == "pending":
            pending_fields.append("selection_ref")
        if item.get("status") == "pending":
            pending_fields.append("definition_status")
        target_status = "not_applicable" if item.get("status") == "not_applicable" else "pending" if pending_fields else "complete"
        record["target_reviews"].append({"name": name, "status": target_status, "pending_fields": pending_fields})
        if pending_fields and record["operation"] != "inspect":
            record["todos"].append(issue("OP_TARGET_PENDING", "target_outputs." + name, "Pending fields: " + ", ".join(pending_fields)))
        if record["operation"] == "export":
            if target_status == "not_applicable":
                record["side_errors"].append(issue("OP_TARGET_NOT_APPLICABLE", "target_outputs." + name,
                                                    "An explicitly not-applicable target is not an exportable quantity"))
            solution = item.get("required_solution", {})
            if solution.get("kind") == "planned":
                record["side_errors"].append(issue("OP_SOLUTION_MISSING", "target_outputs." + name,
                                                    "Export requires an existing solution; this target declares a planned solution. No solve is implied."))
            elif solution.get("status") == "complete" and solution.get("kind") != "existing":
                record["todos"].append(issue("OP_SOLUTION_UNCONFIRMED", "target_outputs." + name,
                                             "Existing solution identity and source must be explicit; text is not interpreted as availability."))
            elif solution.get("kind") == "existing":
                legacy = next((entry for entry in data.get("legacy", {}).get("solutions") or [] if entry["id"] == solution["id"]), None)
                if legacy is None or legacy.get("validity") != "valid":
                    record["side_errors"].append(issue("OP_SOLUTION_INVALID", "target_outputs." + name,
                                                       "Existing solution has no recorded valid applicability declaration"))
                else:
                    applicable = legacy["applies_to"]
                    if applicable["model_sha256"] != data["model"]["sha256"]:
                        record["side_errors"].append(issue("OP_SOLUTION_APPLICABILITY", "legacy.solutions." + legacy["id"],
                                                           "Recorded solution applicability is for a different model, not this operation input"))
                    runtime_hashes = {data["model"]["sha256"]} | {dep.get("sha256") for dep in data.get("dependencies") or []
                                      if dep.get("category") == "runtime" and dep.get("role") in ("source_model", "source_solution")
                                      and "export" in dep.get("applies_to", []) and dep.get("status") == "present"}
                    if applicable["source_model_sha256"] not in runtime_hashes:
                        record["side_errors"].append(issue("OP_SOLUTION_PIN_MISSING", "legacy.solutions." + legacy["id"],
                                                           "Source solution must be the input model or a declared export runtime dependency"))
                    for dimension in ("parameters", "time", "frequency", "mode"):
                        desired = item[dimension]
                        available = applicable.get(dimension, {})
                        if desired["status"] == "complete" and desired != available:
                            # Do not parse arbitrary scientific range expressions or infer containment.
                            if desired.get("value") != available.get("value") or available.get("status") != "complete":
                                record["todos"].append(issue("OP_SOLUTION_RANGE_PENDING", "target_outputs." + name + "." + dimension,
                                                             "Requested position needs an explicit applicability review; no range containment is inferred."))


def build_review(manifest_path, operation, scope, target_names=None, runtime_files=None):
    """Create a declaration-based review object; caller/CLI saves a new file."""
    manifest_path = Path(manifest_path).resolve(strict=True)
    data = read_json(manifest_path)
    record = _base_record("manifest", operation, scope)
    record["manifest"] = file_ref(manifest_path)
    _add_pin(record, manifest_path, "input_manifest")
    report = contract_v2.validate_manifest(manifest_path)
    record["input_status"] = "rejected" if report.get("public_errors") else "input_files_verified"
    record["public_errors"].extend(report.get("public_errors", []))
    record["side_errors"].extend(report.get("side_errors", []))
    if operation != "inspect":
        record["todos"].extend(item for item in report.get("todos", []) if item["code"] == "LINEAGE_PENDING")
    if report.get("public_errors"):
        return _finish(record)
    model = data.get("model")
    model_path = resolve(manifest_path.parent, model["path"])
    record["model"] = {"path": str(model_path), "sha256": model["sha256"]}
    _add_pin(record, model_path, "input_model", model["sha256"])
    known = _known_scope_ids(data)
    for scope_id in record["scope"]:
        if scope_id not in known:
            record["public_errors"].append(issue("OP_SCOPE_UNKNOWN", "scope", "Unknown scope identifier: " + scope_id))
    requested = _scope_expanded(data, record["scope"])
    requested.update("dependency:" + dep["id"] for dep in data.get("dependencies") or []
                     if dep["category"] == "runtime" and (operation == "prepare" or operation in dep["applies_to"]))
    _targets(record, data, target_names)
    _unresolved(record, data, requested)
    if operation != "inspect":
        _inventory(record, data, ["dependencies"])
    if operation in ("solve", "resume", "export"):
        _inventory(record, data, ["components", "selections", "pairs", "materials", "target_outputs"])
        for check_name in ("structure", "reload"):
            status = data.get("checks", {}).get(check_name, {}).get("status")
            if status in ("failed", "blocked"):
                record["side_errors"].append(issue("OP_CHECK_BLOCKED", "checks." + check_name, "Required model check is " + status))
            elif status != "passed":
                record["todos"].append(issue("OP_CHECK_PENDING", "checks." + check_name, "Required model check is not passed"))
    for dependency in data.get("dependencies") or []:
        if dependency.get("category") == "runtime" and (operation == "prepare" or operation in dependency.get("applies_to", [])):
            if dependency.get("status") == "present":
                _add_pin(record, resolve(manifest_path.parent, dependency["path"]), dependency.get("role", "runtime"), dependency.get("sha256"), dependency.get("required", True))
            elif dependency.get("required", True):
                record["side_errors"].append(issue("OP_DEPENDENCY_MISSING", "dependencies." + str(dependency.get("id", "")), "Required runtime dependency is unavailable"))
    _runtime_inputs(record, manifest_path.parent, runtime_files)
    _runtime_entry(record)
    return _finish(record)


def build_mph_review(model_path, scope=None, runtime_files=None):
    """Only-MPH input can be prepared for an authorized read-only inspection."""
    record = _base_record("mph_only", "inspect", scope or ["all"])
    if record["scope"] != ["all"]:
        record["side_errors"].append(issue("OP_SCOPE_UNINSPECTED", "scope", "Uninspected MPH cannot assert internal scope identifiers"))
    record["model"] = file_ref(model_path)
    _add_pin(record, model_path, "input_model")
    _runtime_inputs(record, Path(model_path).resolve().parent, runtime_files)
    _runtime_entry(record)
    record["limitations"].append("pending_model_inspection: only file bytes are known; ready applies only to read-only inventory, not model internals.")
    return _finish(record)


def build_source_review(spec_path, scope=None, runtime_files=None):
    """Prepare a declared new-model build, with no invented input MPH/manifest."""
    spec_path = Path(spec_path).resolve(strict=True)
    spec = read_json(spec_path)
    if not isinstance(spec, dict):
        raise ValueError("new_model_spec must be a JSON object")
    record = _base_record("new_model", "build", scope or ["all"])
    record["model_spec"] = file_ref(spec_path)
    _add_pin(record, spec_path, "model_spec")
    if spec.get("schema_version") != VERSION or spec.get("record_type") != "new_model_spec":
        record["public_errors"].append(issue("OP_SPEC_FORMAT", "model_spec", "Expected explicit v2 new_model_spec"))
    if not isinstance(spec.get("reason"), str) or not spec["reason"].strip():
        record["public_errors"].append(issue("OP_SPEC_REASON", "model_spec.reason", "New model with no input MPH needs an explicit reason"))
    allowed = spec.get("scope_ids", [])
    if not isinstance(allowed, list) or not allowed or any(not isinstance(x, str) or not x.strip() for x in allowed) or len(set(allowed)) != len(allowed) or any(x not in allowed and x != "all" for x in record["scope"]):
        record["public_errors"].append(issue("OP_SCOPE_UNKNOWN", "scope", "New-model scope must be explicitly declared by the spec"))
        return _finish(record)
    if spec.get("definition_status") != "complete":
        record["todos"].append(issue("OP_SPEC_PENDING", "model_spec.definition_status", "New-model definition is not complete"))
    if not isinstance(spec.get("unresolved"), list):
        record["public_errors"].append(issue("OP_SPEC_INVENTORY", "model_spec.unresolved", "Spec must explicitly inventory unresolved issues"))
    else:
        main_schema = read_json(contract_v2.SCHEMA)
        issue_schema = main_schema["properties"]["unresolved"]["items"]
        seen = set()
        for item in spec["unresolved"]:
            if contract_v2.schema_errors(item, issue_schema, main_schema):
                record["public_errors"].append(issue("OP_SPEC_ISSUE", "model_spec.unresolved", "Issue must use the common unresolved definition, including owner/evidence/question/impacts"))
                continue
            if item["id"] in seen:
                record["public_errors"].append(issue("OP_SPEC_ISSUE", "model_spec.unresolved", "Duplicate unresolved ID"))
            seen.add(item["id"])
            if any(x != "all" and x not in allowed for x in item["affected_scope"]):
                record["public_errors"].append(issue("OP_SCOPE_UNKNOWN", "model_spec.unresolved." + item["id"], "Unresolved affected_scope is absent from spec scope_ids"))
            relevant = spec_scope_overlap(record["scope"], item["affected_scope"])
            if relevant:
                record["todos"].append(issue("OP_UNRESOLVED_PENDING", "model_spec.unresolved." + item["id"], item["question"]))
            for evidence in item["evidence"]:
                _add_pin(record, resolve(spec_path.parent, evidence["path"]), "issue_evidence", evidence["sha256"])
            record["unresolved_decisions"].append({"id": item["id"], "relevant": relevant,
                                                   "impact": "pending" if relevant else "not_applicable",
                                                   "reason": item["question"] if relevant else "Declared affected_scope does not intersect this explicit build scope.",
                                                   "affected_scope": item["affected_scope"]})
    runtime = spec.get("runtime_files")
    if not isinstance(runtime, list) or not runtime:
        record["todos"].append(issue("OP_RUNTIME_UNDECLARED", "model_spec.runtime_files", "Declare every source/script/class/config needed to build"))
    else:
        _runtime_inputs(record, spec_path.parent, runtime)
    _runtime_inputs(record, spec_path.parent, runtime_files)
    _runtime_entry(record)
    record["limitations"].append("No input model exists. Readiness is limited to executing the reviewed build definition; saved model checks remain unperformed.")
    return _finish(record)


def verify_review(review_path, manifest_path=None, operation=None, scope=None):
    """Rebuild the declaration assessment and require identical input pins."""
    review_path = Path(review_path).resolve(strict=True)
    saved = read_json(review_path)
    errors = []
    here = Path(__file__).resolve().parent
    schema_path = here / "operation-review.schema.json"
    if not schema_path.is_file():
        schema_path = here.parent / "references" / "operation-review.schema.json"
    schema = read_json(schema_path)
    contract_v2.audit_schema(schema)
    errors.extend(issue("OP_REVIEW_SCHEMA", path, message) for path, message in contract_v2.schema_errors(saved, schema, schema))
    if errors:
        return contract_v2.public_report({"status": "blocked", "public_errors": errors, "side_errors": [], "todos": [],
                "authorization_granted": False, "comsol_model_check_performed": False, "scientific_validity_verified": False})
    if saved.get("schema_version") != VERSION or saved.get("record_type") != "operation_review":
        errors.append(issue("OP_REVIEW_VERSION", "schema_version", "Unsupported review version/type"))
    expected_fields = set(_base_record("manifest", "prepare", ["all"]))
    if set(saved) != expected_fields:
        errors.append(issue("OP_REVIEW_FORMAT", "review", "Unexpected or missing review fields"))
    if operation is not None and operation != saved.get("operation"):
        errors.append(issue("OP_OPERATION_MISMATCH", "operation", "Review is for a different operation"))
    if scope is not None and normalize_scope(scope) != saved.get("scope"):
        errors.append(issue("OP_SCOPE_MISMATCH", "scope", "Review is for a different scope"))
    if saved.get("authorization_granted") is not False:
        errors.append(issue("OP_AUTHORIZATION_INVALID", "authorization_granted", "Review cannot grant authorization"))
    try:
        kind = saved.get("input_kind")
        if kind == "manifest":
            original = Path(saved["manifest"]["path"]).resolve()
            if manifest_path is not None and Path(manifest_path).resolve() != original:
                errors.append(issue("OP_MANIFEST_MISMATCH", "manifest", "Review binds a different manifest"))
            current = build_review(original, saved["operation"], saved["scope"], saved["target_names"], saved["runtime_files"])
        elif kind == "mph_only":
            if manifest_path is not None:
                errors.append(issue("OP_MANIFEST_MISMATCH", "manifest", "MPH-only review has no manifest binding"))
            if saved.get("operation") != "inspect" or saved.get("manifest") is not None:
                errors.append(issue("OP_INPUT_KIND", "input_kind", "MPH-only review is restricted to inspect with null manifest"))
            current = build_mph_review(saved["model"]["path"], saved["scope"], saved["runtime_files"])
        elif kind == "new_model":
            if manifest_path is not None:
                errors.append(issue("OP_MANIFEST_MISMATCH", "manifest", "New-model review has no input manifest"))
            if saved.get("operation") != "build" or saved.get("manifest") is not None or saved.get("model") is not None:
                errors.append(issue("OP_INPUT_KIND", "input_kind", "New-model review is restricted to build with null manifest/model"))
            # Declared runtime files already include spec files; avoid duplicate supplemental entries.
            spec = read_json(saved["model_spec"]["path"])
            declared = [(str(resolve(Path(saved["model_spec"]["path"]).parent, x["path"])), x["role"]) for x in spec.get("runtime_files", [])]
            supplemental = []
            for item in saved["runtime_files"]:
                key = (item["path"], item["role"])
                if key in declared:
                    declared.remove(key)
                else:
                    supplemental.append(item)
            current = build_source_review(saved["model_spec"]["path"], saved["scope"], supplemental)
        else:
            raise ValueError("Unknown input_kind")
        expected = {x["path"]: x["sha256"] for x in current["pins"]}
        actual = {x["path"]: x["sha256"] for x in saved.get("pins", [])}
        if len(actual) != len(saved.get("pins", [])):
            errors.append(issue("OP_PIN_DUPLICATE", "pins", "Duplicate pin paths"))
        for path, value in expected.items():
            if path not in actual:
                errors.append(issue("OP_PIN_MISSING", "pins", "Required input omitted from pins: " + path))
            elif actual[path] != value:
                errors.append(issue("OP_PIN_CHANGED", "pins", "Prepared input changed: " + path))
        for path in actual.keys() - expected.keys():
            errors.append(issue("OP_PIN_UNDECLARED", "pins", "Pin has no runtime declaration: " + path))
        if saved.get("pins") != current["pins"] and actual == expected:
            errors.append(issue("OP_PIN_DECLARATION", "pins", "Pin roles/order differ from derived runtime declarations"))
        for key in ("manifest", "model", "model_spec", "input_status", "unresolved_decisions", "target_reviews", "dependency_verification", "status", "errors", "public_errors", "side_errors", "todos"):
            if saved.get(key) != current.get(key):
                errors.append(issue("OP_REVIEW_STALE", key, "Saved assessment differs from current derived assessment"))
        errors.extend(current["public_errors"])
        return contract_v2.public_report({"status": "blocked" if errors or current["side_errors"] else current["status"], "public_errors": errors,
                "side_errors": current["side_errors"], "todos": current["todos"], "authorization_granted": False,
                "comsol_model_check_performed": False, "scientific_validity_verified": False,
                "review_sha256": digest(review_path)})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(issue("OP_REVIEW_INVALID", "review", str(exc)))
        return contract_v2.public_report({"status": "blocked", "public_errors": errors, "side_errors": [], "todos": [],
                "authorization_granted": False, "comsol_model_check_performed": False, "scientific_validity_verified": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest")
    source.add_argument("--mph")
    source.add_argument("--new-model-spec")
    prepare.add_argument("--operation", choices=sorted(OPERATIONS), required=True)
    prepare.add_argument("--scope", nargs="+", required=True)
    prepare.add_argument("--targets", nargs="*")
    prepare.add_argument("--runtime-files", help="JSON array of extra path/role declarations")
    prepare.add_argument("--out", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--review", required=True)
    verify.add_argument("--manifest")
    verify.add_argument("--operation", choices=sorted(OPERATIONS), required=True)
    verify.add_argument("--scope", nargs="+", required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = verify_review(args.review, args.manifest, args.operation, args.scope)
        else:
            runtime = read_json(args.runtime_files) if args.runtime_files else None
            if args.manifest:
                result = build_review(args.manifest, args.operation, args.scope, args.targets, runtime)
            elif args.mph:
                if args.operation != "inspect":
                    raise ValueError("Only-MPH review permits only inspect")
                result = build_mph_review(args.mph, args.scope, runtime)
            else:
                if args.operation != "build":
                    raise ValueError("New-model-spec review permits only build")
                result = build_source_review(args.new_model_spec, args.scope, runtime)
            with Path(args.out).open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ready" else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(contract_v2.public_report({"status": "blocked", "public_errors": [issue("OP_REVIEW_INVALID", "input", str(exc))],
                          "side_errors": [], "todos": [], "authorization_granted": False}), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
