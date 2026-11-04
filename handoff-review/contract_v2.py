#!/usr/bin/env python3
"""Public COMSOL contract 2.0.0 checker; standard library, read-only, no COMSOL.

Canonical maintenance source: handoff-review. Publish byte-identical copies
beside each skill's own wrapper; no cross-skill runtime import is required.
This verifies declarations and file provenance, never physical correctness,
spatial membership, execution readiness, authorization, or legacy validity.
"""
from pathlib import Path
import hashlib
import json
import re

VERSION = "2.0.0"
_HERE = Path(__file__).resolve().parent
SCHEMA = (_HERE / "model-manifest.schema.json" if (_HERE / "model-manifest.schema.json").is_file()
          else _HERE.parent / "references" / "model-manifest.schema.json")
INVENTORY_GROUPS = ("components", "selections", "pairs", "parameters", "materials",
                    "dependencies", "target_outputs", "assumptions", "coordinate_systems",
                    "physical_initial_conditions", "legacy_meshes", "legacy_studies", "legacy_solutions")
_SCHEMA_KEYS = {"$schema", "$id", "$defs", "$ref", "title", "description", "type", "properties",
                "required", "additionalProperties", "items", "anyOf", "oneOf", "const", "enum",
                "minLength", "pattern", "minimum", "maximum", "minItems", "maxItems"}


