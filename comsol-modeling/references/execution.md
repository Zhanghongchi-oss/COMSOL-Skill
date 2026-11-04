# Java 运行与 v2 操作闸门

环境集中在 assets/environment.local.json；文档/API/示例目录由 comsol_root 派生。运行器支持 PowerShell 5.1/7 的参数数组调用，单个无 package 的 Java 源文件。methodexec 对辅助类的可见性不能由编译成功推断；共享导热生成器采用同一顶层类中的静态方法，不生成嵌套类/Sink。它不是任意 Java 的权限沙箱；必须审查所有可达调用和写入目标。2026-11-01 与 2026-11-02 的单域导热验证均按精确源码和输入记录；原嵌套类生成输出在 methodexec 实测失败，单类桥接成功不证明正式生成器已修复。历史授权不继承到本次新操作。

## 计划模式

```powershell
& ./scripts/Invoke-ComsolJava.ps1 -Source ./BuildModel.java -RunDirectory ./build-01 -JobFile ./job.properties -Operation build -Scope all
```

默认仅解析路径、散列源码/job/环境配置/明确输入模型和声明依赖并返回计划；不创建运行目录、不编译、不启动 COMSOL。输出 execution_readiness=not_assessed，input_bindings.side_errors 明列缺失或冲突，不能称可执行包。新运行目录避免旧 class 混入。MPH 不直接作为 batch 输入；入口为审查后的 Java class。

未传 `-ConfigPath` 时，在脚本体内从本 skill 路径解析默认配置，避免 Windows PowerShell 5.1 在参数默认值阶段尚无 `$PSScriptRoot`。显式配置路径仍优先；用 `-Python` 指定本次已核实的解释器，不能假设 PATH 中的 `python` 就是原验证环境。2026-11-03 的搬迁测试已分别验证 PowerShell 5.1/7 的默认与显式配置计划模式，不创建运行目录或启动 COMSOL。

inspect/modify 需要 job.input_model 或显式 `-InputModel`；同时提供时须一致。无 job 的自定义 Java 必须用 `-InputModel` 明确主模型，额外数据/模型/库使用 `-RuntimeInput` 列出并加入审查 pins。这只登记实际输入，不会把这些参数自动注入任意 Java：源码仍须按已审阅方式读取它们。

## 独立操作审查

先用本 skill 的 [operation_review.py](../scripts/operation_review.py)，遵守 [公共操作定义](operation-review.md)：

- 有 manifest：绑定输入 manifest 和模型，并核对该操作范围的未解项、目标量、依赖和检查。
- 仅 MPH：mph_only 审查只可准备 inspect，表示后续授权的只读盘点；不声称已经检查模型。
- 从零建模：new_model_spec 明确尚无模型/manifest，绑定任务定义和运行输入，准备 build；不能伪造模型哈希。

除了 manifest 声明的适用 runtime 文件，把以下实际运行输入列入 runtime_files：Java 源码、job（若有）、环境配置、显式偏好文件及权限审阅记录、实际 comsolcompile.exe/comsolbatch.exe、Invoke-ComsolJava.ps1、modeling_gate.py、operation_review.py、contract_v2.py、model-manifest.schema.json 和 operation-review.schema.json。公共 review 已自动固定最后四份规则文件，重复声明不影响核验。主模型须与 review.model 的路径及哈希一致；额外外部数据、用户库、模型和源解等也必须列入，不能只固定 manifest 或 job 文件本身。未确认依赖完整时保持 pending。新增的 launcher/偏好/权限记录 pins 会使旧运行审查不足；另存重新准备，不补写旧审查或沿用历史 ready。可执行文件哈希不等于已固定整个 COMSOL 安装库；实际用户库、外部数据及额外运行脚本仍须按任务登记。

只有 review 的当前操作/Scope 是 ready 且当前明确授权涵盖本次 COMSOL 动作，才调用：

