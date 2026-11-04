#!/usr/bin/env python3
"""Prepare, execute and inspect isolated computation evidence (Python stdlib).

This is an evidence wrapper, not a COMSOL API adapter or scientific validator.
It trusts the operator's explicit script review and current authorization.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid


VERSION = "2.0.0"
RESERVED = {"config.json", "bundle.json", "started.json", "process.json", "summary.json",
            "stdout.log", "stderr.log", "output-record.json"}
STATE_KEYS = {"position", "initial_fields", "motion_state", "solution_source"}


class Invalid(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise Invalid(message)


def read_json(path):
    def no_constant(value):
        raise Invalid("Non-finite JSON number: " + value)
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        return json.load(stream, parse_constant=no_constant, object_pairs_hook=no_duplicates)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def same_json(left, right):
    """Compare JSON values without Python's False == 0 / True == 1 coercion."""
    return canonical(left) == canonical(right)


def target_position_map(value, names):
    """Validate the private normalized map; meanings remain in the manifest."""
    need(isinstance(value, dict) and set(value) == set(names),
         "expected_positions must map every target name to its positions; recreate older list-based configurations")
    for name, positions in value.items():
        need(isinstance(positions, list) and positions,
             "Each target requires an explicit nonempty position array: " + name)
        need(len({canonical(item) for item in positions}) == len(positions),
             "A target position array contains duplicates: " + name)
    return value


def public_schema_paths():
    """Resolve the same per-skill schema locations used by the public modules."""
    here = Path(__file__).resolve().parent
    result = []
    for name in ("model-manifest.schema.json", "operation-review.schema.json"):
        local = here / name
        actual = local if local.is_file() else here.parent / "references" / name
        actual = actual.resolve(strict=True)
        need(actual.is_file(), "Actual public schema is missing: " + str(actual))
        result.append(actual)
    return result


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value, exclusive=False):
    with Path(path).open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def input_path(value, base):
    need(isinstance(value, str) and value.strip(), "Input path must be a nonempty string")
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    path = path.resolve(strict=True)
    need(path.is_file(), "Input is not a file: " + str(path))
    return str(path)


def inside(root, relative):
    need(isinstance(relative, str) and relative.strip(), "Artifact path must be a nonempty string")
    p = Path(relative)
    need(not p.is_absolute() and not p.drive and ".." not in p.parts,
         "Artifact path must be relative without '..': " + relative)
    target = (root / p).resolve()
    need(target != root and target.is_relative_to(root), "Artifact escapes bundle: " + relative)
    return target


def validate_config(raw, base):
    need(isinstance(raw, dict), "Configuration must be an object")
    cfg = dict(raw)
    need(cfg.get("schema_version") == VERSION, "Unsupported configuration schema_version")
    op = cfg.get("operation")
    need(op in ("solve", "resume", "export"), "operation must be solve, resume or export")
    need(cfg.get("execution_kind") in ("simulation", "comsol"),
         "execution_kind must explicitly distinguish simulation from comsol")
    for key in ("model", "manifest", "input_record", "operation_review"):
        cfg[key] = input_path(cfg.get(key), base)
    scope = cfg.get("scope")
    need(isinstance(scope, list) and scope and all(isinstance(x, str) and x.strip() for x in scope)
         and len(scope) == len(set(scope)), "scope must be an explicit nonempty unique string array")
    names = cfg.get("target_names")
    need(isinstance(names, list) and names and all(isinstance(x, str) and x.strip() for x in names)
         and len(names) == len(set(names)), "target_names must be nonempty unique names")
    for key in ("scripts", "dependencies"):
        need(isinstance(cfg.get(key), list), key + " must be a path array")
        cfg[key] = [input_path(x, base) for x in cfg[key]]
    need(cfg["scripts"], "At least one reviewed script must be pinned")
    argv = cfg.get("argv")
    need(isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv),
         "argv must be a nonempty string array")
    need(Path(argv[0]).is_absolute(), "argv[0] must be an absolute executable path")
    cfg["argv"] = [input_path(argv[0], base)] + argv[1:]
    review = cfg.get("script_review", {})
    need(isinstance(review, dict) and review.get("reviewed") is True
         and review.get("operation") == op and isinstance(review.get("notes"), str)
         and review["notes"].strip(), "Explicit script_review for this operation is required")
    need(review.get("calls_solver") is (op != "export"),
         "script_review.calls_solver must be true for solve/resume and false for export")
    target_position_map(cfg.get("expected_positions"), names)
    for key in ("parameters", "solver_settings"):
        need(isinstance(cfg.get(key), dict), key + " must be an object")
    need(isinstance(cfg.get("outputs"), list) and cfg["outputs"], "outputs must be a nonempty array")
    for output in cfg["outputs"]:
        need(isinstance(output, dict) and isinstance(output.get("role"), str) and output["role"],
             "Each output needs path and role")
        need(isinstance(output.get("path"), str), "Output path missing")
    if op != "export":
        need(any(o["role"] == "solved_model" and Path(o["path"]).suffix.lower() == ".mph"
                 for o in cfg["outputs"]), "solve/resume requires a solved_model .mph output")
    need(sum(o["role"] == "solver_observation" for o in cfg["outputs"]) == 1,
         "Every operation requires one independent solver_observation output")
    need(isinstance(cfg.get("logs"), list) and all(isinstance(x, str) for x in cfg["logs"]),
         "logs must be an array; raw stdout/stderr are preserved separately")
    validate_log_policy(cfg)
    resource = cfg.get("resources")
    need(isinstance(resource, dict) and set(resource) == {"timeout_seconds"},
         "resources must contain only timeout_seconds; hard memory/CPU limits are unsupported")
    timeout = resource["timeout_seconds"]
    need(timeout is None or (type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0),
         "timeout_seconds must be null or a positive finite number")
    if op == "resume":
        cfg["checkpoint"] = input_path(cfg.get("checkpoint"), base)
        state = cfg.get("resume_expected")
        need(isinstance(state, dict) and set(state) == STATE_KEYS
             and all(state[k] not in (None, "", {}, []) for k in STATE_KEYS),
             "resume_expected needs position, initial_fields, motion_state and solution_source")
    return cfg


