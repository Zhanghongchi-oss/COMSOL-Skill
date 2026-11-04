# COMSOL 共同交接协议 2.0.0 · candidate04

维护入口仅为 `handoff-review`。`model-manifest.schema.json` 和 `contract_v2.py` 发布时复制到两侧各自的 references/scripts；两个 skill 可独立运行，不导入另一侧私有实现。v1 原件保持不变，迁移必须显式另存并记录原始 manifest 的路径和哈希，未知和旧证据不得升级为通过。

## 接口与错误分类

发布 CLI、结果和错误分类见 [validator-interface.md](validator-interface.md)。公共结果为 `errors: [{code, instance_path, message}]`，侧别错误为 `side_errors`，待办为 `todos`；符合性比较使用 `(code, instance_path)`，不比较提示文字或退出码。`public_errors` 是 candidate01/02 的兼容别名，不是新比较入口。文件合同通过不证明模型、空间位置、可执行性或授权。

同一 schema_version 的候选修订必须用发布文件清单及 SHA-256 区分；candidate03 的 operation_review 新增必需 errors，旧审查应从原输入另建，不得静默改写。版本相同不代表不同快照可混用。迁移规则见 [migration.md](migration.md)。

## 精确形状（以 schema 为机器准绳）

- 顶层保留 `schema_version/producer/model/source_model/comsol/components/selections/pairs/parameters/materials/dependencies/target_outputs/assumptions/checks/legacy/unresolved`，新增必需 `inventory/coordinate_systems/physical_initial_conditions`，可选 `lineage/inherited_checks/extensions`。
- `file={path,sha256}`，相对路径以 manifest 目录为基准。所有证据是 file 数组。`check={status,model_sha256,evidence,notes}`，status 为 `passed/failed/not_run/blocked/not_applicable`。当前检查通过必须绑定当前模型；旧检查只能放 inherited_checks 保留原绑定。
- `definition={status,value,reason,unresolved_ids}`：status 为 `complete/pending/not_applicable`；complete 的 value 为非空白字符串；pending/not_applicable 的 value 为 null 并说明原因；pending 的 unresolved_ids 非空且可解析。不用字符串 `unknown` 冒充完整字段。
- `inventory` 对以下每组记录 `{status,reason,evidence,unresolved_ids}`：`components,selections,pairs,parameters,materials,dependencies,target_outputs,assumptions,coordinate_systems,physical_initial_conditions,legacy_meshes,legacy_studies,legacy_solutions`。status=`complete/partial/not_inspected`；complete 对应数组（可空，表示已确认无内容），partial 对应至少一条已知内容，not_inspected 对应 null；后两者须关联 unresolved。组件自身另有 `physics_inventory`，规则相同；其 `physics` 可 null。几何 tag 在 `components[].geometries` 登记。
- `unresolved[]={id,question,owner,evidence,affected_scope,impacts}`。owner=`modeling/compute/user/shared`；affected_scope 为非空字符串数组；impacts 对 `solve/resume/export` 各给 `{effect,reason}`，effect=`blocks/none/unknown/not_applicable`，全部必须说明理由。
- `affected_scope`、继承检查的 `applicable_scope` 与 operation_review.scope 使用公共 `known_scope_ids(data)`：`all`、`model`、`inventory:<组名>`、`component:<tag>`、`geometry:<组件>/<tag>`、`physics:<组件>/<tag>`、`selection:<组件>/<tag>`、`pair:<组件>/<tag>`、`material:<组件>/<tag>`、`coordinate_system:<组件>/<tag>`、`initial_condition:<id>`、`target:<name>`、`dependency:<id>`、`parameter:<scope>/<name>`、`legacy_mesh:<id>`、`legacy_study:<id>`、`legacy_solution:<id>`。具体 ID 必须登记存在；未知 scope 为公共错误，不能因未匹配而当作无影响。
- pending 的 unresolved_id 还须对应字段作用域：目标量对应 `target:name` 或其已知组件；物理/材料/初态对应自身节点或所属组件；inventory 对应 `inventory:group`。`all/model` 可以显式覆盖。拿无关组件/目标的问题 ID 凑数是 `UNRESOLVED_SCOPE`。operation_review 可使用公共 `expand_scope/scope_overlap` 的保守组件依赖闭包；该闭包不宣称已解析真实模型的变量依赖，也不能用未命中的未知范围证明无影响。
- `dependencies[]={id,path,sha256,category,role,required,status,applies_to,notes}`；category=`runtime/source/audit`；status=`present/missing/unknown`；applies_to 是 `build/modify/inspect/solve/resume/export` 的数组。runtime 对受影响操作至少列一项，声明的全部适用 runtime 文件必须进入 operation_review pins；role 非空字符串（如 data/source_model/source_solution/java_source/class/runner/check_record）。仅 source/runtime 类且明确 role 为 source_model/source_solution 的记录可作为 legacy 的额外模型来源绑定；普通材料 CSV、说明等 source 文件不可冒充模型。文件存在或哈希正确不证明依赖盘点完整，也不证明标为 source_model 的字节确实为可加载 MPH。

