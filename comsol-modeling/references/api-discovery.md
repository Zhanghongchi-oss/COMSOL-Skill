# 按问题查证 COMSOL Java API

用于未知接口、修改盘点、编写 Java 和结构审计。以下是本机 **6.3 文档静态查证**，不是运行验证。实际建模时以集中环境配置中的路径和实际运行版本为准。

## 定位与证据

本次只读资料根目录：

- `DOC = <COMSOL_ROOT>\doc\help\wtpwebapps\ROOT\doc`
- `API = DOC\com.comsol.help.comsol\api\com\comsol\model`
- `APPS = <COMSOL_ROOT>\applications`
- Windows launcher 文件版本只读取得 `6,3,0,290`；它不是一次成功启动或许可验证。

先把问题映射到物理接口和所需特征，再限目录检索；不要遍历整个历史库。优先顺序：本机对应版本帮助 → 本机官方示例及其说明 → 有证据的已验证代码。资料不足才查 COMSOL 官方网站，并记录其版本、与本机的差异、仍未确认的行为。

建议每个关键调用留一条证据记录：`接口/特征目的 → Java 类型/属性/枚举/表达式 → 版本 → 本地文档相对路径或官方链接/导出源码行号 → 静态查证/已执行 → 限制`。

```powershell
# $cfg 由当前环境配置读取；以下只示范小范围查找。
$docRoot = Join-Path $cfg.comsol_root 'doc\help\wtpwebapps\ROOT\doc'
$apiDir = Join-Path $docRoot 'com.comsol.help.comsol\api\com\comsol\model'
rg -n 'getAllowedPropertyValues|properties|getValueType' (Join-Path $apiDir 'PropFeature.html')
rg -l --glob '*.html' 'The Heat Transfer in Solids Interface' (Join-Path $docRoot 'com.comsol.help.heat')
```

JavaDoc 通常确认方法签名，不保证列全物理特征的类型及属性。UI 标签、接口变量前缀、Java `feature type` 是不同概念；不能把 `ht`、`solid`、`tds` 当成已确认的创建类型。必要时在获得运行授权后，用匹配版本的 Desktop 建立最小特征并导出 Java，审查其中建模段，删除计算段后才复用。不得靠反复猜属性试错，也不得把导出文件中的求解历史直接执行。

## 已查证的 API 入口

表中路径均相对 `API`；读取完整方法说明、继承关系及返回类型后再组合代码。示例里的 tag 均需由当前任务确定。