```powershell
& ./scripts/Invoke-ComsolJava.ps1 -Source ./BuildModel.java -RunDirectory ./build-01 -JobFile ./job.properties -Operation build -Scope all -PreferencesFile ./reviewed-comsol.prefs -PermissionsReviewFile ./permissions-review.md -OperationReview ./operation-review.json -ReviewedSourceSha256 <已审阅源码哈希> -CurrentAuthorization '<本次用户授权的出处和具体范围>' -Execute
```

CurrentAuthorization 仅记录由执行者核实的当前授权，传入文本或 ready 文件都不能自行产生授权。本轮开发/修复授权不能填作未来建模运行授权。入口先调用本地 modeling_gate.py：重新计算 review、核对操作/Scope、所有必需 pins及准备后变化；源码哈希仍须匹配。没有显式范围、授权记录或 review 时在启动前拒绝。

环境配置从同一份字节解析与散列。复制后、编译前再次核验输入；源码和 job 的副本对照准备时固定的哈希，不能只与可能同时变化的原件比较。成功产生的新 class 另记 compiled-pins.json，关联原 review 和源码哈希，不改原 review。batch 前再核验 review、输入、副本和所有 class pins。真实依赖完整性需要代码/模型盘点，工具只能核对已声明文件；不保证任意 Java 的权限隔离。

编译与 batch 分别使用独立的 configuration/workspace/prefs/tmp/recovery 目录，并显式设置 -migrateprefs off。编译使用 -verbose <file>.java；batch 使用 -inputfile <class> -nosave -batchlog <log>。-nosave 仅关闭 launcher 自动保存，不能拦截 Java 的 save/求解调用。-norun 与 Java class 的交互未验证，不作防求解保证。Java 必须显式另存新文件；拒绝覆盖源 MPH。不以进程退出 0 推断检查通过。

运行目录预留后，stage-record.json 记录最后阶段、退出码、错误、输入绑定和日志哈希；失败保留日志并停止，不自动重跑、求解或删除旧节点。预留前的门禁拒绝不创建运行目录，由调用方另存 stdout/stderr。两个 Python 公共模块及 schema 均来自 handoff-review 的发布副本，运行时不依赖另一 skill。

## 只读盘点源码

assets/InspectModel.java 从 UTF-8（支持 BOM）的 job.properties 读取：

```properties
input_model=D:/project/input.mph
audit_output=inventory.tsv
```

此入口采用明确的 UTF-8 `key=value` 子集：允许 BOM、注释和空行；拒绝转义、续行和重复键。路径使用正斜杠，input_model 为绝对路径；这是运行入口的解析约束，不是所有 Java Properties 文件的通用规则。audit_output 必须是新运行目录内尚不存在的 TSV，禁止通过绝对路径、`../` 或可识别的目录链接越界。

源码 loadCopy 后只读遍历并写新 TSV，不保存模型、不构建几何、不配置网格或求解。实际属性、选择空间、材料覆盖等仍需项目 CheckModel；仅完成清单不能填 structure=passed。InspectModel.java 的修复起于 2026-11-01 sources-inventory-v03；当前精确资产另有 2026-11-02 两次各 1694 行、0 读取错误的实测，源码哈希和范围见 [盘点 API 说明](inventory-api.md)。不能将这些历史读取结果套用到新 MPH；本次单类生成修复没有重新执行全面盘点。Python/PowerShell 模拟通过不能提升 API 验证状态。

## 私有运行环境与权限

默认计划不创建任何目录，也不产生或导入宽权限偏好。执行必须提供 `-PreferencesFile` 和 `-PermissionsReviewFile`，两者进入 operation_review 的 runtime pins；权限审阅至少明确：实际读写文件/目录、需要读取的系统属性、依据、不可再收窄的原因，以及运行环境提供的隔离边界。空文件不满足该要求，文件非空和哈希正确也不等于权限已获授权。