def review_module():
    """Load only this skill's sibling review module; never another skill's script."""
    path = Path(__file__).resolve().with_name("compute_operation_review.py")
    spec = importlib.util.spec_from_file_location("comsol_compute_operation_review", path)
    need(spec is not None and spec.loader is not None, "Operation review module unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def validate_review(cfg, pins=None):
    # Read-only prepare/inspect must not create bytecode for lazy imports either.
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        module = review_module()
        report = module.validate_operation_review(
            cfg["operation_review"], cfg["manifest"], cfg["model"], cfg["operation"], cfg["scope"],
            pins=pins, input_record_path=cfg["input_record"], target_names=cfg["target_names"],
            expected_positions=cfg["expected_positions"],
            execution_config={"parameters": cfg["parameters"], "solver_settings": cfg["solver_settings"]})
    finally:
        sys.dont_write_bytecode = previous_bytecode
    need(isinstance(report, dict) and report.get("status") == "ready",
         "Operation review is not ready for this scope: " + canonical(report))
    return report


def pin_files(cfg, source):
    """Expand referenced runtime files, separately retaining review provenance."""
    reviewed = validate_review(cfg)
    roles = {}
    public_runtime = reviewed.get("required_runtime_files")
    need(isinstance(public_runtime, list), "Review must provide required_runtime_files")
    declared_runtime = {}
    public_roles = {}
    for item in public_runtime:
        need(isinstance(item, dict) and isinstance(item.get("path"), str)
             and Path(item["path"]).is_absolute() and isinstance(item.get("sha256"), str)
             and isinstance(item.get("roles"), list) and item["roles"]
             and all(isinstance(role, str) and role for role in item["roles"]),
             "Reviewed runtime files require absolute path, hash and public roles")
        path = str(Path(item["path"]).resolve(strict=True))
        need(path not in declared_runtime, "Duplicate reviewed runtime path: " + path)
        declared_runtime[path] = item["sha256"]
        public_roles[path] = set(item["roles"])
    for path in [str(source), *cfg["scripts"], *cfg["dependencies"]]:
        resolved = str(Path(path).resolve(strict=True))
        need(resolved in declared_runtime and declared_runtime[resolved] == digest(resolved),
             "Actual run config/script/dependency was not pinned by the public review: " + resolved)

    def add(path, role, expected=None):
        path = str(Path(path).resolve(strict=True))
        need(Path(path).is_file(), "Pinned input is not a file: " + path)
        if expected is not None:
            need(digest(path) == expected, "Review file hash mismatch: " + path)
        roles.setdefault(path, []).append(role)

    add(source, "run_config_source")
    add(cfg["model"], "input_model")
    add(cfg["argv"][0], "executable")
    for key in ("manifest", "input_record", "operation_review"):
        add(cfg[key], key)
    for path in cfg["scripts"]:
        add(path, "runtime_script")
    for path in cfg["dependencies"]:
        add(path, "explicit_runtime_dependency")
    for key, role in (("required_runtime_files", "manifest_runtime_dependency"),
                      ("required_review_files", "review_provenance")):
        need(isinstance(reviewed.get(key), list), "Review must provide " + key)
        for item in reviewed[key]:
            need(isinstance(item, dict) and isinstance(item.get("path"), str)
                 and Path(item["path"]).is_absolute() and isinstance(item.get("sha256"), str),
                 "Malformed reviewed file in " + key)
            add(item["path"], role, item["sha256"])
            if key == "required_runtime_files":
                for declared_role in sorted(public_roles[str(Path(item["path"]).resolve())]):
                    add(item["path"], "public_runtime:" + declared_role)
    # The wrappers used to produce/interpret a run are reproducibility inputs too.
    for path in Path(__file__).resolve().parent.glob("*.py"):
        add(path, "compute_tool_implementation")
    for path in public_schema_paths():
        add(path, "public_contract_schema")
    if cfg["operation"] == "resume":
        add(cfg["checkpoint"], "checkpoint")
    pins = {path: digest(path) for path in roles}
    validate_review(cfg, pins=pins)
    runtime_paths = sorted(path for path, labels in roles.items()
                           if any(label in ("manifest_runtime_dependency", "explicit_runtime_dependency")
                                  for label in labels))
    # Run configuration/review documents are pinned for this operation, but are
    # not scientific external state for checkpoint equivalence. Scripts already
    # have their own binding; source solution/data/class dependencies remain here.
    checkpoint_paths = sorted(path for path in runtime_paths
                              if path != str(Path(source).resolve()) and path not in cfg["scripts"])
    source_solution_paths = sorted(path for path in runtime_paths
                                   if public_roles.get(path, set()) & {"source_model", "source_solution"})
    allowed_solution_sources = reviewed.get("allowed_solution_sources")
    need(isinstance(allowed_solution_sources, list), "Review must provide allowed_solution_sources")
    definitions = reviewed.get("target_position_definitions")
    need(isinstance(definitions, dict) and set(definitions) == set(cfg["target_names"]),
         "Review must trace each target position map to its public location definitions")
    return pins, roles, runtime_paths, checkpoint_paths, source_solution_paths, allowed_solution_sources, definitions


def artifacts(cfg):
    return [cfg.get("evidence")] + cfg["logs"] + [o["path"] for o in cfg["outputs"]]


def validate_artifact_paths(root, cfg):
    paths = [inside(root, p) for p in artifacts(cfg)]
    need(len(set(paths)) == len(paths), "Artifact paths must be distinct")
    for path in paths:
        need(path.name not in RESERVED, "Reserved artifact name: " + path.name)
    # A directory artifact would block another artifact's file path.
    need(not any(a != b and a in b.parents for a in paths for b in paths),
         "Artifact paths overlap as parent and child")
    return paths


def resume_binding(cfg, pins, runtime_paths=None):
    checkpoint = read_json(cfg["checkpoint"])
    expected = {"model_sha256": pins[cfg["model"]],
                "script_hashes": {p: pins[p] for p in cfg["scripts"]},
                "dependency_hashes": {p: pins[p] for p in (runtime_paths if runtime_paths is not None else cfg["dependencies"])},
                "parameters": cfg["parameters"], "solver_settings": cfg["solver_settings"]}
    need(same_json(checkpoint.get("binding"), expected), "Checkpoint input/script/parameter/solver binding mismatch")
    need(same_json(checkpoint.get("state"), cfg["resume_expected"]), "Checkpoint resume state mismatch")


def prepare(config_path, root_path):
    source = Path(config_path).resolve(strict=True)
    raw = read_json(source)
    need(isinstance(raw, dict) and raw.get("schema_version") == VERSION,
         "Only explicit 2.0.0 configurations are accepted; no implicit migration")
    need(raw.get("operation") in ("solve", "resume", "export"), "Unknown operation")
    root = Path(root_path).resolve()
    run_id = uuid.uuid4().hex
    directory = root / run_id
    reasons = []
    try:
        cfg = validate_config(raw, source.parent)
        validate_artifact_paths(directory, cfg)
        pins, roles, runtime_paths, checkpoint_paths, source_solution_paths, allowed_sources, definitions = pin_files(cfg, source)
        if cfg["operation"] == "resume":
            resume_binding(cfg, pins, checkpoint_paths)
        kind = "executable"
    except (OSError, ValueError, TypeError, KeyError, LookupError, ImportError) as error:
        # A plan can be delivered despite missing inputs. It is never executable.
        cfg = raw
        pins = {str(source): digest(source)}
        roles = {str(source): ["incomplete_plan_source"]}
        runtime_paths = []
        checkpoint_paths = []
        source_solution_paths = []
        allowed_sources = []
        definitions = {}
        reasons.append(str(error))
        kind = "plan"
    fingerprint = hashlib.sha256(canonical({"config": cfg, "pins": pins}).encode("utf-8")).hexdigest()
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "config.json", cfg, exclusive=True)
    write_json(directory / "bundle.json", {"schema_version": VERSION, "run_id": run_id,
               "fingerprint": fingerprint, "pins": pins, "config_source": str(source),
               "kind": kind, "preparation_issues": reasons, "pin_roles": roles,
               "runtime_paths": runtime_paths, "checkpoint_dependency_paths": checkpoint_paths,
               "source_solution_paths": source_solution_paths, "allowed_solution_sources": allowed_sources,
               "target_position_definitions": definitions,
               "prepared_ns": time.time_ns()}, exclusive=True)
    status = "executable_bundle_prepared_not_executed" if kind == "executable" else "plan_prepared_not_executable"
    return {"status": status, "bundle": str(directory), "run_id": run_id,
            "fingerprint": fingerprint, "preparation_issues": reasons,
            "executable": kind == "executable",
            "authorization_granted": False, "completion_evidence_accepted": False}


