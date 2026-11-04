# 运行后解状态观察协议（计算侧 2.0.0 candidate03）

本页定义 `run_bundle.py` 检查的运行产物，不修改共同 manifest 协议。它要求独立的解状态观察与读回记录，避免只凭完成标记、退出零或 MPH 文件存在接受计算完成。包装器只校验记录的一致性与文件来源；适配器仍须真正读取状态，不能把计划内容复制成“观察结果”。

## 三类互相核对的产物

1. **完成证据**：配置 `evidence` 指定的 JSON；关联本次身份、操作、位置及全部输出散列。
2. **解状态观察**：`outputs` 中唯一 `role: solver_observation` 的 JSON；按本页格式记录实际状态和解映射。
3. **独立读回记录**：`outputs` 中 `role: solution_readback` 的新文件；保存实际状态查询或已保存解读回的原始值、查询方法及适用限制。观察 JSON 和完成证据不能相互引用充当此原始记录。

三类产物均须在本次唯一运行目录内，启动前不存在，结束后非空且时间戳不早于本次启动；适配器不能从旧目录复制标记充当新鲜状态。读取方法和实际对象/节点应能人工追查。原生日志仍需另查，发现错误时即使其他记录一致也不接受完成证据。

配置示意（位置和名字必须换成本任务定义）：

```json
{
  "schema_version": "2.0.0",
  "execution_kind": "comsol",
  "target_names": ["temperature"],
  "expected_positions": {"temperature": [{"case": "A"}]},
  "outputs": [
    {"path": "solved.mph", "role": "solved_model"},
    {"path": "solver-observation.json", "role": "solver_observation"},
    {"path": "solution-readback.json", "role": "solution_readback"}
  ],
  "evidence": "evidence.json"
}
```

这是字段片段，不是可直接运行的配置或默认科研参数。`execution_kind` 必须显式为 `simulation` 或 `comsol`；两者的观察方法和输出证据级别分开记录。

candidate03 的 `expected_positions` 是逐目标映射，键必须恰好为 `target_names`，每个值为非空、无重复的位置数组。位置含义仍由共同 `target_outputs` 的 time/frequency/parameters/mode 定义；补充审查保留这些定义的原样快照 `target_position_definitions`，并以逐目标审查证据解释本次规范化的对应关系，不自动解析任意范围表达式。旧 candidate02 的全局位置数组不能可靠分配给各目标，必须另建配置和审查，不能静默转换或覆盖旧证据。

## 观察 JSON

```json
{
  "schema_version": "2.0.0",
  "run_id": "本次运行ID",
  "fingerprint": "本次运行指纹",
  "operation": "solve",
  "input_model_sha256": "原输入MPH的实际SHA256",
  "solver_status": "completed",
  "completed_positions": {"temperature": [{"case": "A"}]},
  "observation": {
    "method": "saved_solution_readback",
    "detail": "写明实际查询的模型、研究/解对象、查询方法和读回范围",
    "evidence": [{"path": "solution-readback.json", "sha256": "该读回文件的实际SHA256"}]
  },
  "solutions": [{
    "target_names": ["temperature"],
    "solution_tag": "实际解tag",
    "dataset_tag": null,
    "dataset_unavailable_reason": "本次只求解并保存，尚未创建结果数据集",
    "solution_count": 1,
    "available_solution_count": 1,
    "positions": [{"case": "A"}],
    "source": {"path": "solved.mph", "sha256": "实际输出MPH的SHA256"}
  }]
}
```

字段约束：

| 字段 | 必需语义 |
|---|---|
| `schema_version` | 当前计算侧观察协议 `2.0.0`，不自动解释旧记录。 |
| `run_id`、`fingerprint`、`operation` | 与本次 bundle 和完成证据一致。 |
| `input_model_sha256` | 与本次输入 pins 中的模型散列相同，不用新输出散列替换。 |
| `solver_status` | solve/resume 必须为 `completed`；export 必须为 `existing_solution_available`。缺解、部分完成、失败均不能写成这些状态。 |
| `completed_positions` | 逐目标映射，与 `expected_positions` 及完成证据的键、每个位置数组的顺序、JSON 类型和值相同；不能用 false/true 替代 0/1。 |
| `observation.method` | simulation 仅接受 `synthetic_mock`；comsol 接受 `solver_api`、`saved_solution_readback` 或 `gui_inspection`。方法名称不代替真实证据。 |
| `observation.detail` | 非空，说明如何获得实际状态；不能只写“完成”或“文件存在”。 |
| `observation.evidence` | 非空文件引用数组；每项为本次声明的 `solution_readback` 输出，路径相对本次目录，散列/新鲜性须匹配。 |
| `solutions` | 非空实际解映射。完全相同的解/数据集/目标集合/位置集合条目不得重复；允许同一解/数据集按不同目标或位置分条记录。必须分别覆盖每个目标请求的全部位置。 |
| `target_names` | 每条映射必需，solve/resume/export 均不能省略；非空、无重复、属于本次请求目标。该条的位置列表同时适用于其中每个目标。 |
| `solution_tag` | 非空实际解 tag。 |
| `dataset_tag` | export 必须有实际结果数据集 tag；solve/resume 若只求解保存而未创建结果数据集，可为 null，但必须给 `dataset_unavailable_reason`。不得为了通过校验虚构数据集。 |
| `solution_count` | 本条映射实际选中的解位置数量，正整数，等于本条 `positions` 长度；不得用一个解冒充全部位置。 |
| `available_solution_count` | 从该来源观察到的可用解位置总数，至少为选中数。允许模型另有本次未选的解；记录其维度/外内解解释于读回文件。 |
| `positions` | 本条实际选中位置，非空、无重复，必须属于本条每个 target_name 的请求集合；通过同条来源检查后才按目标累加覆盖，不能借另一目标的位置补足。 |
| `source` | 实际含解 MPH 的路径和 SHA256。solve/resume 必须是本次声明的 `solved_model` 输出；export 必须是已固定的当前输入模型或公共声明角色为 source_model/source_solution 的 MPH，并且与该目标的已审查解来源匹配。普通 data 角色的 MPH 即使被 pin 也不能冒充该目标源解。 |

