# operation_review v2.0.0（公共候选接口）

本工具只准备和核对独立记录，不执行任何命令、不启动 COMSOL、不判断用户授权。`ready` 仅表示已声明的本次范围具备准备条件；真实运行仍须另行核对当前授权。

公共 Python API（两个 skill 各携带本模块及 `contract_v2.py` 的发布副本）：

```python
build_review(manifest_path, operation, scope, target_names=None, runtime_files=None)
build_mph_review(model_path, scope=None, runtime_files=None)
build_source_review(spec_path, scope=None, runtime_files=None)
verify_review(review_path, manifest_path=None, operation=None, scope=None)
```

- `operation`：`prepare/inspect/build/modify/solve/resume/export`。
- `scope`：本次范围的显式非空 ID 数组，使用 `contract_v2.known_scope_ids` 的共同标识（例如 `component:c1`、`physics:c1/ht`、`target:temperature`）。`all` 和 `model` 明确表示全模型，空数组无效；`all` 不与其他标识混用。组件范围包含其子节点，目标范围包含选择所属组件的物理依赖。全局目标没有更窄依赖闭包时保守按全模型处理。
- `target_names`：省略时从 scope 推导；显式给定必须恰好覆盖 scope 内的目标，不能用空数组或子集隐藏待定目标。只处理部分目标时，应明确使用 `scope=["target:<name>"]`。目标表达式、单位、坐标、统计、时间/频率/参数/模态位置及所需解分别核验。
- `runtime_files`：额外运行输入的 `{path, role}` 数组，路径相对 manifest（或 new_model_spec/MPH 所在目录）。脚本、class、外部数据、源解等必须声明。manifest 中 `category=runtime` 且 `applies_to` 包含本操作的全部存在文件自动收集，包括可选但已选用的文件；`prepare` 收集全部 runtime 声明。来源/audit 文件不自动冒充运行输入；必需文件是否齐全仍按共同合同检查。
- `build_review` 返回记录，调用方使用独占新文件保存；本模块 CLI 的 `--out` 拒绝覆盖。
- `verify_review` 实际验证 [operation-review.schema.json](operation-review.schema.json)，再从原输入重建审查，检查绑定、scope、operation、公共合同、运行 pins 的完整性及准备后变更。返回 `{status, errors, public_errors, side_errors, todos, authorization_granted: false}`。规范公共错误为 `errors:[{code,instance_path,message}]`，`public_errors` 仅兼容旧调用；candidate03 的已保存审查必须含 errors，旧审查另建。它不会把 `ready` 转为执行。CLI 只有 ready 返回 0，其余返回 2；代码也必须读取状态，不能把退出 0 当成授权。

CLI：

```powershell
python operation_review.py prepare --manifest model-manifest.json --operation export --scope all --runtime-files runtime-inputs.json --out operation-review.json
python operation_review.py verify --review operation-review.json --manifest model-manifest.json --operation export --scope all
```

独立记录绑定输入 manifest 和模型的 SHA256，逐项记录未解决问题处理、目标定义完整性和依赖核验。`pending` 允许交付未完成准备方案；`blocked` 表示声明或对应范围存在阻断。两者均不可称为可执行运行包。所有未解项都保留处理记录；范围不相交也写明理由。`solve/resume/export` 按本操作 impacts 的 effect 判定；只读 inspect 不修改或计算物理，因此允许带未解项盘点，但不把这些项消除。

`export` 只接受明确 existing 的解，或明确不依赖解且确实可提取的目标；planned 解会阻断，仅提取绝不自动转为求解。整体 not_applicable 的目标不可导出。existing 解还须有当前输入模型适用声明、valid 及证据、已固定的来源文件；除当前输入模型外，来源文件须以 runtime 的 source_model/source_solution 角色声明，普通 data 不代替源解。请求参数/时间/频率/模态与声明不同，或请求已定义但相应源位置缺失/不适用，均保持待核验；不自动推断任意范围表达式的包含关系。工具只确认声明和来源一致，不独立证明旧解有效。

## 无 manifest 的两个显式入口

- `input_kind=mph_only`：model 绑定真实文件，manifest/model_spec 为 null；`input_status=pending_model_inspection`，只允许 `operation=inspect, scope=["all"]`。可在已固定只读盘点源码后给该**盘点操作** ready，但模型内部仍未检查。不能把这个 review 用于 solve/export/modify。
- `input_kind=new_model`：model/manifest 均为 null，绑定独立 `model_spec` 文件；只允许 build。没有虚构 MPH。spec 必需 `schema_version:"2.0.0", record_type:"new_model_spec", reason, scope_ids, definition_status, unresolved, runtime_files`。`definition_status=complete` 表示任务输入声明完整，不能以默认空 unresolved 掩盖未盘点；未知项使用共同 unresolved 全字段（id/question/owner/evidence/affected_scope/impacts），其作用范围必须存在于 spec.scope_ids。非 complete 或相关未解项保持 pending。至少固定一个 java_source/class/runner/script/adapter 入口；只有文档没有实际入口仍为 pending。

新模型 spec 尚无实际模型依赖图：组件及其限定子节点视为相关；只有明确分属不同已声明组件，才可据此判为不相交。未限定组件的目标/几何等无法证明独立时保守保持 pending，不能用不同字符串把未解项排除。

```powershell
python operation_review.py prepare --mph original.mph --operation inspect --scope all --runtime-files runtime-inputs.json --out inspection-review.json
python operation_review.py prepare --new-model-spec model-spec.json --operation build --scope all --out build-review.json
```

运行器必须同时核对当前实际 Source/脚本/class/配置文件在 review pins 中（路径及 SHA256 都匹配），并额外核对本次授权。不能拿一个只固定了其他脚本的 ready review 执行当前代码。自动检查只能覆盖已声明运行依赖；人工/获授权的模型盘点负责证明声明完整。

candidate03 自动将当前实际读取的 contract_v2.py、operation_review.py、model-manifest.schema.json 和 operation-review.schema.json 加入 pins，verify 重新生成并比对；这不替代运行器对自身脚本、job、配置、输入模型等实际输入的固定。规则文件变更也使旧审查失效，需另建。scope 沿目标的 existing 解 ID 展开，即使该解 component=null；组件/目标范围保守包含全局参数，不把这些已声明阻断项判成无关。

输入 manifest 保持不可变。旧检查和旧解的模型绑定不改写；若未来输出文件不同，应另建输出记录关联输入与输出，并另记继承依据、适用范围及限制，不把旧检查换成输出哈希冒充重检。来源一致性不证明旧解物理或数值有效。

本模块和其 schema 只在 handoff-review 维护；两侧独立携带发布副本，运行时不从另一个 skill 或维护目录导入。`new_model_spec` 是执行前建模输入清单，不是已经建模完成的 manifest。

本次新增测试属于隔离的辅助模拟执行，文件字节明确不是 COMSOL 模型或真实检查证据。真实 COMSOL 验证全部未执行；这些测试也不构成未来运行授权。