def load_bundle(directory):
    root = Path(directory).resolve(strict=True)
    meta = read_json(root / "bundle.json")
    cfg = read_json(root / "config.json")
    need(meta.get("schema_version") == VERSION, "Unsupported bundle schema_version")
    need(re.fullmatch(r"[0-9a-f]{32}", meta.get("run_id", "")), "Invalid run_id")
    need(meta.get("kind") in ("plan", "executable"), "Invalid bundle kind")
    need(isinstance(meta.get("pins"), dict) and meta["pins"], "Missing input pins")
    actual = hashlib.sha256(canonical({"config": cfg, "pins": meta["pins"]}).encode("utf-8")).hexdigest()
    need(actual == meta.get("fingerprint"), "Configuration snapshot or pins fingerprint mismatch")
    for path, expected in meta["pins"].items():
        need(Path(path).is_absolute() and digest(path) == expected, "Pinned file changed: " + path)
    if meta["kind"] == "plan":
        return root, cfg, meta
    validate_config(cfg, root)
    source_name = meta.get("config_source")
    need(isinstance(source_name, str) and Path(source_name).is_absolute(),
         "Reviewed configuration source must be an absolute pinned file")
    source = Path(source_name).resolve(strict=True)
    need(str(source) in meta["pins"] and digest(source) == meta["pins"][str(source)],
         "Reviewed configuration source is not pinned or changed")
    # The local fingerprint is reproducible, not an approval signature. A
    # rewritten snapshot must not select unreviewed settings while reusing the
    # original source's public review/pins. Normalize relative inputs against
    # the original source directory exactly as prepare() did.
    reviewed_cfg = validate_config(read_json(source), source.parent)
    need(same_json(cfg, reviewed_cfg), "Configuration snapshot differs from pinned reviewed source")
    validate_artifact_paths(root, cfg)
    validate_review(cfg, pins=meta["pins"])
    # Rebuild the expected set to reject incomplete/tampered pin registries as well.
    current_pins, roles, runtime_paths, checkpoint_paths, source_solution_paths, allowed_sources, definitions = pin_files(cfg, meta["config_source"])
    need(same_json(current_pins, meta["pins"]) and same_json(roles, meta.get("pin_roles"))
         and same_json(runtime_paths, meta.get("runtime_paths"))
         and same_json(checkpoint_paths, meta.get("checkpoint_dependency_paths"))
         and same_json(source_solution_paths, meta.get("source_solution_paths"))
         and same_json(allowed_sources, meta.get("allowed_solution_sources"))
         and same_json(definitions, meta.get("target_position_definitions")),
         "Run pins do not cover the current reviewed dependencies")
    if cfg["operation"] == "resume":
        resume_binding(cfg, meta["pins"], checkpoint_paths)
    return root, cfg, meta


