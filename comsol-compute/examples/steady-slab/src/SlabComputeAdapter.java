import com.comsol.model.*;
import com.comsol.model.util.*;
import java.io.*;
import java.lang.reflect.Array;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Prepared COMSOL 6.3 model-file-for-Java; Candidate port; this revision has NOT been compiled or run.
 * No geometry/material/physics/BC/physical-initial-state setter is present.
 * All case-specific tags, parameter expectations and result expressions come
 * from a case-spec-derived UTF-8 Properties file prepared by the Python driver.
 * Live validation uses a fresh per-phase cwd/job.properties, without getenv.
 */
public class SlabComputeAdapter {
  private static final String[] PARAMS = {"L", "H", "thickness", "k_slab", "T_left", "T_right"};
  private static final String[] SELECTIONS = {"domain", "left", "right", "bottom", "top", "insulated"};
  private static Properties p;
  private static Path job;

  public static void main(String[] args) { run(); }

  /** COMSOL batch class entry: only this branch's explicit instructions execute. */
  public static Model run() {
    try {
      job = Paths.get("job.properties").toRealPath();
      p = new Properties();
      try (Reader r = Files.newBufferedReader(job, StandardCharsets.UTF_8)) { p.load(r); }
      String mode = required("mode");
      require(Arrays.asList("solve", "readback", "export").contains(mode), "Unsupported mode");
      // A parent-reviewed operation + current authorization is required before launching.
      // This flag prevents accidentally launching a preparation-only properties file.
      require("true".equals(required("execution_authorized")), "Preparation only: no execution authorization");
      required("run_id"); required("fingerprint"); required("case_spec_sha256");
      Path input = existing("input_mph");
      String originalHash = sha(input);
      require(originalHash.equals(required("input_sha256")),"Phase input differs from reviewed/pinned source");
      checkOutputPaths(mode, input);
      Model m = ModelUtil.load("compute_" + required("run_id").replaceAll("[^a-zA-Z0-9_]", "_"), input.toString());
      preflight(m);
      if (mode.equals("solve")) {
        solve(m, input, originalHash);
      } else {
        // NO study.run, mesh.run, sol.runAll or model.save in this branch.
        readback(m, input, originalHash, mode);
      }
      require(sha(input).equals(originalHash), "Input MPH changed during operation");
      return m;
    } catch (Exception e) {
      e.printStackTrace(System.err); // preserve concrete API cause in this live validation
      throw new IllegalStateException("Slab adapter failed; no completion evidence may be accepted", e);
    }
  }

  private static void preflight(Model m) {
    String c = required("component"), g = required("geometry"), h = required("physics");
    require(Arrays.equals(m.component().tags(), new String[]{c}), "Unexpected components; return to modeling");
    require(Arrays.equals(m.component(c).geom().tags(), new String[]{g}), "Unexpected geometry sequence");
    require(m.component(c).geom(g).getSDim() == 2 && !m.component(c).geom(g).isAxisymmetric(), "Requires Cartesian 2D");
    require("m".equals(m.component(c).geom(g).lengthUnit()), "Expected case geometry length unit m");
    require(Arrays.equals(m.component(c).physics().tags(), new String[]{h}), "Additional/missing physics; return to modeling");
    require(m.component(c).physics(h).getType().equals(required("physics_type")), "Unexpected physics type");
    require(m.component(c).physics(h).isActive(), "Heat physics is inactive; return to modeling");
    require(g.equals(m.component(c).physics(h).geom()), "Physics geometry mismatch");
    require(Arrays.asList(m.component(c).material().tags()).contains(required("material")), "Missing material");
    for (String k : PARAMS) {
      require(m.param().get(k).replaceAll("\\s+", "").equals(required("expected." + k).replaceAll("\\s+", "")),
              "Parameter differs from shared case: " + k + "; return to modeling");
      require(Double.isFinite(m.param().evaluate(k)), "Nonfinite parameter: " + k);
    }
    for (String s : SELECTIONS) {
      String tag = required("selection." + s);
      require(Arrays.asList(m.component(c).selection().tags()).contains(tag), "Missing named selection: " + tag);
      int dim = s.equals("domain") ? 2 : 1, count = s.equals("insulated") ? 2 : 1;
      require(m.component(c).selection(tag).dim() == dim, "Selection dimension mismatch: " + tag);
      require(m.component(c).selection(tag).entities(dim).length == count, "Selection count mismatch: " + tag);
    }
    int[] left = selected(m, "left"), right = selected(m, "right"), insulated = selected(m, "insulated");
    require(left[0] != right[0], "Left/right overlap");
    require(!contains(insulated, left[0]) && !contains(insulated, right[0]), "Dirichlet/insulated selections overlap");
    int[] topBottom = {selected(m, "top")[0], selected(m, "bottom")[0]};
    sameEntities(insulated, topBottom, "Insulation union mismatch");
    sameEntities(m.component(c).physics(h).selection().entities(2), selected(m, "domain"), "Physics coverage mismatch");
    sameEntities(m.component(c).material(required("material")).selection().entities(2), selected(m, "domain"), "Material coverage mismatch");
    sameEntities(m.component(c).physics(h).feature(required("temperature_left")).selection().entities(1), left, "Left BC selection mismatch");
    sameEntities(m.component(c).physics(h).feature(required("temperature_right")).selection().entities(1), right, "Right BC selection mismatch");
    // COMSOL's default insulation is an all-boundary fallback; the named
    // temperature features override it on left/right. Do not change that model.
    int[] actualInsulation = m.component(c).physics(h).feature(required("insulation")).selection().entities(1);
    for (int boundary : insulated) require(contains(actualInsulation, boundary), "Insulation does not cover a residual boundary");
    require(m.component(c).physics(h).feature(required("temperature_left")).isActive()
        && m.component(c).physics(h).feature(required("temperature_right")).isActive()
        && m.component(c).physics(h).feature(required("insulation")).isActive(), "Inactive boundary feature");
    // Tag/count/association checks do not substitute for the modeling-side spatial,
    // constitutive, thickness, and boundary-value inspection bound to this MPH.
  }

