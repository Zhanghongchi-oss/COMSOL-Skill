# 二维稳态矩形导热适配器

仅在任务符合示例 case-spec 的物理、目标和支持范围时使用 `../examples/steady-slab/`。源码独立随技能发布，运行不调用建模 skill 或历史 validation 的私有脚本。正式身份语义见 [公共解身份定义](solution-identity.md)。其他案例先查对应版本文档并实现、审阅适配器；不要直接套用该例的单 study/单 solver、solution_id 等于 tag 等限制。

## 入口与准备

- `scripts/prepare_case.py --case CASE_SPEC --out NEW_DIRECTORY`：只生成 pending 计划，不启动任何 COMSOL 程序。随包 `case-spec.json` 是共同案例的逐字节发布副本，case-spec 是科学定义来源，数值起始网格/容差是明确的案例选择，既不是测量也不是误差验收门槛。
- prepare 的可选 `--manifest --source --legacy-id` 只解析唯一身份到 pending 审查记录，不能替代公共/计算审查；该例当前只支持输入文件本身载解且 actual solution_id 等于 solver tag，其他合法公共映射明确拒绝，不能据此判公共合同错误。
- `src/SlabComputeAdapter.java`：由 stage_driver 的独立阶段调用；每次编译/执行仍须对应当前授权。指定源码已在 [本次实测](live-validation-20261102.md) 编译执行。solve 保存到新 MPH；readback 重新载入输出；export 仅读取已有解，缺解即退出，不调用求解或保存源 MPH。
- `scripts/stage_driver.py --bundle BUNDLE --settings SETTINGS --runner RUN_BUNDLE`：由通用 runner 在对应操作当前已获授权后调用；要求 pins、实际配置及两层审查匹配，不是绕过审查的快捷入口。
- `scripts/compare_mesh.py`：仅接受 COMSOL/runtime_observation 且完成证据通过的两次输出，核对声明的 readback/网格文件、角色、哈希与身份，再比较真实单元/坐标/连接及目标量差异。模拟 accepted 不能获得真实测量结论。

目录必须新建；失败后另建运行。资源、日志编码、输入模型/manifest/审查、编译产物及实际解身份缺失时保持 pending。生成产物依当前任务要求保留或清理；使用前仍须核对当前文件和来源，不能从历史报告散列虚构文件存在或通过检查。

## 六项修复的范围

| 修复 | 必须保留的事实和停止条件 |
|---|---|
| 求解器发现 | 保留 filtered 查询为空的原始观察；枚举实际 tags 并检查所属 study，不能猜 sol1 或任取首项。该例 solve 要求无既有解；export 必须解析已审核既有解。多个匹配或所属研究不符即停止。 |
| 解与网格 | getMesh 原始空值保留。用实际 Xmesh 局部角点、坐标、连接的多重集证明与序列网格的对应，并独立 Python 复算。节点/单元重排可等价，重复单元计数不能丢。证明绑定载解文件、解、run、case 和原始文件散列。仅支持明确案例布局；角点对应不证明任意高阶场插值、曲边几何或三维网格等价。 |
| 边界热量 | 共同审核的是此例单邻接域外边界的域侧迹 `mean(d(T,x))`；通过右边界积分、正 x 方向及厚度一次计入保持原科学目标。内部双侧边界、不同物理量或方向不能无条件使用 mean。 |
| 空日志 | 声明、存在且新鲜的日志可以为空；缺失、过期、报错日志仍失败。科学输出和完成证据必须非空，文件角色不能绕过检查。 |
| 网格质量 | Java 显式选择域维度并读回维度；Python 要求域三角形统计的维度与实体范围正确。历史顶层边界统计不能改标签当成域质量；历史数据只可从有证据的 domain 局部统计另行复算。 |
| 仅提取身份 | 从唯一审核的 legacy 记录分别获得逻辑ID、实际 solution_id、solver tag 和载解文件哈希，并核对实际读回。该专用适配器若不能支持这些标识的某种映射应拒绝，而不是改公共定义。缺解不转求解，export 后核对源文件不变。 |