def validate_log_policy(cfg):
    """Private execution policy, bound by the complete configuration fingerprint.

    A map is exact and authoritative when present. Legacy uniform policy remains
    explicit; neither mode guesses codecs or silently retries another encoding.
    """
    logs = cfg.get("logs")
    need(isinstance(logs, list) and all(isinstance(x, str) and x.strip() for x in logs),
         "logs must declare nonempty relative paths")
    paths = ["stdout.log", "stderr.log", *logs]
    need(len(paths) == len(set(paths)), "Log source paths must be unique")
    if "log_encodings" in cfg:
        policy = cfg["log_encodings"]
        need(isinstance(policy, dict) and set(policy) == set(paths),
             "log_encodings must exactly cover stdout.log, stderr.log and declared logs")
    else:
        policy = {path: cfg.get("log_encoding") for path in paths}
    for path, encoding in policy.items():
        need(isinstance(encoding, str) and encoding.strip(), "Explicit log encoding required for source: " + path)
        try:
            codec = codecs.lookup(encoding)
            need(isinstance(codec.decode(b"")[0], str), "Log codec must decode bytes to text")
        except (LookupError, ValueError, TypeError) as error:
            raise Invalid("Unsupported log encoding for source " + path + ": " + repr(encoding)) from error
    return dict(policy)


def log_encoding_for(cfg, relative):
    policy = validate_log_policy(cfg)
    need(relative in policy, "Undeclared log source: " + str(relative))
    return policy[relative]


def _log_findings(text, path):
    hits = []
    zero_count = re.compile(r"^\s*(?:(?:number of|total)\s+)?(?:errors?|exceptions?|failures?|failed|错误|异常|失败)\s*[:=]\s*0\s*[.!。]?\s*$", re.I)
    fatal = re.compile(r"\b(?:errors?|exceptions?|failed|failures?|fatal)\b|\b(?:did not converge|not converged|no convergence|cannot create native file)\b|错误|异常|失败|不收敛|未收敛|未能收敛|未找到解|无法找到解|无法求解|未达到收敛|未通过", re.I)
    # A loaded Error/Exception class is not a thrown exception. Only exempt
    # the complete info/class,load form observed in the local JVM; unsupported
    # decorators/sources remain subject to the normal failure classifier.
    # Do not strip the line or allow arbitrary suffix text after the source URI.
    class_load_info = re.compile(
        r"\[[0-9]+(?:\.[0-9]+)?s\]\[info\]\[class,load\] "
        r"[A-Za-z_$][A-Za-z0-9_.$]* source: "
        r"(?:jrt:/java\.base"
        r"|file:/(?:[A-Za-z0-9_.~:/!$()+-]|%[0-9A-Fa-f]{2})+\.jar)")
    # Java throwable headers may contain RuntimeException/AssertionError, whose
    # suffix has no leading word boundary. Match the structured header, not an
    # arbitrary occurrence of Exception in informational prose or a class name.
    java_exception = re.compile(
        r'[ \t]*(?:(?:Caused by|Suppressed):[ \t]+|Exception in thread "[^"\r\n]+"[ \t]+)?'
        r"(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*"
        r"(?:[A-Za-z_$][A-Za-z0-9_$]*)?(?:Exception|Error)(?::[^\r\n]*)?[ \t]*")
    for number, line in enumerate(text.splitlines(), 1):
        if class_load_info.fullmatch(line):
            continue
        if not zero_count.match(line) and (fatal.search(line) or java_exception.fullmatch(line)):
            hits.append({"file": Path(path).name, "line": number, "text": line.strip()[:600]})
            if len(hits) >= 20:
                break
    return hits


def scan_log_record(path, encoding):
    """Read one immutable byte snapshot and return diagnostics, never codec guesses.

    Decode failures retain byte hash and explicit offsets. Exact ASCII native
    error signatures are separately labelled raw-byte indicators, not a partial
    decoded document. Callers must reject read failures as well as error hits.
    """
    path = Path(path)
    record = {"path": str(path.resolve()), "encoding": encoding, "sha256": None,
              "size": None, "status": "read_failed", "findings": [],
              "read_error": None, "raw_ascii_indicators": []}
    try:
        data = path.read_bytes()
    except OSError as error:
        record["read_error"] = {"type": type(error).__name__, "message": str(error), "encoding": encoding}
        return record
    record.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    for match in re.finditer(rb"Cannot create native file", data, re.I):
        indicator = {"offset": match.start(), "text": match.group().decode("ascii"),
                     "method": "exact_ascii_bytes_not_full_decode"}
        record["raw_ascii_indicators"].append(indicator)
        # An explicit native failure signature remains fatal even if a reviewed
        # but wrong codec happens to decode its bytes into unrelated characters.
        record["findings"].append({"file": path.name, "line": None, **indicator})
    try:
        codec = codecs.lookup(encoding)
        need(isinstance(codec.decode(b"")[0], str), "Log codec must decode bytes to text")
        text = data.decode(encoding, errors="strict")
    except (UnicodeError, LookupError, TypeError, ValueError) as error:
        detail = {"type": type(error).__name__, "message": str(error), "encoding": encoding}
        if isinstance(error, UnicodeDecodeError):
            detail.update(start=error.start, end=error.end, reason=error.reason,
                          byte_excerpt_hex=data[max(0,error.start-12):error.end+12].hex())
        record.update(status="decode_failed", read_error=detail)
        return record
    record["status"] = "scanned"
    record["findings"].extend(_log_findings(text, path))
    return record


def scan_logs(root, cfg, relatives=None):
    policy = validate_log_policy(cfg)
    relatives = list(policy) if relatives is None else list(relatives)
    need(all(path in policy for path in relatives), "Log scan includes an undeclared source")
    need(len(relatives) == len(set(relatives)), "Duplicate log scan sources")
    return [dict(scan_log_record(inside(Path(root), path), policy[path]), relative_path=path)
            for path in relatives]


def scan_log(path, encoding):
    """Compatibility API; new production callers aggregate scan_log_record(s)."""
    record = scan_log_record(path, encoding)
    need(record["status"] == "scanned", "Log read failed for " + str(path) + ": " + str(record["read_error"]))
    return record["findings"]