  private static void solve(Model m, Path input, String inputHash) throws Exception {
    String c = required("component"), g = required("geometry"), mesh = required("mesh_tag"), study = required("study_tag");
    require(!Arrays.asList(m.component(c).mesh().tags()).contains(mesh), "Mesh tag collision; do not overwrite");
    require(!Arrays.asList(m.study().tags()).contains(study), "Study tag collision; do not overwrite");
    require(m.sol().tags().length == 0, "Fresh solve requires the inspected unsolved input");
    MeshSequence ms = m.component(c).mesh().create(mesh, g);
    ms.feature("size").set("custom", "on");
    ms.feature("size").set("hmax", required("mesh_hmax"));
    ms.feature("size").set("hmin", required("mesh_hmin"));
    ms.create("tri", "FreeTri");
    ms.feature("tri").selection().named(required("selection.domain"));
    ms.run();
    require(!ms.isEmpty() && ms.getNumElem("tri") > 0, "No actual triangular mesh");
    m.study().create(study);
    m.study(study).create("stat", "Stationary");
    m.study(study).feature("stat").set("mesh", new String[]{g, mesh});
    m.study(study).feature("stat").set("usestol", true);
    m.study(study).feature("stat").set("stol", required("solver_rtol"));
    // COMSOL's documented generator supplies dependent-variable, stationary and
    // linear-solver nodes appropriate to the unchanged input physics.
    m.study(study).createAutoSequences("sol");
    String[] filtered = m.study(study).getSolverSequences("SolverSequence");
    String[] all = m.study(study).getSolverSequences("All");
    String[] solvers = m.sol().tags();
    List<String> candidates = new ArrayList<String>();
    Map<String,Object> owners = new LinkedHashMap<String,Object>();
    for (String tag : solvers) { String owner=m.sol(tag).study(); owners.put(tag,owner); if(study.equals(owner)) candidates.add(tag); }
    System.out.println("SOLVER_DISCOVERY " + json(map("filtered", filtered, "all_related", all, "actual_tags", solvers, "owning_studies", owners)));
    require(candidates.size() == 1 && solvers.length == 1, "This fresh-slab adapter requires one unambiguous actual solver belonging to the requested study");
    String sol = candidates.get(0);
    require(study.equals(m.sol(sol).study()), "Generated solver is not bound to the requested study");
    m.sol(sol).runAll();
    int[] size = requireStationarySolution(m, sol);
    Path output = newPath("output_mph");
    m.save(output.toString());
    require(Files.size(output) > 0, "Empty saved MPH");
    require(sha(input).equals(inputHash), "Input MPH changed");
    String[] featureTags = m.sol(sol).feature().tags();
    String[] types = new String[featureTags.length];
    for (int i=0; i<featureTags.length; i++) types[i] = m.sol(sol).feature(featureTags[i]).getType();
    Map<String,Object> out = identity("solve_saved_pending_independent_readback");
    out.put("source_mph", input.toString()); out.put("source_sha256", inputHash);
    out.put("output_mph", output.toString()); out.put("output_sha256", sha(output));
    out.put("solver_discovery", map("filtered",filtered,"all_related",all,"actual_tags",solvers,"owning_studies",owners));
    out.put("solution_tag", sol); out.put("study_tag", study); out.put("mesh_tag", mesh);
    out.put("solver_type", m.sol(sol).getType()); out.put("solution_count", size[1]); out.put("dofs", size[0]);
    out.put("solver_feature_tags", featureTags); out.put("solver_feature_types", types);
    out.put("solver_configuration", "COMSOL-generated default sequence + explicit study relative tolerance");
    out.put("solver_rtol", required("solver_rtol"));
    out.put("solver_initial_guess", "Inherited generated stationary initialization; no physical Initial Values node changed");
    out.put("physical_initial_state", "Not applicable for this shared steady case");
    write(newPath("solve_metadata"), out);
    // This receipt is deliberately NOT a final completion marker.
  }