## 统一 selection_ref

各 `components[].physics[].selection_ref`、`materials[].selection_ref`、`physical_initial_conditions[].selection_ref`、`target_outputs[].selection_ref`，以及配对的 `source_selection_ref/destination_selection_ref` 使用同一个定义；下列之外的字段不允许混入：

| kind | 必需字段 |
|---|---|
| named | `kind,component,selection`；必须存在于该组件登记的 selections |
| all | `kind,component,geometry,entity_dimension`；明确范围，不由字符串 all 推断 |
| inline | `kind,component,geometry,entity_dimension,rule,scope,verification`；rule/scope 为非空白生成规则/作用范围，verification 为 check；它不是命名节点 |
| global | `kind,quantity_scope`；quantity_scope 明确全局或非实体意义 |
| pending | `kind,reason,unresolved_ids`；必须有对应未解决项 |

登记选择形状为 `{component,geometry,tag,purpose,entity_dimension,entity_count,spatial_verification}`。named 的维度和几何从该登记项解析。几何必须属于组件、维度不得越界；全局量不登记为伪实体选择。配对还记录 `entity_dimension`，两侧仅允许 named/all/inline，须同组件、同声明实体维度并存在于已登记几何。静态一致性不证明空间重合/方向/映射。

物理接口 `{tag,interface_type,selection_ref,material_requirements,evidence}`，tag 在组件内唯一。材料维持属性/来源字段但作用域改为 selection_ref，required_by 仍是 `组件/物理tag`，须实际存在。坐标系登记 `{component,tag,definition,evidence}`；目标 coordinate_system 完整值可为明确 `global` 或已登记 `组件/tag`，不是任意未核实节点。

## 完整目标量与所需解

每项 `{name,status,reason,expression,unit,selection_ref,coordinate_system,statistic,time,frequency,parameters,mode,required_solution}`。name 全局唯一；status 为 `complete/pending/not_applicable`。除 selection_ref、required_solution 外，各项为 definition。expression 完整值不得空白；任何字段 pending 则整体不能 complete。pending 整体必须有原因；not_applicable 所有定义必须不适用，选择采用 global 并说明意义。

`required_solution` 是专用判别联合，不能从普通字符串猜已有解：

- `{status:"complete",kind:"existing",id,reason,unresolved_ids:[]}`：id 引用 `legacy.solutions[].id`；仅证明引用存在，是否可用于操作由 validity/范围/证据及 operation_review 决定。
- `{status:"complete",kind:"planned",id,reason,unresolved_ids:[]}`：id 为计划中的解请求标识，不表示已存在；仅提取时不能自动转为求解。
- `{status:"pending",kind:"pending",reason,unresolved_ids:[...]}`。
- `{status:"not_applicable",kind:"none",reason,unresolved_ids:[]}`：该目标不依赖解，必须解释。

单位、坐标系、统计方法及位置不能从历史案例自动补齐。统计 definition 应解释权重、时间窗、复数/峰值约定等本目标所需语义。不再使用私有 `extensions.compute_output_definitions`。

## 旧数据、来源与初态