def validate_solver_observation(root, cfg, meta, started_ns, output_hashes):
    """Validate an adapter's observed solution map, not just its completion marker.

    This verifies record consistency and file provenance; the reviewed adapter
    remains responsible for obtaining the observation from COMSOL. Simulations
    are explicitly labelled and cannot be used as COMSOL execution evidence.
    """
    items = [o for o in cfg["outputs"] if o["role"] == "solver_observation"]
    need(len(items) == 1, "Exactly one independent solver_observation is required")
    path = inside(root, items[0]["path"])
    observed = read_json(path)
    need(isinstance(observed, dict) and observed.get("schema_version") == VERSION,
         "Unsupported solver observation schema")
    for key in ("run_id", "fingerprint"):
        need(observed.get(key) == meta[key], "Solver observation " + key + " mismatch")
    need(observed.get("operation") == cfg["operation"], "Solver observation operation mismatch")
    need(observed.get("input_model_sha256") == meta["pins"][cfg["model"]],
         "Solver observation input model mismatch")
    expected_status = "existing_solution_available" if cfg["operation"] == "export" else "completed"
    need(observed.get("solver_status") == expected_status,
         "Solver observation reports missing, partial or unsuccessful solution state")
    need(same_json(observed.get("completed_positions"), cfg["expected_positions"]),
         "Solver observation positions do not match plan/completion evidence")
    method = observed.get("observation", {})
    need(isinstance(method, dict) and isinstance(method.get("detail"), str) and method["detail"].strip(),
         "Observation must describe how actual solution state was read")
    allowed = {"synthetic_mock"} if cfg["execution_kind"] == "simulation" else {
        "solver_api", "saved_solution_readback", "gui_inspection"}
    need(method.get("method") in allowed, "Observation method does not match execution_kind")
    support = method.get("evidence")
    need(isinstance(support, list) and support, "Observation requires independent state-readback evidence")
    def check_readback(ref):
        need(isinstance(ref, dict) and isinstance(ref.get("path"), str), "Invalid observation evidence reference")
        support_path = inside(root, ref["path"])
        need(support_path != path and support_path != inside(root, cfg["evidence"]),
             "Completion/observation file cannot be its own state-readback evidence")
        need(ref["path"] in output_hashes and any(o["path"] == ref["path"]
             and o["role"] == "solution_readback" for o in cfg["outputs"]),
             "Readback evidence must be a declared fresh solution_readback output")
        need(support_path.is_file() and support_path.stat().st_size > 0,
             "Missing/empty solution state-readback evidence")
        need(support_path.stat().st_mtime_ns >= started_ns, "Stale solution state-readback evidence")
        need(digest(support_path) == ref.get("sha256"), "State-readback evidence hash mismatch")
    for ref in support:
        check_readback(ref)
    solutions = observed.get("solutions")
    need(isinstance(solutions, list) and solutions, "No observed solution/tag mapping")
    planned = {name: {canonical(p) for p in positions}
               for name, positions in target_position_map(cfg["expected_positions"], cfg["target_names"]).items()}
    mappings, covered = set(), {name: set() for name in planned}
    solved_outputs = {str(inside(root, o["path"])): output_hashes[o["path"]]
                      for o in cfg["outputs"] if o["role"] == "solved_model"}
    for solution in solutions:
        need(isinstance(solution, dict), "Invalid observed solution mapping")
        key = (solution.get("solution_tag"), solution.get("dataset_tag"))
        need(isinstance(key[0], str) and key[0].strip(), "Missing observed solution tag")
        if key[1] is None and cfg["operation"] != "export":
            need(isinstance(solution.get("dataset_unavailable_reason"), str)
                 and solution["dataset_unavailable_reason"].strip(),
                 "A solve without a result dataset must explicitly explain its absence")
        else:
            need(isinstance(key[1], str) and key[1].strip(), "Missing observed dataset tag")
        targets = solution.get("target_names")
        need(isinstance(targets, list) and targets and all(isinstance(n, str) for n in targets)
             and len(targets) == len(set(targets)) and set(targets) <= set(planned),
             "Solution lacks a target-to-dataset/position mapping")
        positions = solution.get("positions")
        need(isinstance(positions, list) and positions, "Solution mapping has no positions")
        mapped = {canonical(p) for p in positions}
        need(len(mapped) == len(positions), "Solution mapping has duplicate positions")
        mapping_key = (*key, canonical(sorted(targets)), canonical(sorted(mapped)))
        need(mapping_key not in mappings, "Duplicate observed target/position mapping")
        mappings.add(mapping_key)
        for target_name in targets:
            need(mapped <= planned[target_name],
                 "Solution mapping has unplanned positions for target: " + target_name)
        need(type(solution.get("solution_count")) is int and solution["solution_count"] == len(positions),
             "Observed selected solution count disagrees with position mapping")
        available = solution.get("available_solution_count")
        need(type(available) is int and available >= solution["solution_count"],
             "Available solution count is missing or smaller than the selected mapping")
        source = solution.get("source", {})
        need(isinstance(source, dict) and isinstance(source.get("path"), str), "Missing solution source")
        source_path = Path(source["path"])
        source_path = source_path.resolve() if source_path.is_absolute() else inside(root, source["path"])
        if cfg["operation"] == "export":
            existing_models = {cfg["model"], *meta.get("source_solution_paths", [])}
            need(str(source_path) in meta["pins"] and str(source_path) in existing_models
                 and source_path.suffix.lower() == ".mph",
                 "Export source solution is not a pinned existing model/runtime source MPH")
            expected_hash = meta["pins"][str(source_path)]
            allowed_sources = meta.get("allowed_solution_sources")
            need(isinstance(allowed_sources, list), "No reviewed target-to-source solution map")
            for target_name in targets:
                matches = [item for item in allowed_sources if item.get("target_name") == target_name
                           and item.get("solution_id") == solution.get("solution_id")
                           and item.get("solution_tag") == solution["solution_tag"]
                           and item.get("source_model_sha256") == expected_hash
                           and any(ref.get("path") == str(source_path) and ref.get("sha256") == expected_hash
                                   for ref in item.get("files", []))]
                need(matches, "Export observed source/solution does not match the reviewed target: " + target_name)
            selections = solution.get("selection_evidence")
            need(isinstance(selections, list) and selections,
                 "Export requires readback evidence of the actual target selections")
            for ref in selections:
                check_readback(ref)
        else:
            need(str(source_path) in solved_outputs, "Solved solution source is not a new solved_model output")
            expected_hash = solved_outputs[str(source_path)]
        need(source.get("sha256") == expected_hash and digest(source_path) == expected_hash,
             "Observed solution source hash mismatch")
        # Accumulate only from this same source/target/position mapping after its
        # source was verified. Separate unions cannot establish target coverage.
        for target_name in targets:
            covered[target_name].update(mapped)
    for target_name in planned:
        need(covered[target_name] == planned[target_name],
             "Observed solution mapping does not cover all requested positions for target: " + target_name)
    return {"path": str(path), "sha256": digest(path), "solver_status": observed["solver_status"],
            "solution_mappings": len(solutions), "evidence_level":
            "simulated_execution" if cfg["execution_kind"] == "simulation" else "runtime_observation"}