| 目的 | 本机签名/调用形态 | 证据文件及限制 |
|---|---|---|
| 安全加载副本 | `ModelUtil.loadCopy(String tag, String filename)` | `util/ModelUtil.html#loadCopy(java.lang.String,java.lang.String)`：保存时必须提供新文件名；tag 冲突会移除已有同名模型，选唯一 tag。 |
| 保存、重新加载 | `model.save(String filename)`；`ModelUtil.load(String tag, String filename)` | `Model.html`、`util/ModelUtil.html`。另存路径必须与来源不同；保存后用新的模型 tag 重新加载输出，审计重新加载对象。 |
| 版本 | `ModelUtil.getComsolVersion()`；`model.getComsolVersion()` | 前者是当前 COMSOL 版本；后者是模型上次保存版本，未保存时才是当前版本。二者分开记录。 |
| 枚举模型树 | `model.component().tags()`；各列表的 `tags()`；`component.physics()`、`func()`、`pair()`、`coordSystem()`、`multiphysics()` | `Model.html`、`ModelNode.html`、`ModelEntityList.html`；全局对象还见 `AbstractModel.html`。递归盘点子 `feature()`，不要只看顶层。 |
| 参数 | `model.param().varnames()`、`.get(name)`、`.evaluateUnit(expr)`；`.group().tags()` | `ExpressionBase.html`、`ParamBase.html`、`ModelParam.html`。参数组读取使用 ExpressionBase，单位由所属 ParamBase 求值（不是强制转换参数组）；保留原表达式和参数组；仅评价不依赖解的表达式。单位未知与无量纲不能混为一谈。 |
| 函数及依赖 | 全局/组件 `func().tags()`；`FunctionFeature.functionNames()`、`feature()` | `AbstractModel.html`、`ModelNode.html`、`FunctionFeature.html`。检查函数属性中的外部表、路径、插值范围和单位；不能假定一切依赖都内嵌在 MPH。 |
| 通用属性读取 | `properties()`、`hasProperty(name)`、`getValueType(name)`、对应 `getString/getStringArray/getStringMatrix/getDouble/...` | `PropFeature.html`、`ParameterEntity.html`。按返回类型读取；不能把所有属性强行读成字符串。 |
| 枚举值 | `getAllowedPropertyValues(String name)` | 上述两页：仅有限字符串集合返回数组，否则返回 `null`；`null` 不是属性不存在，也不是允许任意值。 |
| 活跃性及物理特征 | `isActive()`；物理及子特征 `getType()`、`feature()`、`selection()` | `ModelEntity.html`、`physics/Physics.html`、`physics/PhysicsFeature.html`。节点存在/active 不能证明最终控制该实体；需按接口查覆盖优先级及本构选择。 |
| 材料 | `material(tag).selection()`、`.propertyGroup().tags()`；属性组 `.properties()`、`.getValueType()`、`.getStringArray()`、`.input()` | `Material.html`、`MaterialModel.html`（继承 `ParameterEntity`）。检查物理节点选用的材料来源/用户定义开关及实际属性组；不能只检查材料节点名。 |
| 选择 | `.selection().named(selTag)`；选择 `.dim()`、`.entities()`/`.entities(int dim)`、`.named()` | `AbstractSelection.html`、`Selection.html`、`LocalSelection.html`。isGeom 表示整个几何，不表示所有实体选择；用 isGlobal 区分全局、按实际 dim 读取 entities(dim)，未知维度保留 not_read。名称关联仍须检查几何归属、维度、数量、空间范围；ID 只能是本次构建的审计快照。 |
| 配对 | `pair(tag).type()`、`.source()`、`.destination()`、`.manualSelection()`、`.srcFrame()`、`.dstFrame()` | `Pair.html`。两侧均需核验非空、维度、位置、方向/坐标框架和物理条件引用；边界数量相同不是映射正确的证明。 |
| 构建几何 | `geom(tag).run()`、`.run(String featureTag)` | `GeomSequence.html`。属于本 skill；与 mesh/study/sol 的运行严格区分。局部 run 不能声称最终几何已完整构建。 |
| 几何状态 | `geom.feature(tag).status()`、`.hasError()`、`.hasWarning()`、`.message()`、`.errors()`、`.warnings()`；`geom.problems()` | `GeomMeshFeature.html`、`GeomSequence.html`。读取每个相关特征和问题节点；警告需解释，不静默当作通过。不是通用的物理完整性检查器。 |
| 几何计数及位置 | `geom.getSDim()`、`.getNEntities()`、`.getBoundingBox()`；`component.measure().selection()` 后 `.getBoundingBox()`、`.getVolume()`、`.getArea()`、`.getLength()` | `GeomInfo.html`、`ModelNode.html`、`GeomMeasureBase.html`、`GeomMeasureFinal.html`。选择要按实体维度限定；记录几何单位。`geom.measureFinal()` 在 6.3 已弃用，应优先组件 `measure()`。 |

不要将以上列表当成已编译的通用审计程序；组合时仍须检查对象的静态类型、继承和当前模型结构。没有发现一个能代替接口检查的“模型全部正确”API。

可复用的只读盘点入口见 [InspectModel.java](../assets/InspectModel.java)。它从当前任务工作目录的 UTF-8 `job.properties` 读取 `input_model` 与 `audit_output`，用 `loadCopy` 读取模型，向一个新的 TSV 写参数/函数/组件/材料/物理属性、选择和配对快照、几何消息及旧计算节点标签；不构建或保存模型。job 采用 UTF-8 `key=value` 子集，路径使用正斜杠 `/`，拒绝转义、续行和重复键；与实际解析器及 execution.md 一致。把 `input_model` 指向刚保存的输出 MPH 可用于独立重载检查。它以 `overall_model_validation=incomplete` 明确区分“可加载/已盘点”和物理正确；项目的空间位置、材料覆盖、生效本构和边界条件仍需任务专用 `CheckModel.java`。属性读取异常写入 TSV 并以非零状态退出；未知值类型标为 `not_read`，不得据此声称属性已核实。参数组/单位归属、选择语义和盘点范围的修复见 [盘点 API 说明](inventory-api.md)：其中明确记录当前 InspectModel 精确源码在 2026-11-02 的两次真实读取；读取成功不代表物理断言通过，也不能追授其他生成器或不同源码的验证状态。

## 生效设置与材料覆盖

针对每个物理接口分别定义所需区域和属性。核查：接口参与域 → 活跃本构节点及覆盖优先级 → 实际材料/用户定义来源 → 所需属性及其单位、各向异性坐标系、状态依赖 → 边界条件/默认条件覆盖 → 初值 → 耦合引用。保存属性读回值作为证据；无法无求解确认的项保持 `not_run`/未解决。

例如热问题依据采用的导热/储热模型查热参数；固体力学依据弹性等本构查力学属性；稀物质传递依据扩散/对流/迁移/反应选项查系数与来源。方程接口可以完全使用用户系数；不能要求所有域都具有相同材料属性，也不能要求每个接口必须创建材料节点。