  private static int[] requireStationarySolution(Model m, String sol) {
    require(Arrays.asList(m.sol().tags()).contains(sol), "Required solution does not exist; extraction cannot solve");
    require(!m.sol(sol).isEmpty(), "Required solution is empty; extraction cannot solve");
    require("Stationary".equals(m.sol(sol).getType()), "Only a single stationary solution is supported");
    int[] size = m.sol(sol).getSize();
    require(size.length == 2 && size[0] > 0 && size[1] == 1, "Solution shape is not one solved stationary field");
    require(m.sol(sol).isRealU(1), "Unexpected complex solution");
    double[] u = m.sol(sol).getU(1);
    require(u.length > 0, "Missing actual solution vector");
    for (double value : u) require(Double.isFinite(value), "Nonfinite solution vector");
    return size;
  }

  private static void readback(Model m, Path input, String inputHash, String mode) throws Exception {
    String c = required("component"), mesh = required("mesh_tag"), sol = required("solution_tag");
    int[] size = requireStationarySolution(m, sol); // checked BEFORE creating result nodes
    require(Arrays.asList(m.component(c).mesh().tags()).contains(mesh), "Expected saved mesh does not exist");
    MeshSequence ms = m.component(c).mesh(mesh);
    require(!ms.isEmpty(), "Saved mesh is empty; extraction does not regenerate it");
    Map<String,Object> meshBinding = verifySolutionMesh(m, sol, ms, inputHash);
    String ds = required("dataset_tag");
    require(!Arrays.asList(m.result().dataset().tags()).contains(ds), "Readback dataset tag collision");
    m.result().dataset().create(ds, "Solution");
    m.result().dataset(ds).set("solution", sol);
    m.result().dataset(ds).set("comp", c);
    m.result().dataset(ds).set("geom", required("geometry"));
    int nx = Integer.parseInt(required("sample_nx")), ny = Integer.parseInt(required("sample_ny"));
    require(nx >= 2 && ny >= 2 && nx <= 1000 && ny <= 1000, "Invalid or excessive sample grid");
    double L=m.param().evaluate("L"), H=m.param().evaluate("H");
    double[][] coords = new double[2][nx*ny];
    int cursor=0;
    for (int j=0;j<ny;j++) for (int i=0;i<nx;i++) {
      coords[0][cursor]=L*i/(nx-1); coords[1][cursor]=H*j/(ny-1); cursor++;
    }
    double[] temperature = sample(m, ds, "cc_temp", "target.temperature", coords);
    double[] qx = sample(m, ds, "cc_qx", "target.flux_x", coords);
    double[] qy = sample(m, ds, "cc_qy", "target.flux_y", coords);
    assertSingleExteriorRightBoundary(m, ms);
    String integral = "cc_rate";
    require(!Arrays.asList(m.result().numerical().tags()).contains(integral), "Integral tag collision");
    m.result().numerical().create(integral, "IntLine");
    m.result().numerical(integral).set("data", ds);
    m.result().numerical(integral).selection().named(required("selection.right"));
    m.result().numerical(integral).set("expr", new String[]{required("target.heat_rate.expression")});
    m.result().numerical(integral).set("unit", new String[]{required("target.heat_rate.unit")});
    m.result().numerical(integral).set("dataseries", "none");
    m.result().numerical(integral).set("solrepresentation", "solnum");
    m.result().numerical(integral).set("innerinput", "manual");
    m.result().numerical(integral).set("solnum", new int[]{1});
    // Cartesian IntLine integrates along length. Axisymmetric conversion is
    // inapplicable (preflight rejects axisymmetry); explicitly disable if exposed.
    if (m.result().numerical(integral).hasProperty("intsurface"))
      m.result().numerical(integral).set("intsurface", "off");
    require(!m.result().numerical(integral).isComplex(), "Complex heat-rate result");
    double[][] heat = m.result().numerical(integral).getReal();
    require(heat.length == 1 && heat[0].length == 1 && Double.isFinite(heat[0][0]), "Invalid heat-rate result shape/value");
    double[][] vertexRows = ms.getVertex();
    int nv = ms.getNumVertex();
    require(vertexRows.length == 2 && vertexRows[0].length == nv && vertexRows[1].length == nv && nv > 0, "Unexpected mesh coordinate layout");
    Map<String,Object> vertices = map("coordinate_rows", vertexRows, "columns_are_vertices", true, "coordinate_unit", "m");
    Map<String,Object> elementTypes = new LinkedHashMap<String,Object>();
    Set<Integer> seen = new HashSet<Integer>();
    for (String type : ms.getTypes()) {
      int[][] conn = ms.getElem(type);
      int[] entities = ms.getElemEntity(type);
      for (int[] row : conn) {
        require(row.length == entities.length, "Element/entity array mismatch");
        for (int index : row) {
          require(index >= 0 && index < nv, "Unverified mesh vertex index convention; stop, do not shift indices");
          seen.add(index);
        }
      }
      elementTypes.put(type, map("connectivity_rows", conn, "entity_ids", entities));
    }
    // getElem docs identify vertex indices, but do not explicitly state the
    // base. Require actual complete 0..N-1 coverage before exposing that base;
    // absence of 0, unused vertices, or another convention is a hard stop.
    require(seen.size() == nv && seen.contains(0) && seen.contains(nv-1), "Mesh index base not established by readback");
    write(newPath("mesh_vertices"), vertices);
    write(newPath("mesh_elements"), map("types", elementTypes, "indices_as_returned", true, "index_base", 0,
        "index_base_evidence", "All N vertex indices actually observed, minimum 0, maximum N-1; no remapping"));
    Map<String,Object> selections = new LinkedHashMap<String,Object>();
    Map<String,Object> localStats = new LinkedHashMap<String,Object>();
    for (String name : SELECTIONS) {
      selections.put(name, selected(m, name));
      int statDim=name.equals("domain")?2:1;
      ms.stat().selection().geom(statDim);
      ms.stat().selection().named(required("selection." + name));
      require(ms.stat().selection().dim()==statDim,"Statistics selection dimension mismatch");
      localStats.put(name, map("entity_dimension", ms.stat().selection().dim(), "num_elements", ms.stat().getNumElem(), "min_quality", ms.stat().getMinQuality(),
          "mean_quality", ms.stat().getMeanQuality(), "quality_measure", ms.stat().getQualityMeasure()));
    }
    ms.stat().selection().geom(2); // all() alone retains previous boundary dimension
    ms.stat().selection().all();
    require(ms.stat().selection().dim()==2,"Domain statistics dimension not restored");
    Map<String,Object> stats = map("entity_dimension",ms.stat().selection().dim(), "num_vertices", ms.getNumVertex(), "num_tri", ms.getNumElem("tri"),
        "num_edg", ms.getNumElem("edg"), "min_quality", ms.stat().getMinQuality(),
        "mean_quality", ms.stat().getMeanQuality(), "quality_measure", ms.stat().getQualityMeasure(),
        "geometry_shape_order", m.component(c).sorder(), "local_selection_stats", localStats);
    Map<String,Object> targets = map(
        "temperature_field", map("expression", required("target.temperature.expression"), "unit", required("target.temperature.unit"), "values", temperature),
        "conductive_heat_flux", map("expressions", new String[]{required("target.flux_x.expression"),required("target.flux_y.expression")}, "unit", required("target.flux_x.unit"), "values", new double[][]{qx,qy}),
        "through_heat_rate", map("expression", required("target.heat_rate.expression"), "unit", required("target.heat_rate.unit"), "value", heat[0][0]));
    Map<String,Object> out = identity("independent_saved_solution_readback");
    out.put("mode", mode); out.put("source_mph", input.toString()); out.put("source_sha256", inputHash);
    out.put("solution_tag", sol); out.put("dataset_tag", ds); out.put("dataset_lifetime", "in-memory readback process only"); out.put("dataset_persisted", false);
    out.put("solver_type", m.sol(sol).getType()); out.put("solution_count", size[1]); out.put("inner_solnum", 1); out.put("dofs", size[0]);
    out.put("solution_mesh_tag", meshBinding.get("sequence_tag"));
    out.put("solution_mesh_binding", meshBinding);
    out.put("sample_coordinates", coords); out.put("coordinate_unit", "m"); out.put("sampling", "Explicit regular point grid; saved MPH holds full FE field");
    out.put("target_values", targets); out.put("mesh", stats); out.put("selection_entities", selections);
    out.put("mesh_vertices_sha256", sha(existing("mesh_vertices"))); out.put("mesh_elements_sha256", sha(existing("mesh_elements")));
    Map<String,Object> parameters = new LinkedHashMap<String,Object>();
    Map<String,Object> parametersSI = new LinkedHashMap<String,Object>();
    for(String name:PARAMS) {parameters.put(name,map("expression",m.param().get(name),"value_SI",m.param().evaluate(name)));parametersSI.put(name,m.param().evaluate(name));}
    out.put("parameters", parameters);
    out.put("parameters_si", parametersSI);
    out.put("thickness_rule", "Right-boundary IntLine of qx*thickness; Cartesian length integral, exactly one explicit thickness factor");
    require(sha(input).equals(inputHash), "Source MPH changed during readback");
    write(newPath("raw_readback"), out);
    // No save: the source MPH and its already computed solution remain untouched.
  }