`legacy.meshes/studies/solutions` 项为 `{id,component,tag,solution_id,validity,applies_to,reason,evidence}`；validity=`valid/invalid/unknown`。applies_to 必需 `{model_sha256,source_model_sha256,parameters,time}`，可另有 `frequency/mode`；所有位置/范围均为 definition。valid 须两个真实散列、已记录范围全部非待定及证据；solution 还须非空 solution_id。缺省 frequency/mode 不表示该位置已覆盖：若提取目标在该维度 complete，而旧解未记录可比适用范围，operation_review 必须 pending，不能从参数文本或历史经验推断。校验器只核对声明/来源文件，不证明旧解物理有效。

`physical_initial_conditions` 项 `{id,component,physics,selection_ref,definition,evidence}`；这是建模物理定义，与计算侧的 solver initial guess 分开。研究启停、多步初始化和延拓必须符合确认的物理问题，不得以研究配置名义改题。

可选 `lineage={input_manifest,input_model,relation,notes}` 保存输入来源，relation=`modified/computed/inspected/migrated`。可选 `inherited_checks` 项 `{name,original_check,original_model,applicable_scope,basis,limitations,evidence}`；original_check 的 model_sha256 只能绑定 original_model，不能改成输出模型散列冒充重检。输入 manifest 不变，输出另建记录。

## 操作衔接与证据

只有 MPH 时只散列，返回 pending_model_inspection，之后获授权才盘点内部。没有另一 skill 不妨碍准备方案。执行前另建 operation_review，绑定输入 model/manifest 哈希、操作及 scope、逐项 unresolved 处置、目标完整性和运行依赖 pins；ready/pending/blocked 与授权独立。prepare 可以未完成；run/export 需要相应范围 ready 和另外的当前授权。运行前复核模型、manifest 以及它引用的全部适用 runtime 文件，并检查准备后的变化。

证据等级区分文档查证、静态检查、模拟执行、独立行为测试、真实 COMSOL 验证。每份证据按其实际执行范围记录；本次修订仅离线验证，不把历史实测升级为当前候选实测。预写回答只是示例，关键词检查只是文档回归。

## candidate04：生成父模型、载解文件与解身份

此修订不改变 schema_version、schema 字段或既有拒绝规则。具体生成顺序与正反例见 [解身份与证据生成](solution-identity.md)。

`source_model` / `lineage.input_model` 是生成父模型；`legacy.*[].applies_to.source_model_sha256` 是实际承载所声明旧网格、研究或解的 MPH。两者可以不同。`applies_to.model_sha256` 是本条有效性适用的当前模型。载解文件必须为本操作输入 MPH 或明确声明并固定的相应 runtime 源模型/源解；不能为让门禁通过把无解父模型伪装为载解依赖。

`target.required_solution.kind=existing` 时，`id` 引用 `legacy.solutions[].id`（逻辑登记 ID）；planned 的 id 仍只是未来解请求，不要求伪造旧解；`legacy.solutions[].solution_id` 是实际解身份，`tag` 是实际 solver sequence tag。三者分别读写，不能因某案例字符串相同而合并。dataset tag 在独立运行/读回证据中记录，注明内存或已保存；仅内存创建的 dataset 不得宣称在 MPH 内持久存在。共同 manifest 无 dataset 专用字段，不另造私有替代语义。

`inherited_checks` 保留原对象、原模型散列、原证据、适用范围及限制。逐项审核变化影响；求解后新增 study/solution 的模型不得继承“无 study/无 solution”断言。保留原历史断言不等于将它列为输出模型适用检查。静态校验只能核对结构/绑定，不理解任意检查名的科学含义，须有明确的继承审查依据。

科学目标（被积量、方向、选择、单位、统计与解位置）和实际 API 实现分别记录。导热验证中 `mean(d(T,x))` 只在已核验单邻接域外边界上等同于域导数迹；内部多域边界可能平均不同侧值，须重新定义及审核，不能自动替换。API 实现依据以 audit/source 证据关联；不修改原目标来迁就接口失败。