def validate_runtime_artifact(path, declared_log, started_ns):
    """Empty logs are valid; required scientific/completion artifacts are not.

    The caller derives declared_log from the distinct config.logs paths, never
    an output role or filename. This does not exempt logs from freshness checks.
    """
    need(path.is_file(), "Missing artifact: " + str(path))
    stat = path.stat()
    need(declared_log or stat.st_size > 0, "Empty non-log artifact: " + str(path))
    need(stat.st_mtime_ns >= started_ns, "Stale artifact: " + str(path))


def raw_log_creation(stream, meta):
    """Receipt for a handle just opened by this wrapper with exclusive 'xb'.

    Windows may give a newly created empty file an mtime earlier than the
    preceding high resolution wall clock sample. Bind its actual identity
    instead of changing timestamps or allowing a generic stale-time window.
    """
    stat = os.fstat(stream.fileno())
    need(stat.st_size == 0 and stat.st_ino > 0, "New raw log identity unavailable")
    return {"method": "exclusive_wrapper_creation", "run_id": meta["run_id"],
            "fingerprint": meta["fingerprint"], "device": stat.st_dev,
            "inode": stat.st_ino, "creation_observed_ns": time.time_ns(),
            "initial_mtime_ns": stat.st_mtime_ns}


def seal_raw_log(path, receipt):
    stat = path.stat()
    need((stat.st_dev, stat.st_ino) == (receipt["device"], receipt["inode"]),
         "Raw log replaced since exclusive creation: " + str(path))
    receipt.update(final_mtime_ns=stat.st_mtime_ns, size=stat.st_size, sha256=digest(path))


