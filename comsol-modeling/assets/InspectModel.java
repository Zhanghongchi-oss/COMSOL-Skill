import com.comsol.model.*;
import com.comsol.model.physics.Physics;
import com.comsol.model.physics.PhysicsFeature;
import com.comsol.model.util.ModelUtil;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Arrays;
import java.util.Properties;
import java.util.concurrent.Callable;

/**
 * COMSOL 6.3 inventory corrections ported from the historical inventory-03 copy.
 * The current implementation was exercised on the small conduction/Joule fixtures
 * in v3 (2026-11-02), with source hashes and actual read-error counts recorded there.
 * That scoped evidence does not validate every interface or unknown-dimension case.
 * Read-only inventory/reload entry point for comsolbatch class execution.
 * Reads UTF-8 job.properties (with or without BOM) in the working directory:
 *   input_model=<existing MPH path>
 *   audit_output=<new TSV path>
 * Use UTF-8 key=value lines and forward-slash paths. No escapes or continuation.
 * input_model must be absolute; audit_output must remain inside this run directory.
 * It never builds geometry, saves a model, creates a mesh or runs a study.
 * Project-specific semantic checks belong in a separate CheckModel.java.
 */
public final class InspectModel {
    private static BufferedWriter out;
    private static int readErrors;

    private static String clean(String value) {
        return value == null ? "<null>" : value.replace("\\", "\\\\")
            .replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n");
    }

    private static void row(String object, String field, String value) throws IOException {
        out.write(clean(object) + "\t" + clean(field) + "\t" + clean(value));
        out.newLine();
    }

    private static void read(String object, String field, Callable<String> getter) throws IOException {
        try {
            row(object, field, getter.call());
        } catch (Exception e) {
            readErrors++;
            row(object, field + ".read_error", e.getClass().getName() + ": " + e.getMessage());
        }
    }

    private static void selection(String path, Selection s) throws IOException {
        read(path, "dimension", () -> Integer.toString(s.dim()));
        read(path, "is_whole_geometry_selection", () -> Boolean.toString(s.isGeom()));
        read(path, "is_global_selection", () -> Boolean.toString(s.isGlobal()));
        if (s instanceof LocalSelection) {
            read(path, "named_reference", () -> ((LocalSelection) s).named());
        }
        read(path, "entity_ids_snapshot", () -> s.isGlobal()
            ? "not_applicable_to_global_selection" : s.dim() >= 0
            ? Arrays.toString(s.entities(s.dim())) : "not_read: unspecified_entity_dimension");
        read(path, "entity_count", () -> s.isGlobal()
            ? "not_applicable_to_global_selection" : s.dim() >= 0
            ? Integer.toString(s.entities(s.dim()).length) : "not_read: unspecified_entity_dimension");
        row(path, "spatial_and_expected_membership_check", "not_run");
    }

    private static String propertyValue(PropFeature node, String name, String type) {
        switch (type) {
            case "String": return node.getString(name);
            case "StringArray": return Arrays.toString(node.getStringArray(name));
            case "StringMatrix": return Arrays.deepToString(node.getStringMatrix(name));
            case "Boolean": return Boolean.toString(node.getBoolean(name));
            case "Int": return Integer.toString(node.getInt(name));
            case "IntArray": return Arrays.toString(node.getIntArray(name));
            case "Double": return Double.toString(node.getDouble(name));
            case "DoubleArray": return Arrays.toString(node.getDoubleArray(name));
            case "DoubleMatrix": return Arrays.deepToString(node.getDoubleMatrix(name));
            default: return "not_read: unsupported_value_type=" + type;
        }
    }

    private static void properties(String path, PropFeature node) throws IOException {
        for (String name : node.properties()) {
            read(path, "property." + name + ".type", () -> node.getValueType(name));
            read(path, "property." + name + ".value", () -> propertyValue(node, name, node.getValueType(name)));
        }
    }