## 非电磁资料入口

以下文件已定位并读取接口说明；示例 MPH 未加载、未修改、未运行，不代表对应模块许可可用。这里只提供查证路径，不预置物理场模板。

| 问题 | 本机接口说明（相对 DOC） | 官方案例及说明 |
|---|---|---|
| 固体导热 | `com.comsol.help.heat/heat_ug_interfaces.08.31.html`，默认 Solid、Thermal Insulation、Initial Values；按问题决定导热/对流/辐射及参数来源 | `APPS/Heat_Transfer_Module/Tutorials,_Conduction/heat_conduction_in_slab.mph`；`DOC/com.comsol.help.models.heat.heat_conduction_in_slab/heat_conduction_in_slab.html` |
| 结构力学 | `com.comsol.help.sme/sme_ug_solid.07.002.html`，维度假设、默认线弹性/自由边界和功能许可差异 | `APPS/COMSOL_Multiphysics/Structural_Mechanics/feeder_clamp.mph`；`DOC/com.comsol.help.models.mph.feeder_clamp/feeder_clamp.html` |
| 稀物质传递、反应 | `com.comsol.help.chem/chem_ug_chemsptrans.08.007.html`，扩散、对流、迁移、参与域、浓度变量；`chem_ug_chemsptrans.08.003.html` 比较稀/浓物质传递的适用性 | 多组分反应问题可参考 `APPS/Chemical_Reaction_Engineering_Module/Tutorials/multicomponent_tubular_reactor.mph` 和同目录参数 TXT；说明 `DOC/com.comsol.help.models.chem.multicomponent_tubular_reactor/multicomponent_tubular_reactor.html`。该案例不是所有稀溶液问题的直接模板。 |

对于其他领域，先定位相应 `com.comsol.help.<module>` 的接口章节及官方案例，确认适用方程、维度和许可，再确定类型与属性。`applications` 中本次未发现可直接复用的 Java 源码；现存 MPH、说明和数据文件不是无需运行即可取得全部 Java 属性的证据。

## Windows 启动、编译与许可边界

证据：`DOC/com.comsol.help.comsol/comsol_ref_running.38.31.html`（COMSOL Commands on Windows）、`comsol_api_intro.46.07.html`（编译 Java）、`comsol_api_intro.46.11.html`（以 batch 运行编译模型）。

- launcher 位于安装根目录下 `bin/win64`；路径应从配置派生，不硬编码在通用源码中。
- `comsolcompile <file>.java` 编译 Java；文档列出的 Java 附加参数为 `-classpathadd`、`-jdkroot`、`-verbose`。不要把应用打包专用的 `-outputdir` 套到 Java 编译。
- `comsolbatch -inputfile <file>.class` 执行编译模型。当前 skill 的运行入口必须是审查过的 Java class，不直接把用户 MPH 作为 batch 输入；Java 自行加载并另存到明确的新路径。
- batch 的 `-nosave` 禁用 launcher 的结果保存，可避免额外自动保存；Java 中显式 `save` 仍应逐一审查。文档警告：未给 `-outputfile` 时 batch 默认覆盖输入，不能对 MPH 随意套用示例命令。
- `-norun` 文档定义为不计算模型；**未查证其与 Java class 入口执行的组合语义**，不得称其为防止 Java 内部求解的安全隔离。脚本内部/被调用方法/launcher 选项都要审计，不依赖单个开关，也不依赖搜索 `.run()`。
- 不传 `-study`、`-job`、`-methodcall`、`-continue`、`-recover`、清网格/清解或计算参数扫选项。保留旧计算树时只读盘点，标记影响，不为“检查”调用其方法。
- PowerShell 先记录 `$PSVersionTable.PSVersion`；5.1 不使用 `&&` 等新版语法，用 `& $exe @argArray` 和 `$LASTEXITCODE` 检查失败；引用路径、参数数据与命令分离，不拼接 `Invoke-Expression`。Java 编译产物放任务输出目录，不写只读历史或安装目录。
- 实际 class 入口、`-nosave`、编译与另存/重载行为尚待明确授权后的集成验证；不在本次技能建设中运行 launcher（包括以启动确认许可）。

许可 API 证据均在 `API/util/ModelUtil.html`：

- `hasProduct(String... product)`、`hasProductForFile(String file)` 只检查 `licenseinfo.ini` 的许可信息，不 checkout，不能保证当时有席位。
- `checkoutLicense(String... product)`、`checkoutLicenseForFile(String file)` 才尝试占用所需许可；产品标识必须查证，不能用目录名推导。
- 文档/模块目录存在、静态编译成功、许可信息包含产品、实际 checkout 成功是四件不同的事。分别记录；本次没有执行任何许可 API。
