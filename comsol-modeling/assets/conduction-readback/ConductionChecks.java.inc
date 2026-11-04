// Same-top-level-class READ-ONLY recipe for reviewed 2D standard isotropic solid conduction.
// __CONDUCTION_RECORD__ is bound by render.py to an explicitly declared static recorder.
// Generated into each new/modify/independent-check source; not a complete model.
// No dimensions, material values, entity IDs or tolerance defaults are supplied.
    private static void crRequire(boolean value, String name, String observed) {
        __CONDUCTION_RECORD__(value, name, observed);
        if (!value) throw new IllegalStateException(name + ": " + observed);
    }
    private static java.util.Set<Integer> crIds(int[] values) {
        java.util.Set<Integer> result = new java.util.HashSet<Integer>();
        for (int value : values) result.add(value);
        return result;
    }
    static boolean crExactIsotropic(String[] observed, String expected) {
        if (expected == null || expected.trim().isEmpty()) return false;
        return java.util.Arrays.equals(observed, new String[]{expected}) ||
            java.util.Arrays.equals(observed, new String[]{expected,"0","0","0",expected,"0","0","0",expected});
    }
    private static void crDisabled(com.comsol.model.ParameterEntity node, String key) {
        String type = node.getValueType(key);
        boolean off;
        if ("Boolean".equals(type)) off = !node.getBoolean(key);
        else if ("String".equals(type)) off = "0".equals(node.getString(key));
        else throw new IllegalStateException("Unread/unverified flag representation: " + key + "=" + type);
        crRequire(off, "disabled:" + key, type + "; actual readback required");
    }
    private static void crKnownFeature(com.comsol.model.physics.PhysicsFeature feature) {
        String type = feature.getType();
        java.util.Set<String> allowed = new java.util.HashSet<String>(java.util.Arrays.asList(
            "SolidHeatTransferModel", "init", "ThermalInsulation", "IsothermalDomainInterface",
            "LocalThermalNonequilibriumBoundary", "OpaqueSurface", "ContinuityOnInteriorBoundary",
            "Continuity", "TemperatureBoundary", "Opacity", "LayerOpacity"));
        crRequire(allowed.contains(type), "feature_type:" + feature.tag(), String.valueOf(type));
        if ("LayerOpacity".equals(type))
            crRequire(!feature.isActive(), "inactive_layer_opacity:" + feature.tag(), "Actual inactive state, after related physical flags were checked");
        for (String tag : feature.feature().tags()) crKnownFeature(feature.feature(tag));
    }
    static void crCheck(com.comsol.model.Model model, String component, String geometry,
            String physics, String solidTag, String material, String materialGroup,
            String domainSelection, String conductivityExpression, String thicknessExpression) {
        // All tags and expressions come from the current reviewed problem.
        crRequire(model.component(component).geom(geometry).getSDim() == 2,
            "recipe_scope", "This readback recipe only covers reviewed 2D standard solid conduction");
        crRequire(geometry.equals(model.component(component).selection(domainSelection).geom()) &&
            model.component(component).selection(domainSelection).dim() == 2,
            "expected_domain_identity", domainSelection);
        java.util.Set<Integer> expected = crIds(model.component(component).selection(domainSelection).entities(2));
        crRequire(!expected.isEmpty(), "expected_domain_nonempty", expected.toString());
        crRequire("HeatTransfer".equals(model.component(component).physics(physics).getType()) &&
            model.component(component).physics(physics).isActive(), "heat_interface", physics);
        crRequire(geometry.equals(model.component(component).physics(physics).geom()) &&
            geometry.equals(model.component(component).physics(physics).selection().geom()) &&
            model.component(component).physics(physics).selection().dim() == 2,
            "physics_geometry_dimension", physics);
        crRequire(expected.equals(crIds(model.component(component).physics(physics).selection().entities(2))),
            "physics_domain_coverage", expected.toString());
        com.comsol.model.ParameterEntity physical = model.component(component).physics(physics).prop("PhysicalModelProperty");
        crRequire("userdef".equals(physical.getString("dz_src")) &&
            thicknessExpression != null && !thicknessExpression.trim().isEmpty() &&
            thicknessExpression.equals(physical.getString("dz")), "physical_thickness", String.valueOf(thicknessExpression));
        // These readbacks are prerequisites for accepting inactive LayerOpacity.
        for (String key : new String[]{"SurfaceToSurfaceRadiation", "IsothermalDomain", "HeatTransferInPorousMedia"})
            crDisabled(physical, key);
        com.comsol.model.physics.PhysicsFeature solid = model.component(component).physics(physics).feature(solidTag);
        crRequire("SolidHeatTransferModel".equals(solid.getType()) && solid.isActive(), "solid_type_active", solidTag);
        // The default Solid selection may be locked. Do not call selection().named/set/all on it.
        crRequire(geometry.equals(solid.selection().geom()) && solid.selection().dim() == 2,
            "solid_geometry_dimension", solidTag);
        crRequire(expected.equals(crIds(solid.selection().entities(2))), "solid_actual_domain_coverage", expected.toString());
        crRequire("from_mat".equals(solid.getString("k_mat")) && "dommat".equals(solid.getString("Solid_material")) &&
            "Standard".equals(solid.getString("thermalConductivityModel")) &&
            "GlobalSystem".equals(solid.getString("coordinateSystem")), "solid_constitutive_sources", solidTag);
        crRequire(geometry.equals(model.component(component).material(material).selection().geom()) &&
            model.component(component).material(material).selection().dim() == 2,
            "material_geometry_dimension", material);
        crRequire(model.component(component).material(material).isActive() &&
            expected.equals(crIds(model.component(component).material(material).selection().entities(2))),
            "material_actual_domain_coverage", material);
        String[] conductivity = model.component(component).material(material).propertyGroup(materialGroup).getStringArray("thermalconductivity");
        crRequire(crExactIsotropic(conductivity, conductivityExpression), "isotropic_conductivity", java.util.Arrays.toString(conductivity));
        for (String tag : model.component(component).physics(physics).feature().tags())
            crKnownFeature(model.component(component).physics(physics).feature(tag));
    }