## 分阶段与证据

每阶段使用独立的 job.properties、工作目录、首选项副本、临时/恢复/配置目录，并记录配置及输入哈希。固定 job.properties 已在历史及本次小例实测；不能描述为 getenv 已被实测证实失败，原入口并未执行验证。

资源守卫仅控制自身子进程树。CPU、内存和超时预算由当前任务明确配置，历史单核、2 GiB、180 秒不自动采用。失败不扩大权限，不更改全局首选项或安全策略，不更改几何、材料、物理接口、边界及物理初态。

历史粗网格最初因空 stderr 被拒绝，补充检查独立另存；原失败报告不改写。后续重新解释同样需新报告，绑定检查器版本与原证据。dataset `cdset` 是读回会话内存对象，不能说已持久化在输入 MPH。生成父模型与当前载解文件分别记录，继承检查保持原对象及范围。

## 实测范围与后续任务

较早的2026-11-02导热轮覆盖求解、独立重载、域统计维度、实际 Xmesh 对应、仅提取身份及缺解拒绝，见 [历史版本与边界](live-validation-20261102.md)。当前v3轮已用最终runner重新执行，并补做长度修改后的166单元模型，见 [当前正式候选验证](live-validation-v3-20261102.md)。86/332 个三角形的真实变化与约定局部尺度支持基础模型加密；两张网格解析吻合不证明通用收敛或收敛阶。新增电热耦合与其限制在独立专题中说明，瞬态、一般非线性反馈及可靠续算仍未验证。

后续任务仍按当前授权、实际源码和新输入重新审查。确认离散阶次、曲面近似、采样范围、案例误差门槛与预算；缺输入、身份或证据不一致、域/边界混淆、无解、非有限输出、日志错误、超预算均停止，物理问题返回建模侧。成功的小例不替代这些检查。

## 日志和私有路径

2026-11-02运行e17fd8c750294ec7ab8433b391af65cc的错误、退出码和evidence_rejected保持历史原样。新候选改为逐日志来源严格扫描并聚合诊断。`runtime_path_policy`要求明确路径预算及其审查依据；采用bundle内部短目录，不转移到全局TEMP、不扩大resource_guard范围。启动前对实际映射和预留native后缀做UTF-16长度审查，并在私有目录进行可创建/读回/删除的小文件探针；收据仅说明Python路径检查，不证明COMSOL一定能创建其内部恢复文件。超预算/探针失败停止并保留报告。

短路径后续已经实际运行成功，但这不是对旧261单元失败路径的单变量控制实验；根因界限见 [历史实测专题](live-validation-20261102.md)。清理只针对当前任务明确映射的生成文件并另留回执；不恢复已删除历史模型来补验。


新准备入口为solve/export各生成独立的 `*.solve.settings.json` / `*.export.settings.json`，对应run-config精确引用；旧 `base-coarse.json` 等只保留pending数值计划，不能直接用于新阶段执行。逐源映射覆盖wrapper stdout/stderr以及每阶段native stdout/stderr/batch、guard stdout/stderr；所有codec空值必须先审定。旧单编码执行配置仍可由通用runner识别，但专用stage缺少明确 `runtime_path_policy` 或新增证据声明时会拒绝，不静默升级旧包。

路径policy字段为 `layout=bundle_private_compact_v1`、`max_path_utf16_units`、`reserved_native_suffix_utf16_units` 和 `review_basis`，两个长度预算均不默认填数值，review_basis须写明选择依据。对应目录为 `rt/{s,r,e}/{j,t,r,p,c,w}`，保持在当前bundle范围；实际root由用户当前授权任务选择，超预算需重新准备较短的私有bundle根。资源守卫root未改变，阶段串行且保持本次CPU/内存/时间预算。`*-path-preflight.json`、`*-diagnostics.json`、资源与进程记录和两份job.properties进入输出散列；探针成功删除后才记录deleted，清理失败保留实际路径及错误，不隐瞒。