    private static String parameterValue(ParameterEntity node, String name, String type) {
        switch (type) {
            case "String": return node.getString(name);
            case "StringArray": return Arrays.toString(node.getStringArray(name));
            case "StringMatrix": return Arrays.deepToString(node.getStringMatrix(name));
            case "DoubleArray": return Arrays.toString(node.getDoubleArray(name));
            case "DoubleMatrix": return Arrays.deepToString(node.getDoubleMatrix(name));
            default: return "not_read: unsupported_value_type=" + type;
        }
    }

    private static void parameters(String path, ParameterEntity node) throws IOException {
        for (String name : node.properties()) {
            read(path, "property." + name + ".type", () -> node.getValueType(name));
            read(path, "property." + name + ".value", () -> parameterValue(node, name, node.getValueType(name)));
        }
    }

    private static void modelParameters(String path, ExpressionBase params, ParamBase evaluator) throws IOException {
        for (String name : params.varnames()) {
            read(path, name + ".expression", () -> params.get(name));
            read(path, name + ".unit", () -> evaluator.evaluateUnit(name));
        }
    }

    private static void functions(String path, FunctionFeatureList list) throws IOException {
        for (String tag : list.tags()) {
            FunctionFeature f = list.get(tag);
            String p = path + "/" + tag;
            row(p, "type", f.getType());
            row(p, "active", Boolean.toString(f.isActive()));
            row(p, "function_names", Arrays.toString(f.functionNames()));
            properties(p, f);
            functions(p + "/feature", f.feature());
        }
    }

    // Expr/ModelParamGroup share ExpressionBase. A variable declaration is not
    // a parameter and must not be evaluated through model.param().
    private static void variables(String path, ExprList list) throws IOException {
        for (String tag : list.tags()) {
            Expr v = list.get(tag);
            String p = path + "/" + tag;
            selection(p + "/selection", v.selection());
            for (String name : v.varnames()) {
                read(p, name + ".expression", () -> v.get(name));
                row(p, name + ".unit", "not_read: variable_unit_requires_context_review");
            }
        }
    }

    private static void physicsFeature(String path, PhysicsFeature f) throws IOException {
        row(path, "type", f.getType());
        row(path, "active", Boolean.toString(f.isActive()));
        selection(path + "/selection", f.selection());
        parameters(path, f);
        for (String tag : f.feature().tags()) physicsFeature(path + "/" + tag, f.feature(tag));
    }

    private static void material(String path, Material m) throws IOException {
        row(path, "type", m.materialType());
        row(path, "active", Boolean.toString(m.isActive()));
        selection(path + "/selection", m.selection());
        properties(path, m);
        for (String group : m.propertyGroup().tags()) {
            MaterialModel pg = m.propertyGroup(group);
            String p = path + "/propertyGroup/" + group;
            row(p, "type", pg.getType());
            row(p, "inputs", Arrays.toString(pg.input()));
            parameters(p, pg);
            functions(p + "/func", pg.func());
        }
        for (String tag : m.feature().tags()) material(path + "/feature/" + tag, m.feature(tag));
    }

    private static void geometryFeature(String path, GeomFeature f) throws IOException {
        row(path, "type", f.getType());
        read(path, "status", () -> f.status());
        read(path, "has_error", () -> Boolean.toString(f.hasError()));
        read(path, "has_warning", () -> Boolean.toString(f.hasWarning()));
        read(path, "message", () -> f.message());
        read(path, "errors", () -> Arrays.toString(f.errors()));
        read(path, "warnings", () -> Arrays.toString(f.warnings()));
        for (String tag : f.feature().tags()) geometryFeature(path + "/" + tag, f.feature(tag));
    }

