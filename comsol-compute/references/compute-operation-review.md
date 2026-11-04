# 计算执行补充审查（2.0.0 candidate03）

共同 [operation_review](operation-review.md) 及其脚本/schema 来自 `handoff-review` 发布副本，保持原样。本侧 `scripts/compute_operation_review.py` 只在共同审查之上补充计算操作的执行条件，不另立 manifest、selection_ref 或目标量语义；运行时只加载本 skill 自身脚本。

运行配置的 `operation_review` 指向本侧补充记录，补充记录的 `binding.public_review` 指向共同记录。两层都为 ready 才具备该范围的准备条件，**ready 不授予运行权限**。run/export 还须核对当前用户授权；本轮修复及测试均不构成未来科研执行授权。

candidate03 使用独立的 `review_revision: candidate03`；公共记录新增规范错误接口并固定公共工具/schema。candidate02 输入接收记录、公共审查和本侧补充审查应从原始输入另存重建，不得在旧文件中补字段、换版本标签或改哈希冒充重新检查。本侧核对输入接收记录的当前公共 schema/core 散列及 candidate03 错误接口。

## 形成顺序

1. 保存原 manifest，创建本次 `input_record.py --manifest ... --out ...` 输入记录；两者均保持不可变。
2. 写好本次运行配置及真实适配脚本，先确定最终文件路径。运行配置可引用尚待生成的审查文件路径，但之后不能为求通过而改写已固定文件。
3. 用共同 `operation_review.py prepare` 创建公共记录；`--runtime-files` 除脚本/class/数据/源解外还列出实际运行配置文件（role 可用 `configuration`）。manifest 中适用的运行依赖由公共工具展开，不能只 pin manifest 本身。
4. 完成下表所列人工/静态审查，另存 assessment JSON；通过本侧 `create` 生成补充记录。若有缺项，状态保持 pending/blocked，不能把它称为可执行运行包。
5. runner 的 prepare/run/export 重新调用本侧验证；输入、范围、目标、位置、数值配置或审查证据改变，旧状态不得复用。配置需要修改时重新建立本次输入链和审查。

纯 Python API：

```python
build_execution_review(public_review_path, manifest_path, input_record_path,
                       operation, scope, target_names, expected_positions,
                       execution_config, assessment, assessment_base=None)

validate_operation_review(review_path, manifest_path, model_path, operation, scope,
                          pins=None, input_record_path=None, target_names=None,
                          expected_positions=None, execution_config=None)
```

`scope` 是共同协议的 ID 数组，例如明确的 `target:<name>`；`target_names` 独立列出目标并与公共记录覆盖一致；`expected_positions` 是**逐目标**的执行位置映射，形如 `{"目标甲":[位置1,位置2],"目标乙":[位置1]}`，键必须恰好覆盖本次目标，每个数组非空且无重复。旧的全局位置数组拒绝使用；目标与位置各自并集完整不证明每个目标结果完整。

补充记录自动保存 `target_position_definitions`，按目标原样复制共同 manifest 的 `time/frequency/parameters/mode` definition，核验时与当前绑定 manifest 逐值比较。内部位置映射须由 `assessment.target_reviews` 的证据明确核对其展开、单位和适用点；工具不解析任意科学范围表达式，也不从历史案例补位置。映射只是共同目标定义的本次执行表示，不是新公共目标语义。runner 必须逐目标核对实际解位置完整性。

`execution_config` **仅**包含 `parameters` 和 `solver_settings` 两个对象，由 runner 传入当前实际值并严格比较类型和值，不把 `false` 当作 `0`。

## assessment 格式

assessment 是计算侧执行审查数据，不是公共 manifest 扩展。必需以下字段；未知项用 pending，不能由工具猜测为 complete。

| 字段 | 内容 |
|---|---|
| `reviewer` | 非空审查者/责任来源说明。 |
| `scope_review` | 对本次操作、范围及其依赖闭包的确认。 |
| `input_inspection` | 本次范围内模型盘点与适用检查的证据，不能用文件散列代替内部检查。 |
| `dependency_inventory` | 已审查当前实际脚本/class/数据/源解依赖声明是否完整；自动散列不能发现未声明依赖。 |
| `target_reviews` | 以本次目标名称为键的对象，必须恰好覆盖 `target_names`；证据核对共同字段与 `expected_positions[name]` 的逐目标位置对应关系。 |
| `physics_scope` | 必须分别含 `confirmed_physical_problem`、`physical_initial_conditions`、`solver_initial_guess`、`physics_activation`、`multistep_transfer`、`continuation` 六项。物理初态与数值初猜分开；研究启停、多步传递和延拓不能改变已确认物理问题。 |
| `solution_source` | resume/export 或使用已有解的 solve 必须有完整源解核对；纯计划 solve 可有理由地不适用。 |

除 reviewer 和两个分组对象外，每个决策都采用 `{status, reason, evidence}`：