  private static void assertSingleExteriorRightBoundary(Model m, MeshSequence ms) {
    int[][] edges=ms.getElem("edg"), tri=ms.getElem("tri");int[] entity=ms.getElemEntity("edg");
    require(edges.length==2 && tri.length==3,"Only straight triangle mesh boundary traces supported");
    int right=selected(m,"right")[0],matched=0;double[][] xy=ms.getVertex();double L=m.param().evaluate("L");
    for(int e=0;e<entity.length;e++)if(entity[e]==right) {
      int a=edges[0][e],b=edges[1][e],adj=0;
      require(xy[0][a]==L && xy[0][b]==L,"Right boundary must be Cartesian x=L");
      for(int t=0;t<tri[0].length;t++) {
        boolean ca=false,cb=false;for(int k=0;k<3;k++){ca|=tri[k][t]==a;cb|=tri[k][t]==b;}
        if(ca&&cb)adj++;
      }
      require(adj==1,"mean(d(T,x)) trace only supports one-adjacent-domain exterior boundary");matched++;
    }
    require(matched>0,"No actual right-boundary edges");
  }

  private static Map<String,Object> verifySolutionMesh(Model m, String sol, MeshSequence ms, String inputHash) {
    String geom=required("geometry"), study=m.sol(sol).study();
    XmeshInfo xm=m.sol(sol).xmeshInfo();
    require(Arrays.equals(xm.geoms(),new String[]{geom}),"Unexpected actual solution geometry set");
    require(Arrays.equals(xm.meshCases(),new String[]{"main"}),"Unexpected solution mesh cases");
    String getter=m.sol(sol).getMesh(geom);
    // COMSOL 6.3 returned an empty getMesh(geom1) for this saved solution.
    // Preserve that observation; prove identity from the actual FE mesh instead.
    require(getter.isEmpty() || getter.equals(ms.tag()),"Nonempty solution mesh tag contradicts actual sequence");
    require(study.equals(required("study_tag")),"Solution owning study mismatch");
    String studyMesh=m.study(study).feature("stat").mesh(geom);
    require(studyMesh.equals(ms.tag()),"Study mesh differs from saved mesh sequence");
    double[][] nodes=xm.nodes(geom).coords(), local=xm.elements("tri",geom).localCoords();
    int[][] tri=xm.elements("tri",geom).nodes();
    require(local.length==2 && tri.length==local[0].length && local[1].length==tri.length,"Unexpected FE triangle layout");
    require(tri.length==3 || tri.length==6,"Only the supported straight slab triangle layouts are implemented");
    int[] cornerRows=new int[]{-1,-1,-1}; double[][] corners={{0,0},{1,0},{0,1}};
    for(int k=0;k<3;k++)for(int row=0;row<tri.length;row++)
      if(local[0][row]==corners[k][0] && local[1][row]==corners[k][1]) {
        require(cornerRows[k]==-1,"Duplicate triangle corner in local layout");cornerRows[k]=row;
      }
    for(int row:cornerRows)require(row>=0,"Missing actual FE triangle corner");
    for(int row=0;row<tri.length;row++) {
      double x=local[0][row],y=local[1][row];
      require((x==0 || x==0.5 || x==1) && (y==0 || y==0.5 || y==1) && x+y<=1,"Unsupported reference layout");
      for(int e=0;e<tri[row].length;e++)for(int d=0;d<2;d++) {
        double expected=(1-x-y)*nodes[d][tri[cornerRows[0]][e]]+x*nodes[d][tri[cornerRows[1]][e]]+y*nodes[d][tri[cornerRows[2]][e]];
        require(nodes[d][tri[row][e]]==expected,"Non-affine FE nodes: corner correspondence does not cover curved elements");
      }
    }
    int[][] actualCorners=new int[3][];for(int k=0;k<3;k++)actualCorners[k]=tri[cornerRows[k]];
    List<String> actual=triangleKeys(nodes,actualCorners),sequence=triangleKeys(ms.getVertex(),ms.getElem("tri"));
    require(!actual.isEmpty() && actual.equals(sequence),"Actual solution triangle coordinates/connectivity differ from saved sequence");
    return map("method","exact_triangle_corner_coordinate_multiset",
      "scope","slab_2d_straight_triangle_corners_only", "source_sha256",inputHash,
      "run_id",required("run_id"),"fingerprint",required("fingerprint"),"case_spec_sha256",required("case_spec_sha256"),
      "geometry_tag",geom,"sequence_tag",ms.tag(),
      "solution_tag",sol,"study_tag",study,"study_mesh_tag",studyMesh,"get_mesh_returned",getter,
      "mesh_cases",xm.meshCases(),"solution_geometry_tags",xm.geoms(),"corner_rows",cornerRows,
      "matched_triangles",actual.size(),"node_coordinates",nodes,"triangle_node_indices",tri,"triangle_local_coordinates",local);
  }

