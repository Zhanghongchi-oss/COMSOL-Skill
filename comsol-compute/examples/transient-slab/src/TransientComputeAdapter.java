import com.comsol.model.*;
import com.comsol.model.util.*;
import java.io.*;
import java.lang.reflect.Array;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Scoped COMSOL 6.3 transient sine-diffusion and saved-field restart fixture.
 * No geometry/material/physics/BC/physical-initial-state setter is present.
 * All case-specific tags, parameter expectations and result expressions come
 * from a case-spec-derived UTF-8 Properties file prepared by the Python driver.
 * Live validation uses a fresh per-phase cwd/job.properties, without getenv.
 */
public class TransientComputeAdapter {
  private static final String[] PARAMS = {"L", "H", "thickness", "k_slab", "rho_slab", "Cp_slab", "T_base", "T_amp"};
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
      require(m.component("comp1").physics("ht").feature("init1").getString("Tinit").equals("T_base+T_amp*sin(pi*x/L)"),"Physical initial condition changed");
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
      throw new IllegalStateException("Transient adapter failed; no completion evidence may be accepted", e);
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


  private static double[] times(Model m,String sol) {
    require(Arrays.asList(m.sol().tags()).contains(sol) && !m.sol(sol).isEmpty(),"Missing saved time solution; no solve fallback");
    require("Time".equals(m.sol(sol).getType()),"Expected time solution");
    double[] ts=m.sol(sol).getPVals(); int[] size=m.sol(sol).getSize();
    require(size.length==2 && size[0]>0 && size[1]==ts.length,"Time/solution shape mismatch");
    for(int i=0;i<ts.length;i++) {
      require(Double.isFinite(ts[i]) && (i==0 || ts[i]>ts[i-1]),"Invalid actual times");
      require(m.sol(sol).isRealU(i+1),"Complex transient field");
      double[] u=m.sol(sol).getU(i+1); require(u.length==size[0],"Incomplete actual vector");
      for(double v:u)require(Double.isFinite(v),"Nonfinite actual field");
    }
    return ts;
  }
  private static void solve(Model m,Path input,String inputHash)throws Exception {
    String c=required("component"),g=required("geometry"),mesh=required("mesh_tag"),study=required("study_tag");
    boolean resume=required("operation").equals("resume");
    require(!Arrays.asList(m.study().tags()).contains(study),"Study collision");
    double[] initial=null;String sourceSol=null;double[] sourceTimes=null;Map<String,Object> sourceLayout=null;
    if(resume) {
      sourceSol=required("source_solution_tag"); sourceTimes=times(m,sourceSol);
      require(sourceTimes[sourceTimes.length-1]==Double.parseDouble(required("start_time")),"Checkpoint end time mismatch");
      initial=m.sol(sourceSol).getU(sourceTimes.length);
      sourceLayout=dofLayout(m,sourceSol);
      require(Arrays.asList(m.component(c).mesh().tags()).contains(mesh),"Resume requires existing saved mesh");
    } else {
      require(m.sol().tags().length==0 && m.component(c).mesh().tags().length==0,"Fresh solve requires unsolved model");
      MeshSequence ms=m.component(c).mesh().create(mesh,g);
      ms.feature("size").set("custom","on");ms.feature("size").set("hmax",required("mesh_hmax"));ms.feature("size").set("hmin",required("mesh_hmin"));
      ms.create("tri","FreeTri");ms.feature("tri").selection().named(required("selection.domain"));ms.run();
    }
    m.study().create(study);m.study(study).create("time","Transient");
    m.study(study).feature("time").set("mesh",new String[]{g,mesh});
    m.study(study).feature("time").set("tlist",required("tlist"));
    m.study(study).createAutoSequences("sol");
    String sol=null;int owned=0;
    for(String s:m.sol().tags())if(study.equals(m.sol(s).study())){sol=s;owned++;}
    require(owned==1,"Ambiguous generated solver");
    String variable=null,time=null;
    for(String f:m.sol(sol).feature().tags()) {
      if(m.sol(sol).feature(f).getType().equals("Variables")){require(variable==null,"Duplicate variable feature");variable=f;}
      if(m.sol(sol).feature(f).getType().equals("Time")){require(time==null,"Duplicate time feature");time=f;}
    }
    require(time!=null && variable!=null,"Missing generated time/variables node");
    m.sol(sol).feature(time).set("rtol",required("solver_rtol"));
    if(resume) {
      m.sol(sol).feature(variable).set("control","user");
      // In 6.3 build 290 the generated Variables node need not expose this
      // documented property. Do not read/set a missing property or invent a default.
      if(m.sol(sol).feature(variable).hasProperty("useinitsol"))m.sol(sol).feature(variable).set("useinitsol","on");
      m.sol(sol).feature(variable).set("initmethod","sol");
      m.sol(sol).feature(variable).set("initsol",sourceSol);
      m.sol(sol).feature(variable).set("solnum","last");
      require(m.sol(sol).feature(variable).getString("initsol").equals(sourceSol),"Initial solution setter mismatch");
    }
    m.sol(sol).runAll();double[] ts=times(m,sol);
    double seam=0;
    if(resume){double[] u=m.sol(sol).getU(1);require(initial.length==u.length,"Resume mesh/DOF mismatch");require(json(sourceLayout).equals(json(dofLayout(m,sol))),"Source and resumed DOF ordering differs; do not compare raw vector indices");for(int i=0;i<u.length;i++)seam=Math.max(seam,Math.abs(u[i]-initial[i]));}
    Path output=newPath("output_mph");m.save(output.toString());
    Map<String,Object> out=identity("solve_saved_pending_independent_readback");
    out.put("operation",required("operation"));out.put("source_mph",input.toString());out.put("source_sha256",inputHash);
    out.put("output_mph",output.toString());out.put("output_sha256",sha(output));out.put("solution_tag",sol);out.put("study_tag",study);
    out.put("times",ts);out.put("source_solution_tag",sourceSol);out.put("source_times",sourceTimes);out.put("raw_max_solution_vector_difference",resume?seam:null);
    out.put("raw_vector_difference_units","Mixed or unknown DOF units; not a temperature error. Identify names/mapping before assigning units or thresholds.");out.put("source_dof_layout",sourceLayout);
    out.put("initialization",resume?initialization(m,sol,variable):map("method","physical_init"));
    out.put("time_solver_rtol",m.sol(sol).feature(time).getString("rtol"));out.put("time_solver_tlist",m.sol(sol).feature(time).getString("tlist"));
    out.put("physical_initial_expression",m.component(c).physics("ht").feature("init1").getString("Tinit"));
    out.put("continuation_kind","Saved field restart on unchanged mesh; integrator history is reinitialized, not crash recovery");
    write(newPath("solve_metadata"),out);
  }
  private static void readback(Model m,Path input,String inputHash,String mode)throws Exception {
    String sol=required("solution_tag"),c=required("component"),ds=required("dataset_tag");double[] ts=times(m,sol);
    MeshSequence ms=m.component(c).mesh(required("mesh_tag"));Map<String,Object> binding=verifySolutionMesh(m,sol,ms,inputHash);
    require(!Arrays.asList(m.result().dataset().tags()).contains(ds),"Dataset collision");
    m.result().dataset().create(ds,"Solution");m.result().dataset(ds).set("solution",sol);m.result().dataset(ds).set("comp",c);m.result().dataset(ds).set("geom",required("geometry"));
    double L=m.param().evaluate("L"),H=m.param().evaluate("H");double[][] coords=new double[2][45];int n=0;
    for(int j=0;j<5;j++)for(int i=0;i<9;i++){coords[0][n]=L*i/8;coords[1][n++]=H*j/4;}
    double[][] values=new double[ts.length][];double[][] vectors=new double[ts.length][];
    for(int t=0;t<ts.length;t++){values[t]=sampleAt(m,ds,"t"+t,coords,t+1);vectors[t]=m.sol(sol).getU(t+1);}
    write(newPath("mesh_vertices"),map("coordinate_rows",ms.getVertex(),"columns_are_vertices",true,"coordinate_unit","m"));
    Map<String,Object> types=new LinkedHashMap<String,Object>();for(String type:ms.getTypes())types.put(type,map("connectivity_rows",ms.getElem(type),"entity_ids",ms.getElemEntity(type)));
    write(newPath("mesh_elements"),map("types",types,"indices_as_returned",true,"index_base",0));
    Map<String,Object> out=identity("independent_saved_solution_readback");out.put("mode",mode);out.put("source_mph",input.toString());out.put("source_sha256",inputHash);
    out.put("solution_tag",sol);out.put("dataset_tag",ds);out.put("dataset_persisted",false);out.put("times",ts);out.put("solution_count",ts.length);out.put("dofs",vectors[0].length);
    int[] solnums=new int[ts.length];for(int i=0;i<ts.length;i++)solnums[i]=i+1;
    out.put("inner_solnums",solnums);out.put("temperature_expression","T");out.put("temperature_unit","K");out.put("coordinate_unit","m");out.put("dataset_solution_tag",m.result().dataset(ds).getString("solution"));
    out.put("sample_coordinates",coords);out.put("temperature_K",values);out.put("solution_vectors",vectors);out.put("dof_layout",dofLayout(m,sol));out.put("solution_vector_units","Mixed: use DOF names, not a blanket kelvin unit");out.put("solution_mesh_binding",binding);out.put("solution_mesh_tag",ms.tag());out.put("mesh_triangles",ms.getNumElem("tri"));
    out.put("physical_initial_expression",m.component(c).physics("ht").feature("init1").getString("Tinit"));
    for(String f:m.sol(sol).feature().tags()) {
      if(m.sol(sol).feature(f).getType().equals("Variables"))out.put("saved_initialization",initialization(m,sol,f));
      if(m.sol(sol).feature(f).getType().equals("Time")){out.put("time_solver_rtol",m.sol(sol).feature(f).getString("rtol"));out.put("time_solver_tlist",m.sol(sol).feature(f).getString("tlist"));}
    }
    out.put("mesh_vertices_sha256",sha(existing("mesh_vertices")));out.put("mesh_elements_sha256",sha(existing("mesh_elements")));
    write(newPath("raw_readback"),out);
  }
  private static double[] sampleAt(Model m,String ds,String tag,double[][] coords,int solnum) {
    m.result().numerical().create(tag,"Interp");m.result().numerical(tag).set("data",ds);m.result().numerical(tag).selection().named(required("selection.domain"));
    m.result().numerical(tag).set("expr",new String[]{"T"});m.result().numerical(tag).set("unit","K");m.result().numerical(tag).set("solnum",new int[]{solnum});
    m.result().numerical(tag).set("coorderr","on");m.result().numerical(tag).set("matherr","on");m.result().numerical(tag).set("ext",0.0);m.result().numerical(tag).set("recover","off");m.result().numerical(tag).setInterpolationCoordinates(coords);
    double[][][] v=m.result().numerical(tag).getData();require(v.length==1 && v[0].length==1 && v[0][0].length==45,"Sample shape mismatch");for(double x:v[0][0])require(Double.isFinite(x),"Nonfinite sample");return v[0][0];
  }
  private static Map<String,Object> initialization(Model m,String sol,String feature) {
    boolean available=m.sol(sol).feature(feature).hasProperty("useinitsol");
    return map("method",m.sol(sol).feature(feature).getString("initmethod"),"source",m.sol(sol).feature(feature).getString("initsol"),"solnum",m.sol(sol).feature(feature).getString("solnum"),
      "useinitsol",available?m.sol(sol).feature(feature).getString("useinitsol"):null,"useinitsol_property_available",available,"available_properties",m.sol(sol).feature(feature).properties(),"control",m.sol(sol).feature(feature).getString("control"));
  }
  private static Map<String,Object> dofLayout(Model m,String sol) {
    XmeshInfo xm=m.sol(sol).xmeshInfo();XmeshInfoDofs dofs=xm.dofs();
    return map("field_names",xm.fieldNames(),"field_ndofs",xm.fieldNDofs(),"names",dofs.dofNames(),"name_indices",dofs.nameInds(),"solution_vector_indices",dofs.solVectorInds(),"nodes",dofs.nodes());
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
    String studyMesh=m.study(study).feature("time").mesh(geom);
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
    return map("adapter","TransientComputeAdapter/candidate-port-20261102", "status",status,
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