- `status` 为 `complete/pending/blocked/not_applicable`；`reason` 非空白。
- `evidence` 为 `{path,sha256}` 数组。complete 必须有实际可核对的证据文件；pending 可留空，不生成虚假证明。
- not_applicable 必须说明理由。范围、输入盘点、依赖盘点和本次目标审查不能整体省略；solve/resume 的 confirmed_physical_problem 也不能不适用。物理初态对某些稳态问题可以不适用，但必须记录依据，不能借此跳过给定瞬态初态。
- CLI 中相对证据路径按 assessment 文件目录解析；API 默认按 manifest 目录解析，或显式传 assessment_base。保存后统一绝对路径与原 SHA-256，不改证据内容。

公共模块负责未解项的范围判定、逐项处置及目标完整性；本侧保留其 public_errors/side_errors/todos，不把 blocking 问题改为忽略。本侧不对全模型物理初态 inventory 再追加一刀切否决，依公共结果和本范围物理初态证据决策；公共合同因不完整结构盘点等原因返回的错误仍须处理，不能借局部范围绕过。公共合法的其他组件未知事项不会被本侧额外提升为本范围阻断。

## CLI

命令只读输入并创建新的 JSON，不运行 COMSOL 或适配器。`--out` 拒绝覆盖。

```powershell
python .\scripts\compute_operation_review.py create --public-review 'D:\任务\public-review.json' --manifest 'D:\任务\model-manifest.json' --input-record 'D:\任务\input-record.json' --operation solve --scope 'target:本次目标名' --targets '本次目标名' --positions 'D:\任务\positions.json' --execution-config 'D:\任务\execution-settings.json' --assessment 'D:\任务\assessment.json' --out 'D:\任务\compute-review.json'
python .\scripts\compute_operation_review.py verify --review 'D:\任务\compute-review.json' --manifest 'D:\任务\model-manifest.json' --model 'D:\任务\input.mph' --input-record 'D:\任务\input-record.json' --operation solve --scope 'target:本次目标名' --targets '本次目标名' --positions 'D:\任务\positions.json' --execution-config 'D:\任务\execution-settings.json'
```

退出 0 仅表示当前记录 ready；pending/blocked 返回 2。读取 JSON 状态与分类，不能用退出码代替授权。

## runner 使用的公开结果

返回 `status/errors/side_errors/todos`，错误对象为 `{code,instance_path,message}`；`errors` **只包含公共错误**，本侧错误不得混入。`public_errors` 仅为旧格式兼容别名，不用于 candidate03 符合性比较。本侧额外错误以 `COMPUTE_` 开头。始终保持 `authorization_granted=false`、`comsol_model_check_performed=false`、`scientific_validity_verified=false`、`resume_reliability=not_assessed`。

- `required_runtime_files`：公共已核验 pins 中实际运行输入的路径、SHA-256、roles。仅 input_manifest/input_model 绑定和 public_contract_implementation/public_contract_schema 工具用途另列，不混入科学运行数据或恢复科学状态。
- `required_review_files`：公共记录、补充记录、输入记录、输入绑定、本侧审查证据及公共两份 Python/两份 schema 的工具 pins。runner 必须固定并重新核对；工具与科学依赖保留分类，不能把 schema/校验代码当源解。
- `allowed_solution_sources`：对 export 从共同目标的 existing 解引用，映射到对应 legacy 的 `id/tag/solution_id/source_model_sha256` 与已固定的来源路径。runner 按每个目标核对实际源文件与解标识，不接受任意被 pin 的 MPH。
- `target_position_definitions`：逐目标共同定义快照，供 bundle 保留来源和核对；不能据此跳过适配器对实际目标位置的观测。

当前 runner 只验证已有解导出；共同协议允许的不依赖解的 export 暂由本侧返回 `COMPUTE_EXPORT_NO_SOLUTION_UNSUPPORTED` 待办。不得为了通过而虚构已有解或数据集。

审查器仍依赖声明与真实人工证据。它不打开 MPH，不自动证明空间位置、材料正确性、旧解有效或恢复连续性。测试使用合成小文件调用真实公共 API；这属于静态/模拟验证，真实 COMSOL 验证本轮全部未执行。

## 日志及私有运行目录的审查绑定

`execution_config` 仍只含 parameters/solver_settings，不扩展共同模型协议。每个日志来源的编码策略、路径预算及任务设置都写入实际run-config/settings；完整文件必须以configuration/runtime角色进入公共审查与runner pins。runner指纹包含完整配置；准备后修改策略或目录设置会使旧包失效，不只重新散列manifest。新增被导入的路径辅助脚本也须列入实际运行依赖。

在scope_review/dependency_inventory的证据中记录日志编码的依据、各来源映射及私有目录范围；未知编码/目录预算保持pending。适配器启动前核对settings与cfg的完整有效日志策略，最终runner用同一策略复查所有声明日志。此处只固定和审核配置，不证明编码选择一定正确或COMSOL路径必定可用。