    private static void inventory(Model model) throws IOException {
        row("model", "runtime_version", ModelUtil.getComsolVersion());
        row("model", "saved_version", model.getComsolVersion());
        row("model", "used_products", Arrays.toString(model.getUsedProducts()));
        row("model", "file_resource_tags", Arrays.toString(model.file().tags()));
        row("model", "external_interface_tags", Arrays.toString(model.externalInterface().tags()));
        row("model", "component_tags", Arrays.toString(model.component().tags()));
        row("model", "parameter_group_tags", Arrays.toString(model.param().group().tags()));
        row("model", "function_tags", Arrays.toString(model.func().tags()));
        row("model", "variable_tags", Arrays.toString(model.variable().tags()));
        row("model", "material_tags", Arrays.toString(model.material().tags()));
        modelParameters("model/param", model.param(), model.param());
        for (String tag : model.param().group().tags()) modelParameters("model/paramGroup/" + tag, model.param(tag), model.param());
        functions("model/func", model.func());
        variables("model/variable", model.variable());
        for (String tag : model.material().tags()) material("model/material/" + tag, model.material(tag));
        row("old_nodes", "study_tags", Arrays.toString(model.study().tags()));
        row("old_nodes", "solver_tags", Arrays.toString(model.sol().tags()));
        row("old_nodes", "batch_tags", Arrays.toString(model.batch().tags()));
        row("old_nodes", "validity", "unknown: requires modification dependency assessment");

        for (String ctag : model.component().tags()) {
            ModelNode c = model.component(ctag);
            String p = "component/" + ctag;
            row(p, "type", c.getType());
            row(p, "coordinate_system_tags", Arrays.toString(c.coordSystem().tags()));
            row(p, "function_tags", Arrays.toString(c.func().tags()));
            row(p, "variable_tags", Arrays.toString(c.variable().tags()));
            row(p, "geometry_shape_order", c.sorder());
            for (String tag : c.coordSystem().tags()) {
                String cp = p + "/coordSystem/" + tag;
                row(cp, "type", c.coordSystem(tag).getType());
                properties(cp, c.coordSystem(tag));
            }
            row(p, "multiphysics_tags", Arrays.toString(c.multiphysics().tags()));
            row(p, "mesh_tags_read_only", Arrays.toString(c.mesh().tags()));
            functions(p + "/func", c.func());
            variables(p + "/variable", c.variable());
            for (String gtag : c.geom().tags()) {
                GeomSequence g = c.geom(gtag);
                String gp = p + "/geom/" + gtag;
                row(gp, "space_dimension", Integer.toString(g.getSDim()));
                row(gp, "length_unit", g.lengthUnit());
                read(gp, "problem_tags", () -> Arrays.toString(g.problems()));
                for (String tag : g.feature().tags()) geometryFeature(gp + "/" + tag, g.feature(tag));
                row(gp, "geometry_build_executed_by_this_audit", "false");
            }
            for (String tag : c.selection().tags()) selection(p + "/selection/" + tag, c.selection(tag));
            for (String tag : c.pair().tags()) {
                Pair pair = c.pair(tag);
                String pp = p + "/pair/" + tag;
                row(pp, "type", pair.type());
                row(pp, "source_frame", pair.srcFrame());
                row(pp, "destination_frame", pair.dstFrame());
                selection(pp + "/source", pair.source());
                selection(pp + "/destination", pair.destination());
                row(pp, "mapping_correctness", "not_run");
            }
            for (String tag : c.material().tags()) material(p + "/material/" + tag, c.material(tag));
            for (String tag : c.physics().tags()) {
                Physics ph = c.physics(tag);
                String pp = p + "/physics/" + tag;
                row(pp, "type", ph.getType());
                row(pp, "active", Boolean.toString(ph.isActive()));
                row(pp, "geometry", ph.geom());
                selection(pp + "/selection", ph.selection());
                row(pp, "property_group_tags", Arrays.toString(ph.prop().tags()));
                for (String ptag : ph.prop().tags()) parameters(pp + "/prop/" + ptag, ph.prop(ptag));
                for (String ftag : ph.feature().tags()) physicsFeature(pp + "/" + ftag, ph.feature(ftag));
                row(pp, "effective_constitutive_and_boundary_check", "not_run");
                row(pp, "material_coverage_check", "not_run");
            }
        }
    }