  private static List<String> triangleKeys(double[][] coordinates,int[][] triangles) {
    require(coordinates.length==2 && coordinates[0].length==coordinates[1].length && triangles.length==3,"Unexpected triangle coordinates");
    int count=triangles[0].length;require(triangles[1].length==count && triangles[2].length==count,"Ragged triangle array");
    List<String> keys=new ArrayList<String>();
    for(int e=0;e<count;e++) {
      String[] points=new String[3];
      for(int k=0;k<3;k++) {int n=triangles[k][e];require(n>=0 && n<coordinates[0].length,"Invalid triangle node index");
        double x=coordinates[0][n],y=coordinates[1][n];require(Double.isFinite(x)&&Double.isFinite(y),"Nonfinite triangle coordinate");
        points[k]=Double.toHexString(x==0?0:x)+","+Double.toHexString(y==0?0:y);
      }
      Arrays.sort(points);require(!points[0].equals(points[1])&&!points[1].equals(points[2]),"Degenerate triangle corners");
      keys.add(String.join(";",points));
    }
    Collections.sort(keys);return keys;
  }

  private static double[] sample(Model m, String ds, String tag, String prefix, double[][] coords) {
    require(!Arrays.asList(m.result().numerical().tags()).contains(tag), "Numerical tag collision: " + tag);
    m.result().numerical().create(tag,"Interp");
    m.result().numerical(tag).set("data",ds);
    m.result().numerical(tag).selection().named(required("selection.domain"));
    m.result().numerical(tag).set("expr",new String[]{required(prefix+".expression")});
    m.result().numerical(tag).set("unit",required(prefix+".unit"));
    m.result().numerical(tag).set("solnum",new int[]{1});
    m.result().numerical(tag).set("coorderr","on");
    m.result().numerical(tag).set("matherr","on");
    m.result().numerical(tag).set("ext",0.0);
    m.result().numerical(tag).set("recover","off");
    m.result().numerical(tag).setInterpolationCoordinates(coords);
    require(!m.result().numerical(tag).isComplex(), "Unexpected complex sampled result");
    double[][][] values=m.result().numerical(tag).getData();
    require(values.length==1 && values[0].length==1 && values[0][0].length==coords[0].length,"Incomplete sample result");
    for(double v:values[0][0]) require(Double.isFinite(v),"Nonfinite sample value");
    return values[0][0];
  }