清理记录与历史验收并存。删除 MPH 后保留原哈希和观察时点，不改旧 passed，但当前文件校验必须报告缺失；历史验证不能用于生成新的 ready 或本次授权。准备、建模执行、solve、resume、仅 export 分别核对操作与当前授权；任何历史批准不自动授权新操作。

## 路径、作用范围与准备状态

manifest 的全部 file.path（包括证据、来源、依赖及 inherited_checks 内的路径）均以该 manifest 的父目录为基准。读取 lineage.input_manifest 后，其内部 model.path 以源 manifest 的父目录为基准；禁止用当前工作目录误解。相同 SHA-256 的归档副本可有不同路径，但各声明文件均须存在且哈希吻合。

operation_review 的生成器把输入、runtime_files 和 pins 解析为绝对路径；额外 runtime_files 在生成时相对 manifest、MPH 或 model_spec 的父目录解析。审查记录不能通过搬动目录悄悄指向另一文件；移动可移植交付包后应从包内相对路径 manifest 另建审查。CLI --manifest/--out 等命令行相对路径按调用工作目录解析。fixtures 的原始声明只使用相对路径，运行时在独立目录生成。

范围必须包含显式依赖：目标引用 existing 解时包含对应 legacy_solution，无论其 component 是否为 null；没有逐消费者依赖声明的全局参数保守纳入组件/目标范围。闭包只处理已声明的依赖，不解析任意表达式，也不证明空间或真实物理关系。未知事项不得靠字符串不相等自动忽略。

lineage 的 input_manifest 与 input_model 必须指向同一来源模型的字节；独立文件哈希各自正确仍不足。2.0.0 来源核对其 model 绑定；1.0.0 只在 relation=migrated 时提取可核实的原模型绑定，不解释其余旧字段。无法提取时保留 LINEAGE_PENDING，计算操作保持 pending；明确矛盾则 LINEAGE_BINDING。旧证据仍保留 original_model/original_check，继承不等于当前模型重检。

operation_review 的完整机器结构在 [operation-review.schema.json](operation-review.schema.json)，调用细节在 [operation-review.md](operation-review.md)。记录包含 input_kind、输入 model/manifest/model_spec 的哈希、operation、scope、target_names、runtime_files、pins、unresolved_decisions、target_reviews、dependency_verification、errors/side_errors/todos、status 及明确为 false 的授权与实机核验标志。

| 状态/操作 | 含义与门槛 |
|---|---|
| ready | 本次声明范围满足准备条件；不是授权，不证明模型正确或数值有效 |
| pending | 资料、盘点、目标或适用范围尚待确认；可交付方案，不能称可执行包 |
| blocked | 合同错误、输入变化、必需依赖缺失或相关明确阻断；不能执行 |
| prepare | 可产出 pending/blocked 方案；不启动计算，不自动提升状态 |
| inspect/build/modify | 必须匹配实际操作与范围、实际源码/job/config/模型及依赖 pins；执行另核对当前授权 |
| solve（运行） | 同范围 ready、依赖重新核验、当前授权；物理问题不可为收敛擅改 |
| resume（续算） | solve 门槛之外，明确源解、节点和参数/时间适用范围；物理初态与初始猜测分开 |
| export（仅提取） | 对应目标及其位置/所需已有解明确、来源和范围可用；缺少解不得自动求解 |

依赖分为 runtime（运行实际输入）、source（来源）、audit（审计/交付）。实际使用的 source/audit 文件需同时作为运行输入固定，分类名不能豁免 pins。除 manifest 声明的适用 runtime 文件，运行器及实际读取的公共代码、两份 schema、配置、job、源码/class、外部数据、源解均须固定；pin manifest 不会自动固定所引用文件。准备后及复制后应核验，不把哈希一致当授权，也不宣称能隔离任意 Java。

输出目标的预期采样位置必须逐目标核对。多个目标和多个位置各自的并集完整，不能证明每个目标的结果完整。该规则来自共同 target_outputs 的 time/frequency/parameters/mode 定义；执行方案若使用内部规范化表示，必须可追溯回每个目标，不形成计算侧独有语义。