    private static String required(Properties job, String key) {
        String value = job.getProperty(key);
        if (value == null || value.trim().isEmpty()) throw new IllegalArgumentException("Missing job.properties key: " + key);
        return value.trim();
    }

    private static void inspect() throws Exception {
        readErrors = 0;
        Properties job = new Properties();
        try (BufferedReader r = Files.newBufferedReader(Paths.get("job.properties"), StandardCharsets.UTF_8)) {
            r.mark(1);
            if (r.read() != 0xFEFF) r.reset();
            String raw;
            while ((raw = r.readLine()) != null) {
                String line = raw.trim();
                if (line.isEmpty() || line.startsWith("#") || line.startsWith("!")) continue;
                int separator = line.indexOf('=');
                if (line.indexOf('\\') >= 0 || separator < 1) throw new IllegalArgumentException("Use key=value without escapes or continuation");
                String key = line.substring(0, separator).trim();
                String value = line.substring(separator + 1).trim();
                if (!key.matches("[A-Za-z_][A-Za-z0-9_.-]*") || job.containsKey(key)) throw new IllegalArgumentException("Invalid or duplicate job key");
                job.setProperty(key, value);
            }
        }
        Path declaredInput = Paths.get(required(job, "input_model"));
        if (!declaredInput.isAbsolute()) throw new IllegalArgumentException("input_model must be absolute");
        Path input = declaredInput.toRealPath();
        Path run = Paths.get("").toRealPath();
        Path audit = Paths.get(required(job, "audit_output")).toAbsolutePath().normalize();
        if (!input.toString().toLowerCase(java.util.Locale.ROOT).endsWith(".mph")) throw new IllegalArgumentException("input_model must be an MPH file");
        if (!audit.toString().toLowerCase(java.util.Locale.ROOT).endsWith(".tsv")) throw new IllegalArgumentException("audit_output must be a new TSV file");
        if (audit.equals(input)) throw new IllegalArgumentException("Audit output cannot overwrite input");
        if (!audit.startsWith(run) || audit.equals(run)) throw new IllegalArgumentException("audit_output must remain inside the run directory");
        Path existingParent = audit.getParent();
        while (existingParent != null && !Files.exists(existingParent)) existingParent = existingParent.getParent();
        if (existingParent == null || !existingParent.toRealPath().startsWith(run)) throw new IllegalArgumentException("audit_output parent resolves outside the run directory");
        Files.createDirectories(audit.getParent());
        if (!audit.getParent().toRealPath().startsWith(run)) throw new IllegalArgumentException("audit_output parent changed outside the run directory");
        String modelTag = ModelUtil.uniquetag("inspect");
        boolean loaded = false;
        try (BufferedWriter writer = Files.newBufferedWriter(audit, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            out = writer;
            row("object", "field", "value");
            row("audit", "kind", "read_only_inventory");
            row("audit", "overall_model_validation", "incomplete");
            row("audit", "input_model", input.toString());
            row("audit", "mesh_validation", "not_run");
            row("audit", "solver_validation", "not_run");
            row("audit", "dependency_file_completeness", "not_run: inspect recorded references separately");
            Model model = ModelUtil.loadCopy(modelTag, input.toString());
            loaded = true;
            row("audit", "load_check", "passed: this input loaded in this invocation");
            try {
                inventory(model);
            } catch (Exception e) {
                readErrors++;
                row("audit", "inventory.read_error", e.getClass().getName() + ": " + e.getMessage());
                row("audit", "inventory_status", "aborted_with_read_error");
                row("audit", "read_error_count", Integer.toString(readErrors));
                throw e;
            }
            row("audit", "read_error_count", Integer.toString(readErrors));
            row("audit", "inventory_status", readErrors == 0 ? "completed" : "incomplete_with_read_errors");
        } finally {
            out = null;
            if (loaded) ModelUtil.remove(modelTag);
        }
        if (readErrors != 0) throw new IllegalStateException("Inventory had " + readErrors + " read errors; see TSV");
    }

    public static void main(String[] args) {
        try {
            inspect();
        } catch (Exception e) {
            e.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