配置和统计方法可能需要多个解、多个组件或不同参数层级；适配器必须在原始读回记录里保存足以解释该映射的对象标识和索引，不通过更改计划位置来掩盖缺失解。

例如 A 和 B 各请求 `[0, 1]`，只有 `A@0` 与 `B@1` 时，两目标均缺位置，不能因为目标并集和位置并集各自齐全就接受完成。若本次共同定义和补充审查明确 A 仅需 `[0]`、B 仅需 `[1]`，则这两条映射可以完整覆盖请求。所有操作均按同一规则核对；export 还必须在同一映射条目内同时满足该目标的来源、解标识、数据集和位置关系。

日志中的 `Errors: 1`、`Exceptions: 2`、`Failures: 1` 等非零计数同样属于错误线索；只有整行明确为零的计数可排除，不能以英文复数形式绕过检查。检查点参数、数值设置和状态也采用类型严格的 JSON 比较，避免 Python 将布尔值误认为数值。

## 仅提取已有解

export 的输出可为数据/图片，不要求另存求解 MPH；仍必须观察已有解。每条 `solutions` 额外包含：

```json
{
  "solution_id": "共同manifest中既有解的solution_id",
  "target_names": ["本次目标量名称"],
  "selection_evidence": [{"path": "solution-readback.json", "sha256": "实际SHA256"}]
}
```

全部条目合起来必须映射本次 `target_names`，不能漏目标或引用未请求目标。本侧操作审查从公共已验证的目标 existing 解声明生成 `allowed_solution_sources`，保留 target_name、legacy_id、solution_id、solution_tag、源模型散列及允许的源文件。运行后按每个目标核对观察的 solution_id、solution_tag、源路径和 SHA256；即使另一个 MPH 已在 pins 中、甚至角色也是 source_solution，只要不是该目标的已审查源解，仍拒绝完成证据。

`selection_evidence` 是声明的新鲜读回产物，需记录目标量与实际数据集、实际实体/全局选择的对应关系；目标选择的正式定义仍来自共同 manifest 的 `selection_ref`，本页不另设选择语义。包装器不解析任意读回文件来独立证明空间位置，真实选择正确性仍由适配器检查和数值审核确认。当前本侧执行器只支持需要既有解的 export；共同合同合法但不依赖解的输出，由本侧明确列为尚未支持，不伪造解来源。

缺少已有解、数据集或目标选择证据即拒绝完成证据，不把 export 自动转为 solve。

## 证据级别与输出来源记录

simulation 通过时摘要为 `evidence_level: simulated_execution`，只说明模拟执行的记录核对通过。comsol 通过时为 `runtime_observation`，是本次适配器的运行观察证据，不自动等于“该适配器/研究类型已通过真实 COMSOL 验证”。真实验证需另有明确授权及独立验收记录；本轮移植未新增实机验证；历史小例实测范围见 capabilities.md。

`basic_checks`、`numerical_convergence`、`experimental_validity`、`resume_reliability` 均保持 `not_assessed`，不由记录匹配自动提升。算法可信性、空间/时间精度和恢复接缝连续性须另行检查。

执行后另写 `output-record.json`，关联原输入模型、manifest、输入记录和操作审查的原散列，以及本次输出和当前运行证据。`inherited_checks` 默认空；原 manifest 保持不变，不能把旧结构检查换绑到新 MPH 散列。允许继承时应另行记录原检查来源、依据、适用范围和限制，而非冒称重新检查通过。

## 身份与持久化边界

`required_solution.id` 引用逻辑 `legacy.id`；它不等于实际 `solution_id`，后者也不必等于 solver tag。通过唯一已审核记录解析，分别核对，不猜 sol1 或取首项。生成父模型是来源谱系，实际载解 MPH 才是 export 的解来源；两者可能不同。继承检查保持原始模型对象与范围。

读回中建立的内存 dataset 只证明当前读回会话的映射，不代表已保存于源 MPH。仅提取不能保存覆盖源模型，结束后核对源哈希。空 getMesh 返回保留原值；只有明确支持的适配器才可用独立的 Xmesh 对应证明，且绑定载解文件、解、run 和原始网格证据，不能通用宣称高阶或曲面网格等价。