def read_json(path):
    """Strict UTF-8/BOM JSON; reject duplicates and nonfinite constants."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("Duplicate JSON key: " + key)
            out[key] = value
        return out
    def nonfinite(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=nonfinite)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def known_scope_ids(data):
    """Canonical IDs for operation scopes and unresolved affected_scope."""
    scopes = {"all", "model"} | {"inventory:" + name for name in INVENTORY_GROUPS}
    for component in data.get("components") or []:
        tag = component["tag"]
        scopes.add("component:" + tag)
        scopes.update("geometry:" + tag + "/" + name for name in component["geometries"])
        scopes.update("physics:" + tag + "/" + item["tag"] for item in component["physics"] or [])
    for group, prefix in (("selections", "selection"), ("pairs", "pair"),
                          ("materials", "material"), ("coordinate_systems", "coordinate_system")):
        scopes.update(prefix + ":" + item["component"] + "/" + item["tag"] for item in data.get(group) or [])
    for group, prefix, field in (("physical_initial_conditions", "initial_condition", "id"),
                                  ("target_outputs", "target", "name"), ("dependencies", "dependency", "id")):
        scopes.update(prefix + ":" + item[field] for item in data.get(group) or [])
    scopes.update("parameter:" + item["scope"] + "/" + item["name"] for item in data.get("parameters") or [])
    for group, prefix in (("meshes", "legacy_mesh"), ("studies", "legacy_study"), ("solutions", "legacy_solution")):
        scopes.update(prefix + ":" + item["id"] for item in data.get("legacy", {}).get(group) or [])
    return scopes


def expand_scope(data, scope):
    """Conservative declared dependency closure, not a physical dependency proof.

    Global parameters have no per-consumer dependency declaration in v2 and
    therefore cannot be assumed irrelevant to a component/target operation.
    Existing solutions are followed by explicit ID even without a component.
    """
    expanded = set(scope)
    if expanded & {"all", "model"}:
        return known_scope_ids(data) | {"all", "model"}
    members = {c["tag"]: {"component:" + c["tag"]} for c in data.get("components") or []}
    for value in known_scope_ids(data):
        suffix = value.split(":", 1)[-1]
        if "/" in suffix and suffix.split("/", 1)[0] in members:
            members[suffix.split("/", 1)[0]].add(value)
    for target in data.get("target_outputs") or []:
        node = "target:" + target["name"]
        selection = target["selection_ref"]
        if node in expanded and selection["kind"] in ("global", "pending"):
            return known_scope_ids(data) | {"all", "model"}
        if selection.get("component") in members:
            members[selection["component"]].add(node)
    for item in data.get("physical_initial_conditions") or []:
        if item["component"] in members:
            members[item["component"]].add("initial_condition:" + item["id"])
    for group, prefix in (("meshes", "legacy_mesh"), ("studies", "legacy_study"), ("solutions", "legacy_solution")):
        for item in data.get("legacy", {}).get(group) or []:
            if item["component"] in members:
                members[item["component"]].add(prefix + ":" + item["id"])
    previous = None
    while expanded != previous:
        previous = set(expanded)
        for values in members.values():
            if expanded & values:
                expanded.update(values)
        for target in data.get("target_outputs") or []:
            if "target:" + target["name"] not in expanded:
                continue
            solution = target["required_solution"]
            if solution["kind"] == "existing":
                expanded.add("legacy_solution:" + solution["id"])
            coordinate = target["coordinate_system"]
            if coordinate["status"] == "complete" and coordinate["value"] != "global":
                expanded.add("coordinate_system:" + coordinate["value"])
    if any(expanded & values for values in members.values()):
        expanded.update("parameter:global/" + item["name"] for item in data.get("parameters") or []
                        if item["scope"] == "global")
    return expanded


def scope_overlap(data, left, right):
    """Model/all and registered parent/child scopes cannot be silently ignored."""
    # A shared dependency is not itself proof that two consumers affect each
    # other. Follow each declared edge toward the other actual scope instead.
    return bool(expand_scope(data, left) & set(right) or expand_scope(data, right) & set(left))


def public_report(result):
    """Expose the normative error interface; retain candidate02 aliases.

    instance_path uses the same stable $.field[index] locations as legacy
    path. Side errors and todos remain separate and never enter errors.
    """
    result["errors"] = [{"code": item["code"], "instance_path": item.get("instance_path", item.get("path", "$")),
                         "message": item["message"]} for item in result.get("public_errors", [])]
    return result


def audit_schema(schema):
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        raise ValueError("Unsupported schema keywords: " + ", ".join(sorted(unknown)))
    for key in ("properties", "$defs"):
        for child in schema.get(key, {}).values():
            audit_schema(child)
    for key in ("anyOf", "oneOf"):
        for child in schema.get(key, []):
            audit_schema(child)
    if "items" in schema:
        audit_schema(schema["items"])


def schema_errors(value, schema, root, path="$"):
    """The deliberately limited, fail-closed evaluator for this public schema."""
    if "$ref" in schema:
        target = schema["$ref"]
        if not target.startswith("#/$defs/"):
            raise ValueError("Unsupported schema reference: " + target)
        return schema_errors(value, root["$defs"][target[len("#/$defs/"):]], root, path)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            count = sum(not schema_errors(value, child, root, path) for child in schema[keyword])
            valid = count > 0 if keyword == "anyOf" else count == 1
            return [] if valid else [(path, keyword + " alternatives did not match uniquely")]
    predicates = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
                  "string": lambda v: isinstance(v, str), "integer": lambda v: type(v) is int,
                  "boolean": lambda v: type(v) is bool, "null": lambda v: v is None}
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    if types and not any(predicates[t](value) for t in types):
        return [(path, "Wrong type; expected " + "/".join(types))]
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append((path, "Invalid constant"))
    if "enum" in schema and value not in schema["enum"]:
        errors.append((path, "Invalid enum"))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append((path, "Missing " + key))
        for key, item in value.items():
            if key in schema.get("properties", {}):
                errors.extend(schema_errors(item, schema["properties"][key], root, path + "." + key))
            elif schema.get("additionalProperties") is False:
                errors.append((path + "." + key, "Unexpected field"))
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append((path, "Too few items"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append((path, "Too many items"))
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, schema["items"], root, f"{path}[{index}]"))
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append((path, "String too short"))
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append((path, "String pattern mismatch"))
    elif type(value) is int:
        if "minimum" in schema and value < schema["minimum"]:
            errors.append((path, "Below minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append((path, "Above maximum"))
    return errors


def validate_manifest(path, side=None):
    """Return errors/side_errors/todos; public_errors is a compatibility alias."""
    path = Path(path).resolve()
    result = {"schema_version": VERSION, "manifest_file_check": "failed",
              "comsol_model_check_performed": False, "execution_readiness": "not_assessed",
              "public_errors": [], "side_errors": [], "todos": []}

    def issue(code, where, message, group="public_errors"):
        entry = {"code": code, "path": where, "message": message}
        if entry not in result[group]:
            result[group].append(entry)

    def done():
        result["manifest_file_check"] = "failed" if result["public_errors"] or result["side_errors"] else "passed"
        return public_report(result)

    try:
        data = read_json(path)
        result["manifest"] = {"path": str(path), "sha256": digest(path)}
    except (OSError, ValueError, TypeError) as exc:
        issue("JSON_INVALID", "$", str(exc))
        return done()
    if not isinstance(data, dict):
        issue("SCHEMA_STRUCTURE", "$", "Manifest must be an object")
        return done()
    if data.get("schema_version") != VERSION:
        issue("SCHEMA_VERSION", "$.schema_version", "Explicit separate migration to 2.0.0 is required")
        return done()

    # Preserve useful public classifications even when schema rejects the value.
    def preflight(value, where):
        if isinstance(value, dict):
            for key, child in value.items():
                if where == "$" and key == "extensions":
                    # Extension metadata has no implicit physical/selection semantics.
                    # A retired private output extension is rejected explicitly below.
                    continue
                at = where + "." + key
                if key == "expression" and isinstance(child, str) and not child.strip():
                    issue("EXPRESSION_BLANK", at, "Defined expression cannot be blank")
                if key == "expression" and isinstance(child, dict) and isinstance(child.get("value"), str) and not child["value"].strip():
                    issue("EXPRESSION_BLANK", at, "Defined expression cannot be blank")
                if key in ("entity_dimension", "dimension") and type(child) is int and not 0 <= child <= 3:
                    issue("SELECTION_DIMENSION", at, "Entity/component dimension outside 0..3")
                preflight(child, at)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                preflight(child, f"{where}[{i}]")
    preflight(data, "$")
    try:
        schema = read_json(SCHEMA)
        audit_schema(schema)
        structural = schema_errors(data, schema, schema)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issue("SCHEMA_STRUCTURE", "$", "Schema unavailable or unsupported: " + str(exc))
        return done()
    for where, message in structural:
        issue("SCHEMA_STRUCTURE", where, message)
    if structural:
        return done()

    hashes = {}
    def resolve(raw):
        p = Path(raw)
        return p.resolve() if p.is_absolute() else (path.parent / p).resolve()

    def file_record(item, where):
        candidate = resolve(item["path"])
        if not candidate.is_file():
            issue("FILE_MISSING", where, "File missing: " + str(candidate))
            return
        try:
            if candidate not in hashes:
                hashes[candidate] = digest(candidate)
            if hashes[candidate] != item["sha256"]:
                issue("FILE_HASH", where, "SHA256 mismatch: " + str(candidate))
        except OSError as exc:
            issue("FILE_MISSING", where, str(exc))

    def evidence(items, where):
        for i, item in enumerate(items):
            file_record(item, f"{where}[{i}]")

    file_record(data["model"], "$.model")
    current_hash = data["model"]["sha256"]
    result["model"] = {"path": str(resolve(data["model"]["path"])), "sha256": current_hash}
    source = data["source_model"]
    if source is not None:
        file_record(source, "$.source_model")
    if data["producer"]["operation"] == "modify":
        if source is None:
            issue("SOURCE_OVERWRITE", "$.source_model", "Modification requires the original source record")
        else:
            same = resolve(source["path"]) == resolve(data["model"]["path"])
            try:
                same = same or resolve(source["path"]).samefile(resolve(data["model"]["path"]))
            except OSError:
                pass
            if same:
                issue("SOURCE_OVERWRITE", "$.model", "Modification must save separately from the source")

    def unique(items, key, where):
        seen = set()
        for i, item in enumerate(items or []):
            ident = key(item)
            if ident in seen:
                issue("DUPLICATE_ID", f"{where}[{i}]", "Repeated identifier: " + str(ident))
            seen.add(ident)

    unique(data["unresolved"], lambda x: x["id"], "$.unresolved")
    unresolved = {item["id"]: item for item in data["unresolved"]}
    known_scopes = known_scope_ids(data)
    for i, item in enumerate(data["unresolved"]):
        evidence(item["evidence"], f"$.unresolved[{i}].evidence")
        for scope in item["affected_scope"]:
            if scope not in known_scopes:
                issue("SCOPE_REFERENCE", f"$.unresolved[{i}].affected_scope", "Unknown affected scope: " + scope)
        issue("UNRESOLVED", f"$.unresolved[{i}]", item["id"] + ": " + item["question"], "todos")

    def issue_refs(ids, where, required=False, context=None):
        if required and not ids:
            issue("UNRESOLVED_REFERENCE", where, "Pending state requires a corresponding unresolved issue")
        for ref_id in ids:
            if ref_id not in unresolved:
                issue("UNRESOLVED_REFERENCE", where, "Unknown unresolved id: " + ref_id)
            elif required and context is not None and not (set(unresolved[ref_id]["affected_scope"]) & (set(context) | {"all", "model"})):
                issue("UNRESOLVED_SCOPE", where, "Referenced issue does not cover this pending field: " + ref_id)

    def inventory(items, inv, where, context):
        evidence(inv["evidence"], where + ".evidence")
        status = inv["status"]
        issue_refs(inv["unresolved_ids"], where + ".unresolved_ids", status != "complete", context)
        if status == "not_inspected" and items is not None:
            issue("INVENTORY_STATE", where, "not_inspected requires null, not a list claiming known contents")
        if status == "complete" and items is None:
            issue("INVENTORY_STATE", where, "complete requires a known array; [] means confirmed absent")
        if status == "partial" and not items:
            issue("INVENTORY_STATE", where, "partial requires at least one known item; use not_inspected/null otherwise")
        if status != "complete":
            issue("INVENTORY_PENDING", where, status + ": " + inv["reason"], "todos")

    for group in INVENTORY_GROUPS:
        items = data["legacy"][group[7:]] if group.startswith("legacy_") else data[group]
        inventory(items, data["inventory"][group], "$.inventory." + group, {"inventory:" + group})

    def definition(item, where, context=None):
        status = item["status"]
        issue_refs(item["unresolved_ids"], where + ".unresolved_ids", status == "pending", context)
        if status == "complete":
            if item["value"] is None or not item["value"].strip():
                issue("TARGET_STATE", where, "complete requires a nonblank value")
            if item["unresolved_ids"]:
                issue("TARGET_STATE", where, "complete cannot retain unresolved value references")
        elif item["value"] is not None:
            issue("TARGET_STATE", where, "pending/not_applicable must have null value")
        if status == "not_applicable" and item["unresolved_ids"]:
            issue("TARGET_STATE", where, "not_applicable cannot conceal unresolved value references")

    def check(item, where, bound_hash=current_hash):
        if item["status"] == "passed":
            if not item["evidence"]:
                issue("CHECK_EVIDENCE", where, "passed requires evidence")
            if item["model_sha256"] != bound_hash:
                issue("CHECK_MODEL_BINDING", where, "passed check has the wrong model binding")
        elif item["status"] in ("not_run", "blocked"):
            issue("PENDING_CHECK", where, item["status"] + ": " + item["notes"], "todos")
        evidence(item["evidence"], where + ".evidence")

    for name, item in data["checks"].items():
        if name != "details":
            check(item, "$.checks." + name)
    unique(data["checks"]["details"], lambda x: x["name"], "$.checks.details")
    for i, item in enumerate(data["checks"]["details"]):
        check(item["result"], f"$.checks.details[{i}].result")
    structure_passed = data["checks"]["structure"]["status"] == "passed"
    if structure_passed and not data["checks"]["details"]:
        issue("STRUCTURE_DETAILS", "$.checks.details", "structure=passed requires named structural details")

    def contradict(status, where):
        if structure_passed and status not in ("passed", "not_applicable"):
            issue("STRUCTURE_CONTRADICTION", where, "structure=passed contradicts " + status)
    for i, item in enumerate(data["checks"]["details"]):
        contradict(item["result"]["status"], f"$.checks.details[{i}].result")
    for group in ("components", "selections", "pairs", "parameters", "materials", "dependencies",
                  "coordinate_systems", "physical_initial_conditions"):
        if structure_passed and data["inventory"][group]["status"] != "complete":
            issue("STRUCTURE_CONTRADICTION", "$.inventory." + group, "Structure cannot pass with incomplete structural inventory")
    if data["producer"]["skill"] == "comsol-modeling":
        if data["producer"]["operation"] == "compute":
            issue("MODELING_EXECUTION", "$.producer.operation", "Modeling producer cannot claim compute")
        for name in ("mesh_validation", "solve_validation"):
            if data["checks"][name]["status"] not in ("not_run", "not_applicable", "blocked"):
                issue("MODELING_EXECUTION", "$.checks." + name, "Modeling producer cannot claim this execution")

    components = {item["tag"]: item for item in data["components"] or []}
    unique(data["components"], lambda x: x["tag"], "$.components")
    physics = {}
    for i, item in enumerate(data["components"] or []):
        where = f"$.components[{i}]"
        unique(item["physics"], lambda x: x["tag"], where + ".physics")
        if len(item["geometries"]) != len(set(item["geometries"])):
            issue("DUPLICATE_ID", where + ".geometries", "Geometry tags must be unique within a component")
        inventory(item["physics"], item["physics_inventory"], where + ".physics_inventory", {"component:" + item["tag"]})
        if structure_passed and item["physics_inventory"]["status"] != "complete":
            issue("STRUCTURE_CONTRADICTION", where + ".physics_inventory", "Physics inventory is incomplete")
        for ph in item["physics"] or []:
            physics[item["tag"] + "/" + ph["tag"]] = ph
    selections = {(item["component"], item["tag"]): item for item in data["selections"] or []}
    for group in ("selections", "pairs", "materials", "coordinate_systems"):
        unique(data[group], lambda x: (x["component"], x["tag"]), "$." + group)
    unique(data["parameters"], lambda x: (x["scope"], x["name"]), "$.parameters")
    unique(data["physical_initial_conditions"], lambda x: x["id"], "$.physical_initial_conditions")

    def entity_scope(component, geometry, dim, where):
        owner = components.get(component)
        if owner is None:
            issue("SELECTION_REFERENCE", where, "Unknown component: " + component)
            return
        if geometry not in owner["geometries"]:
            issue("GEOMETRY_REFERENCE", where, "Geometry is not registered in this component: " + geometry)
        if dim > owner["dimension"]:
            issue("SELECTION_DIMENSION", where, "Entity dimension exceeds component dimension")

    def selection_ref(item, where, expected_component=None, structural=True, context=None):
        kind = item["kind"]
        if kind == "pending":
            issue_refs(item["unresolved_ids"], where + ".unresolved_ids", True, context)
            if structural:
                contradict("pending selection", where)
            return None
        if kind == "global":
            return None
        component = item["component"]
        if expected_component is not None and component != expected_component:
            issue("SELECTION_REFERENCE", where, "Selection belongs to another component")
        if kind == "named":
            node = selections.get((component, item["selection"]))
            if node is None:
                issue("SELECTION_REFERENCE", where, "Unregistered named selection")
                return None
            entity_scope(component, node["geometry"], node["entity_dimension"], where)
            return (component, node["geometry"], node["entity_dimension"])
        entity_scope(component, item["geometry"], item["entity_dimension"], where)
        if kind == "inline":
            check(item["verification"], where + ".verification")
            if structural:
                contradict(item["verification"]["status"], where + ".verification")
        return (component, item["geometry"], item["entity_dimension"])

    for i, item in enumerate(data["selections"] or []):
        where = f"$.selections[{i}]"
        entity_scope(item["component"], item["geometry"], item["entity_dimension"], where)
        check(item["spatial_verification"], where + ".spatial_verification")
        contradict(item["spatial_verification"]["status"], where + ".spatial_verification")
    for i, item in enumerate(data["components"] or []):
        for j, ph in enumerate(item["physics"] or []):
            where = f"$.components[{i}].physics[{j}]"
            selection_ref(ph["selection_ref"], where + ".selection_ref", item["tag"], context={"physics:" + item["tag"] + "/" + ph["tag"], "component:" + item["tag"]})
            evidence(ph["evidence"], where + ".evidence")
    for i, item in enumerate(data["pairs"] or []):
        where = f"$.pairs[{i}]"
        scopes = []
        for key in ("source_selection_ref", "destination_selection_ref"):
            scope = selection_ref(item[key], where + "." + key, item["component"])
            if item[key]["kind"] not in ("named", "all", "inline") or scope is None:
                issue("PAIR_REFERENCE", where + "." + key, "Pair sides require resolvable entity references")
            elif scope[2] != item["entity_dimension"]:
                issue("PAIR_REFERENCE", where + "." + key, "Pair side dimension differs from the pair declaration")
            scopes.append(scope)
        if all(scopes) and scopes[0][:2] != scopes[1][:2]:
            issue("PAIR_REFERENCE", where, "Pair sides must use the same declared component and geometry")
        check(item["verification"], where + ".verification")
        contradict(item["verification"]["status"], where + ".verification")
    for i, item in enumerate(data["materials"] or []):
        where = f"$.materials[{i}]"
        selection_ref(item["selection_ref"], where + ".selection_ref", item["component"], context={"material:" + item["component"] + "/" + item["tag"], "component:" + item["component"]})
        if item["component"] not in components:
            issue("SELECTION_REFERENCE", where, "Material component is not registered")
        for ph in item["required_by"]:
            if ph not in physics or not ph.startswith(item["component"] + "/"):
                issue("SELECTION_REFERENCE", where + ".required_by", "Unknown or foreign physics reference: " + ph)
        check(item["coverage"], where + ".coverage")
        contradict(item["coverage"]["status"], where + ".coverage")
    for i, item in enumerate(data["coordinate_systems"] or []):
        if item["component"] not in components:
            issue("COORDINATE_REFERENCE", f"$.coordinate_systems[{i}]", "Coordinate system component is unknown")
        evidence(item["evidence"], f"$.coordinate_systems[{i}].evidence")
    coordinates = {item["component"] + "/" + item["tag"] for item in data["coordinate_systems"] or []}
    for i, item in enumerate(data["physical_initial_conditions"] or []):
        where = f"$.physical_initial_conditions[{i}]"
        if item["component"] + "/" + item["physics"] not in physics:
            issue("SELECTION_REFERENCE", where + ".physics", "Physical initial condition references unknown physics")
        contexts = {"initial_condition:" + item["id"], "physics:" + item["component"] + "/" + item["physics"], "component:" + item["component"]}
        selection_ref(item["selection_ref"], where + ".selection_ref", item["component"], context=contexts)
        definition(item["definition"], where + ".definition", contexts)
        if item["definition"]["status"] == "pending":
            contradict("pending physical initial condition", where)
        evidence(item["evidence"], where + ".evidence")

    unique(data["dependencies"], lambda x: x["id"], "$.dependencies")
    known_model_hashes = {current_hash}
    if source:
        known_model_hashes.add(source["sha256"])
    for i, item in enumerate(data["dependencies"] or []):
        where = f"$.dependencies[{i}]"
        if item["category"] == "runtime" and not item["applies_to"]:
            issue("DEPENDENCY_REQUIRED", where + ".applies_to", "Runtime dependency must declare applicable operations")
        if item["status"] == "present":
            if item["sha256"] is None:
                issue("FILE_HASH", where, "Present dependency requires SHA256")
            else:
                file_record(item, where)
                if item["category"] in ("source", "runtime") and item["role"] in ("source_model", "source_solution"):
                    known_model_hashes.add(item["sha256"])
            if item["required"] and not resolve(item["path"]).is_file():
                issue("DEPENDENCY_REQUIRED", where, "Required dependency is missing")
        elif item["required"]:
            issue("DEPENDENCY_REQUIRED", where, "Required dependency is missing or unverified")
        else:
            issue("DEPENDENCY_PENDING", where, item["status"] + ": " + item["notes"], "todos")
    if data["comsol"]["license_status"] != "unknown" and not data["comsol"]["license_evidence"]:
        issue("CHECK_EVIDENCE", "$.comsol.license_evidence", "Checked license declaration requires evidence; no license probing is performed")
    evidence(data["comsol"]["license_evidence"], "$.comsol.license_evidence")
    lineage = data.get("lineage")
    if lineage:
        file_record(lineage["input_manifest"], "$.lineage.input_manifest")
        file_record(lineage["input_model"], "$.lineage.input_model")
        try:
            original = read_json(resolve(lineage["input_manifest"]["path"]))
            version = original.get("schema_version") if isinstance(original, dict) else None
            if version not in (VERSION, "1.0.0") or (version == "1.0.0" and lineage["relation"] != "migrated"):
                issue("LINEAGE_BINDING", "$.lineage.input_manifest", "Source must be v2, or an explicit relation=migrated v1 source")
            else:
                original_model = original.get("model")
                # Read only the explicit old file binding, never reinterpret v1
                # inventories/checks/physics as if they were v2 declarations.
                original_path = original_model.get("path", original_model.get("file") if version == "1.0.0" else None) if isinstance(original_model, dict) else None
                original_hash = original_model.get("sha256") if isinstance(original_model, dict) else None
                readable = isinstance(original_path, str) and original_path.strip() and isinstance(original_hash, str) and re.fullmatch(r"[a-f0-9]{64}", original_hash)
                if not readable:
                    issue("LINEAGE_PENDING" if version == "1.0.0" else "LINEAGE_BINDING", "$.lineage.input_manifest",
                          "Source model file binding cannot be established; preserve the source and complete explicit inspection/migration",
                          "todos" if version == "1.0.0" else "public_errors")
                elif original_hash != lineage["input_model"]["sha256"]:
                    issue("LINEAGE_BINDING", "$.lineage.input_model", "Input manifest model hash differs from the declared input model")
                else:
                    original_file = Path(original_path)
                    if not original_file.is_absolute():
                        original_file = resolve(lineage["input_manifest"]["path"]).parent / original_file
                    if not original_file.is_file() or digest(original_file) != original_hash:
                        issue("LINEAGE_BINDING", "$.lineage.input_manifest", "Source manifest model file is missing or its hash differs from its original binding")
                    else:
                        known_model_hashes.add(lineage["input_model"]["sha256"])
        except (OSError, ValueError, TypeError) as exc:
            issue("LINEAGE_BINDING", "$.lineage.input_manifest", "Cannot read source model binding: " + str(exc))
    for group, entries in data["legacy"].items():
        unique(entries, lambda x: x["id"], "$.legacy." + group)
        for i, item in enumerate(entries or []):
            where = f"$.legacy.{group}[{i}]"
            if item["component"] is not None and item["component"] not in components:
                issue("LEGACY_BINDING", where + ".component", "Legacy component is not registered")
            evidence(item["evidence"], where + ".evidence")
            legacy_prefix = {"meshes": "legacy_mesh", "studies": "legacy_study", "solutions": "legacy_solution"}[group]
            legacy_contexts = {legacy_prefix + ":" + item["id"], "inventory:legacy_" + group}
            if item["component"] is not None:
                legacy_contexts.add("component:" + item["component"])
            range_keys = [key for key in ("parameters", "time", "frequency", "mode") if key in item["applies_to"]]
            for key in range_keys:
                definition(item["applies_to"][key], where + ".applies_to." + key, legacy_contexts)
            if item["validity"] == "valid":
                if not item["evidence"]:
                    issue("LEGACY_BINDING", where, "Legacy validity declaration requires evidence")
                for key in ("model_sha256", "source_model_sha256"):
                    if item["applies_to"][key] not in known_model_hashes:
                        issue("LEGACY_BINDING", where + ".applies_to." + key, "Legacy applicability hash has no corresponding current/source file record")
                if any(item["applies_to"][key]["status"] == "pending" for key in range_keys):
                    issue("LEGACY_BINDING", where, "Legacy valid cannot have pending applicability range")
                if group == "solutions" and not item["solution_id"]:
                    issue("LEGACY_BINDING", where + ".solution_id", "Valid legacy solution requires an actual solution identifier")
    legacy_solutions = {item["id"]: item for item in data["legacy"]["solutions"] or []}
    unique(data["target_outputs"], lambda x: x["name"], "$.target_outputs")
    for i, item in enumerate(data["target_outputs"] or []):
        where = f"$.target_outputs[{i}]"
        contexts = {"target:" + item["name"]}
        if item["selection_ref"].get("component"):
            contexts.add("component:" + item["selection_ref"]["component"])
        fields = ("expression", "unit", "coordinate_system", "statistic", "time", "frequency", "parameters", "mode")
        for key in fields:
            definition(item[key], where + "." + key, contexts)
        selection_ref(item["selection_ref"], where + ".selection_ref", structural=False, context=contexts)
        sol = item["required_solution"]
        issue_refs(sol["unresolved_ids"], where + ".required_solution.unresolved_ids", sol["status"] == "pending", contexts)
        if sol["kind"] == "existing" and sol["id"] not in legacy_solutions:
            issue("SOLUTION_REFERENCE", where + ".required_solution", "Existing solution id is not registered in legacy.solutions")
        coord = item["coordinate_system"]
        if coord["status"] == "complete" and coord["value"] != "global" and coord["value"] not in coordinates:
            issue("COORDINATE_REFERENCE", where + ".coordinate_system", "Coordinate system must be global or a registered component/tag")
        pending = any(item[k]["status"] == "pending" for k in fields) or sol["status"] == "pending" or item["selection_ref"]["kind"] == "pending"
        if item["status"] == "complete" and (pending or item["expression"]["status"] != "complete"):
            issue("TARGET_STATE", where, "Complete output has pending/missing expression or field")
        if item["status"] == "pending":
            if not pending:
                issue("TARGET_STATE", where, "Pending output must identify its pending field and unresolved issue")
            issue("TARGET_PENDING", where, item["reason"], "todos")
        if item["status"] == "not_applicable" and (any(item[k]["status"] != "not_applicable" for k in fields) or sol["status"] != "not_applicable" or item["selection_ref"]["kind"] != "global"):
            issue("TARGET_STATE", where, "Not-applicable output must consistently declare inapplicable fields and nonentity scope")
    unique(data.get("inherited_checks", []), lambda x: x["name"], "$.inherited_checks")
    for i, item in enumerate(data.get("inherited_checks", [])):
        where = f"$.inherited_checks[{i}]"
        file_record(item["original_model"], where + ".original_model")
        check(item["original_check"], where + ".original_check", item["original_model"]["sha256"])
        if not item["evidence"]:
            issue("CHECK_EVIDENCE", where, "Inheritance requires its own basis evidence")
        evidence(item["evidence"], where + ".evidence")
        for scope in item["applicable_scope"]:
            if scope not in known_scopes:
                issue("SCOPE_REFERENCE", where + ".applicable_scope", "Unknown inherited applicability scope: " + scope)
    if "compute_output_definitions" in data.get("extensions", {}):
        issue("TARGET_STATE", "$.extensions.compute_output_definitions", "Private output semantics were replaced by v2 target_outputs")
    return done()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    report = validate_manifest(args.manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["manifest_file_check"] == "passed" else 1)