每个新 RunDirectory 下分别创建 `_runtime/compile/` 和 `_runtime/batch/`，各自拥有 configuration、workspace、prefs、tmp、recovery。仅向这些新 prefs 目录复制审阅的偏好；不改用户目录、安装目录或全局 INI/prefs。源码、job、偏好副本、主模型与依赖在启动前校验；真实 launcher exe 也进入输入 pins，编译产物 class 另记派生 pins。batch 结束后再次检查原始输入、源码/job 副本和 class，变化记失败，不能继续交付“原输入”的结果。

验证副本为本机文件和 Windows NIO `user.dir` 访问曾显式使用 filepermission=full、propertypermission=on；这只是该次审阅证据，**不随 skill 分发为默认设置**。准备者应先查对应版本的权限能力并按需要收窄；若版本只有粗粒度权限，明确实际扩大范围后另行审阅，不能将“私有 prefs”说成“只能读写运行目录”。当前 runner 只隔离目录与偏好位置，没有 OS 文件访问沙箱、JobObject、CPU/内存硬限制、超时或进程树清理保证。资源限额按任务另定，不继承历史 1 核/2048 MiB/180 秒。局域 IPC 或权限失败必须停止，不自动关安全检查或提权重试。

命令依据：本机 COMSOL 6.3 `comsol_ref_running.38.31.html` 的 Common Options（configuration/data/prefsdir/tmpdir/recoverydir/migrateprefs）及 COMSOL Compile；历史 runtime-05 的配置/workspace/prefs/tmp 参数组合曾运行成功。2026-11-02 当前 runner（SHA-256 d7dd05341c73e8fb631729c902a3bd39fdcb70f1c4a071f1d2111fd0ce38a9ef）已承载单类验证桥接的四阶段真实运行；该证据仅覆盖该小模型与参数组合，不能追认原嵌套类生成器通过。

## 保存与独立重载的验收

runner 只执行已审查 Java，不能通用推断其报告语义；即使退出为 0、有 MPH 或出现完成标记，stage-record 也仅为 `pending_evidence`，从不写 model passed。审阅者须检查详细断言、失败日志、预期输出与哈希、物理约束以及保存后重载证据。不能把退出码或报告总状态替代明细；有矛盾则拒绝。

build/modify 后需独立新建 `inspect` 阶段：绑定刚保存的实际 MPH 及当前哈希、新 job/源码/偏好和对应操作审查；在新进程 loadCopy，只读检查几何、选择、材料、本构/边界及源文件不变，产出另一个检查报告。未执行时 reload 保持 not_run/pending；独立 Check 不把自身输入冒称修改来源。runner 不自动启动第二阶段，ready 不产生授权，保存也不授权后续网格/研究/求解/导出。仅盘点仍不等于物理结构通过。

## 辅助类装载失败的处理

2026-11-02 `live-candidate-validation-20261102/modeling/build-01` 中，编译和 launcher 退出零，但 methodexec 找不到 `BuildSlab$ConductionChecks$Sink`，没有 MPH 或检查报告；runner 的 pending_evidence 正确。build-03 将完整编译 JAR 通过 `-dev` 传入仍失败，因此不把 `-dev` 或临时 JAR 打包当作已验证修复。

正式共享片段现改为宿主顶层类内方法，记录接口由生成器明确绑定；Build/Modify/Check 从同一源生成，不手改生成文件。其他辅助类方案须固定完整依赖闭包并通过真实 methodexec 验证，不能以 Java 编译或 JAR 含类名代替装载验证。现有 runner 的源码、class pins、pending_evidence 与独立重载门槛均保持。

历史单类桥接 244/123/367/123 条断言不代表新正式生成器已执行。2026-11-02 `modeling-single-class-repair-20261102` 的candidate-02另用当前正式生成器和该入口完成同一小案例四阶段，实际源码、模型及独立检查哈希另存，见 [导热读回规则](conduction-readback.md)。runner的pending_evidence门槛未变，正式通过来自原始明细及独立审核。修改报告混合源模型/修改后/重载检查，全部367不能改绑到最终MPH；该输出当前检查为独立123，条数不是通用阈值。未来运行仍须新的适用授权、输入pins、报告和清理约定，不继承此轮资源或权限。