def validate_owned_raw_log(path, receipt, start, process, meta):
    if receipt is None:
        # Historical records without exclusive-creation receipts do not acquire
        # a new exemption. They must satisfy the normal freshness condition.
        validate_runtime_artifact(path, True, start["started_ns"])
        return
    need(path.is_file() and isinstance(receipt, dict), "Missing raw log or creation receipt")
    need(receipt.get("method") == "exclusive_wrapper_creation"
         and all(receipt.get(key) == meta[key] for key in ("run_id", "fingerprint")),
         "Raw log creation receipt identity mismatch")
    for key in ("device", "inode", "creation_observed_ns", "initial_mtime_ns", "final_mtime_ns", "size"):
        need(type(receipt.get(key)) is int, "Invalid raw log receipt field: " + key)
    need(type(process.get("finished_ns")) is int
         and start["started_ns"] <= receipt["creation_observed_ns"] <= process["finished_ns"]
         and 0 < receipt["initial_mtime_ns"] <= receipt["creation_observed_ns"]
         and receipt["final_mtime_ns"] >= receipt["initial_mtime_ns"],
         "Raw log creation/finish time binding mismatch")
    stat = path.stat()
    need(receipt["inode"] > 0 and (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
         == (receipt["device"], receipt["inode"], receipt["size"], receipt["final_mtime_ns"])
         and digest(path) == receipt.get("sha256"), "Raw log identity/content changed")


def validate_process_success(process):
    """A zero child exit cannot override a recorded wrapper/cleanup failure.

    Older records used only error/termination_error and could still say exited.
    Check those fields independently; do not rewrite or reinterpret that history
    as a successful run. Presence also rejects exceptions with an empty message.
    """
    failure_fields = ("error", "termination_error", "cleanup_error", "raw_log_error", "timeout_error",
                      "supervision_error", "failure_details")
    need(not any(key in process for key in failure_fields),
         "Process record contains runtime, supervision or cleanup failure")
    need(process.get("status") == "exited" and type(process.get("exit_code")) is int
         and process["exit_code"] == 0,
         "Process failed, timed out, interrupted or could not start")


def record_process_failure(record, phase, error, status, field):
    """Keep the child's observed exit code and every exception independently."""
    record["status"] = status
    record.setdefault(field, str(error))
    record.setdefault("failure_details", []).append({
        "phase": phase, "exception_type": type(error).__name__, "message": str(error),
        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    })


def inspect(directory):
    report = {"completion_evidence_accepted": False, "basic_checks": "not_assessed",
              "numerical_convergence": "not_assessed", "experimental_validity": "not_assessed",
              "resume_reliability": "not_assessed", "errors": [], "log_findings": [], "log_scans": []}
    try:
        root, cfg, meta = load_bundle(directory)
        report.update(run_id=meta["run_id"], fingerprint=meta["fingerprint"], operation=cfg["operation"])
        if meta["kind"] == "plan":
            report.update(status="plan_prepared_not_executable", preparation_issues=meta["preparation_issues"])
            return report
        if not (root / "started.json").exists():
            report["status"] = "executable_bundle_prepared_not_executed"
            return report
        start = read_json(root / "started.json")
        need(start.get("run_id") == meta["run_id"] and start.get("fingerprint") == meta["fingerprint"],
             "Start record does not match bundle")
        need(type(start.get("started_ns")) is int and start["started_ns"] > 0,
             "Start timestamp must be an integer nanosecond value")
        # Preserve diagnostics even when process/output acceptance fails later.
        # Every source uses one reviewed strict codec; no first decode failure
        # prevents other native logs from being scanned.
        report["log_scans"] = scan_logs(root, cfg)
        for scanned in report["log_scans"]:
            report["log_findings"].extend(scanned["findings"])
            if scanned["status"] != "scanned":
                report["errors"].append("Log read failed for " + scanned["relative_path"] + ": " + str(scanned["read_error"]))
        need((root / "process.json").is_file(), "No process termination record; run incomplete")
        process = read_json(root / "process.json")
        need(process.get("run_id") == meta["run_id"] and process.get("fingerprint") == meta["fingerprint"],
             "Process record does not match bundle")
        validate_process_success(process)
        declared_logs = {inside(root, relative) for relative in cfg["logs"]}
        for path in validate_artifact_paths(root, cfg):
            validate_runtime_artifact(path, path in declared_logs, start["started_ns"])
        raw_receipts = process.get("raw_log_receipts")
        if raw_receipts is not None:
            need(isinstance(raw_receipts, dict) and set(raw_receipts) == {"stdout.log", "stderr.log"},
                 "Raw log creation receipt set mismatch")
        for relative in ["stdout.log", "stderr.log", *cfg["logs"]]:
            path = inside(root, relative)
            if relative in ("stdout.log", "stderr.log"):
                validate_owned_raw_log(path, raw_receipts[relative] if raw_receipts else None,
                                       start, process, meta)
            else:
                validate_runtime_artifact(path, True, start["started_ns"])
        # Bind the bytes just inspected to the files whose freshness/ownership
        # was checked above. A changing log cannot inherit an earlier scan.
        for scanned in report["log_scans"]:
            if scanned["sha256"] is not None:
                need(digest(Path(scanned["path"])) == scanned["sha256"], "Log bytes changed during inspection: " + scanned["relative_path"])
        need(all(row["status"] == "scanned" for row in report["log_scans"]), "One or more log sources could not be read with the reviewed encoding")
        need(not report["log_findings"], "Potential error in logs; manual diagnosis required, not accepted")
        evidence = read_json(inside(root, cfg["evidence"]))
        for key in ("run_id", "fingerprint"):
            need(evidence.get(key) == meta[key], "Evidence " + key + " mismatch")
        need(evidence.get("operation") == cfg["operation"] and evidence.get("status") == "completed",
             "Evidence operation/status mismatch")
        need(same_json(evidence.get("completed_positions"), cfg["expected_positions"]),
             "Completed time/parameter positions differ from plan (including order)")
        expected_hashes = {o["path"]: digest(inside(root, o["path"])) for o in cfg["outputs"]}
        need(same_json(evidence.get("output_hashes"), expected_hashes), "Output hash set/content mismatch")
        observed = validate_solver_observation(root, cfg, meta, start["started_ns"], expected_hashes)
        report.update(status="completion_evidence_accepted", completion_evidence_accepted=True,
                      output_hashes=expected_hashes, completed_positions=evidence["completed_positions"],
                      solver_observation=observed, evidence_level=observed["evidence_level"])
    except (OSError, ValueError, TypeError, KeyError, LookupError) as error:
        report["status"] = "evidence_rejected"
        report["errors"].append(str(error))
    return report


class WindowsJob:
    """Own one suspended process and its descendants; never targets by process name."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.api = c.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, c.c_void_p], w.BOOL),
            "Thread32Next": ([w.HANDLE, c.c_void_p], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            func = getattr(self.api, name)
            func.argtypes, func.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        need(bool(self.handle), "Cannot create an owned Windows Job")
        self.attached = False

    def attach_and_resume(self, process):
        c, w = self.c, self.w
        need(self.api.AssignProcessToJobObject(self.handle, int(process._handle)),
             "Cannot assign suspended process to owned Job; no script executed")
        self.attached = True
        class ThreadEntry(c.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("id", w.DWORD),
                        ("owner", w.DWORD), ("base", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]
        snapshot = self.api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        need(snapshot and snapshot != c.c_void_p(-1).value, "Cannot enumerate suspended primary thread")
        try:
            entry = ThreadEntry()
            entry.size = c.sizeof(entry)
            found = []
            more = self.api.Thread32First(snapshot, c.byref(entry))
            while more:
                if entry.owner == process.pid:
                    found.append(entry.id)
                more = self.api.Thread32Next(snapshot, c.byref(entry))
            need(len(found) == 1, "Expected one suspended primary thread; refusing to run")
            thread = self.api.OpenThread(2, False, found[0])  # THREAD_SUSPEND_RESUME
            need(bool(thread), "Cannot open suspended primary thread")
            try:
                need(self.api.ResumeThread(thread) == 1, "Unexpected primary thread suspension state")
            finally:
                self.api.CloseHandle(thread)
        finally:
            self.api.CloseHandle(snapshot)

    def active(self):
        c, w = self.c, self.w
        class Accounting(c.Structure):
            _fields_ = [("times", c.c_longlong * 4), ("faults", w.DWORD), ("total", w.DWORD),
                        ("active", w.DWORD), ("terminated", w.DWORD)]
        data = Accounting()
        need(self.api.QueryInformationJobObject(self.handle, 1, c.byref(data), c.sizeof(data), None),
             "Cannot query owned Job process state")
        return data.active

    def stop(self):
        need(self.api.TerminateJobObject(self.handle, 124), "Cannot terminate owned Job")
        need(self.wait_empty(5), "Owned Job termination did not finish; manual attention required")

    def wait_empty(self, seconds):
        # Job accounting can lag behind a signaled process handle on Windows.
        deadline = time.monotonic() + seconds
        while self.active():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self):
        need(self.api.CloseHandle(self.handle), "Cannot close owned Job handle")


def stop_owned_tree(process, job):
    if job is not None and job.attached:
        job.stop()
    elif process.poll() is None:
        if os.name == "nt":
            process.kill()  # Unassigned process is still suspended and has no descendants.
        else:
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def execute(directory, authorization, export_only=False):
    need(isinstance(authorization, str) and authorization.strip(), "Current authorization text is required")
    root, cfg, meta = load_bundle(directory)
    need(meta["kind"] == "executable", "Only a reviewed executable bundle can run; prepare a new bundle after resolving the plan")
    need((cfg["operation"] == "export") == export_only,
         "Use export for operation export; use run for solve/resume")
    for path in validate_artifact_paths(root, cfg) + [root / "stdout.log", root / "stderr.log",
                                                   root / "process.json", root / "summary.json", root / "output-record.json"]:
        need(not path.exists(), "Pre-existing artifact; prepare a new run: " + str(path))
    need(not (root / "started.json").exists(), "Bundle is single-use; prepare a new run")
    # Create the start record exclusively to prevent duplicate execution.
    started = {"run_id": meta["run_id"], "fingerprint": meta["fingerprint"],
               "authorization": authorization, "started_ns": time.time_ns()}
    write_json(root / "started.json", started, exclusive=True)
    substitutions = {"{run_dir}": str(root), "{run_id}": meta["run_id"],
                     "{fingerprint}": meta["fingerprint"], "{model}": cfg["model"]}
    argv = []
    for raw in cfg["argv"]:
        for token, value in substitutions.items():
            raw = raw.replace(token, value)
        argv.append(raw)
    record = {"run_id": meta["run_id"], "fingerprint": meta["fingerprint"],
              "argv": argv, "status": "launch_failed", "exit_code": None}
    child = None
    job = None
    phase = "raw_log_creation"
    try:
        with (root / "stdout.log").open("xb") as stdout, (root / "stderr.log").open("xb") as stderr:
            record["raw_log_receipts"] = {"stdout.log": raw_log_creation(stdout, meta),
                                          "stderr.log": raw_log_creation(stderr, meta)}
            if os.name == "nt":
                phase = "job_creation"
                job = WindowsJob()
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 4} if os.name == "nt" else {"start_new_session": True}  # CREATE_SUSPENDED
            phase = "child_launch"
            child = subprocess.Popen(argv, shell=False, cwd=root, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, **options)
            record["pid"] = child.pid
            if job is not None:
                phase = "job_assignment"
                job.attach_and_resume(child)
            try:
                phase = "child_wait"
                record["exit_code"] = child.wait(timeout=cfg["resources"]["timeout_seconds"])
            except subprocess.TimeoutExpired as error:
                record_process_failure(record, phase, error, "timed_out", "timeout_error")
                phase = "timeout_cleanup"
                stop_owned_tree(child, job)
                record["exit_code"] = child.returncode
            else:
                record["status"] = "exited"
                phase = "post_exit_supervision"
                if job is not None and not job.wait_empty(1):
                    record["status"] = "descendants_remaining"
                    phase = "descendant_cleanup"
                    job.stop()
    except BaseException as error:
        record_process_failure(record, phase, error,
                               "interrupted" if isinstance(error, KeyboardInterrupt) else "execution_failed", "error")
        if child is not None:
            # A wait/query failure must not discard an already observed child
            # result, or replace a genuine zero with an invented wrapper code.
            if record["exit_code"] is None:
                record["exit_code"] = child.returncode
            try:
                stop_owned_tree(child, job)
                if record["exit_code"] is None:
                    record["exit_code"] = child.returncode
            except BaseException as stop_error:
                record_process_failure(record, "exception_cleanup", stop_error,
                                       "termination_failed", "termination_error")
    finally:
        if job is not None:
            try:
                job.close()
            except BaseException as close_error:
                record_process_failure(record, "job_close", close_error,
                                       "cleanup_failed", "cleanup_error")
        try:
            for name, receipt in record.get("raw_log_receipts", {}).items():
                seal_raw_log(root / name, receipt)
        except BaseException as error:
            record_process_failure(record, "raw_log_seal", error,
                                   "raw_log_binding_failed", "raw_log_error")
        record["finished_ns"] = time.time_ns()
        write_json(root / "process.json", record, exclusive=True)
    report = inspect(root)
    output_record = {
        "schema_version": VERSION, "record_type": "compute_output_provenance",
        "run_id": meta["run_id"], "fingerprint": meta["fingerprint"],
        "operation": cfg["operation"], "scope": cfg["scope"], "execution_kind": cfg["execution_kind"],
        "target_names": cfg["target_names"], "expected_positions": cfg["expected_positions"],
        "input_model": {"path": cfg["model"], "sha256": meta["pins"][cfg["model"]]},
        "input_manifest": {"path": cfg["manifest"], "sha256": meta["pins"][cfg["manifest"]]},
        "input_record": {"path": cfg["input_record"], "sha256": meta["pins"][cfg["input_record"]]},
        "operation_review": {"path": cfg["operation_review"], "sha256": meta["pins"][cfg["operation_review"]]},
        "outputs": [{"path": str(inside(root, o["path"])), "role": o["role"],
                     "sha256": report["output_hashes"][o["path"]]} for o in cfg["outputs"]]
                   if report["completion_evidence_accepted"] else [],
        "current_checks": {"completion_evidence_accepted": report["completion_evidence_accepted"],
                           "basic_checks": "not_assessed", "numerical_convergence": "not_assessed",
                           "experimental_validity": "not_assessed", "resume_reliability": "not_assessed"},
        "inherited_checks": [],
        "inheritance_policy": "No automatic inheritance; old checks retain their original model binding in the input manifest",
    }
    write_json(root / "output-record.json", output_record, exclusive=True)
    report["output_record"] = {"path": str(root / "output-record.json"), "sha256": digest(root / "output-record.json")}
    write_json(root / "summary.json", report, exclusive=True)
    return report


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="Create a unique bundle; never starts a process")
    p.add_argument("--config", required=True)
    p.add_argument("--root", required=True)
    for command in ("run", "export", "inspect"):
        p = sub.add_parser(command)
        p.add_argument("--bundle", required=True)
        if command != "inspect":
            p.add_argument("--authorization", required=True, help="Verbatim current authorization; not inherited from history")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.config, args.root)
        elif args.command == "inspect":
            result = inspect(args.bundle)
        else:
            result = execute(args.bundle, args.authorization, args.command == "export")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if result.get("status") == "evidence_rejected" else 0
    except (OSError, ValueError, TypeError, KeyError, LookupError) as error:
        print(json.dumps({"status": "rejected_before_execution", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