  private static Map<String,Object> identity(String status) throws Exception {
    return map("adapter","SlabComputeAdapter/candidate-port-20261102", "status",status,
        "run_id",required("run_id"), "fingerprint",required("fingerprint"),
        "case_spec_sha256",required("case_spec_sha256"), "job_properties_sha256",sha(job));
  }
  private static int[] selected(Model m,String name) { return m.component(required("component")).selection(required("selection."+name)).entities(name.equals("domain")?2:1); }
  private static boolean contains(int[] values,int value) { for(int x:values)if(x==value)return true;return false; }
  private static void sameEntities(int[] a,int[] b,String message) { a=a.clone();b=b.clone();Arrays.sort(a);Arrays.sort(b);require(Arrays.equals(a,b),message); }
  private static void require(boolean valid,String message) { if(!valid)throw new IllegalStateException(message); }
  private static String required(String key) { String s=p.getProperty(key);require(s!=null&&!s.trim().isEmpty(),"Missing job property: "+key);return s.trim(); }
  private static Path existing(String key)throws IOException { Path x=Paths.get(required(key));require(x.isAbsolute(),"Absolute path required: "+key);x=x.toRealPath();require(Files.isRegularFile(x),"Missing file: "+key);return x; }
  private static Path newPath(String key)throws IOException { Path x=Paths.get(required(key));require(x.isAbsolute(),"Absolute output path required: "+key);Path parent=x.getParent().toRealPath();x=parent.resolve(x.getFileName());require(!Files.exists(x),"Refusing to overwrite: "+x);return x; }
  private static void checkOutputPaths(String mode,Path input)throws IOException {
    String[] keys=mode.equals("solve")?new String[]{"output_mph","solve_metadata"}:new String[]{"raw_readback","mesh_vertices","mesh_elements"};
    Set<Path> paths=new HashSet<Path>();paths.add(input);paths.add(job);
    for(String key:keys)require(paths.add(newPath(key)),"Output/input paths collide: "+key);
  }
  private static String sha(Path path)throws Exception { MessageDigest d=MessageDigest.getInstance("SHA-256");try(InputStream in=Files.newInputStream(path)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)d.update(b,0,n);}StringBuilder s=new StringBuilder();for(byte x:d.digest())s.append(String.format(Locale.ROOT,"%02x",x&255));return s.toString(); }
  private static Map<String,Object> map(Object... kv) { Map<String,Object> m=new LinkedHashMap<String,Object>();for(int i=0;i<kv.length;i+=2)m.put((String)kv[i],kv[i+1]);return m; }
  private static void write(Path path,Object value)throws IOException { Files.write(path,(json(value)+"\n").getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW); }
  private static String json(Object v) {
    if(v==null)return "null";
    if(v instanceof Boolean)return v.toString();
    if(v instanceof Number){require(!(v instanceof Double)||Double.isFinite((Double)v),"Nonfinite JSON");return v.toString();}
    if(v instanceof Map){StringJoiner j=new StringJoiner(",","{","}");for(Object e:((Map<?,?>)v).entrySet()){Map.Entry<?,?> x=(Map.Entry<?,?>)e;j.add(json(x.getKey().toString())+":"+json(x.getValue()));}return j.toString();}
    if(v.getClass().isArray()){StringJoiner j=new StringJoiner(",","[","]");for(int i=0;i<Array.getLength(v);i++)j.add(json(Array.get(v,i)));return j.toString();}
    String s=v.toString();StringBuilder b=new StringBuilder("\"");for(int i=0;i<s.length();i++){char c=s.charAt(i);if(c=='\\'||c=='\"')b.append('\\').append(c);else if(c<32)b.append(String.format(Locale.ROOT,"\\u%04x",(int)c));else b.append(c);}return b.append('"').toString();
  }
}
