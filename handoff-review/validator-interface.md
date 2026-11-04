# 公共校验接口 · 2.0.0 candidate04

维护源为 handoff-review。双方独立携带相同公共代码、schema 和规范，不导入另一 skill 的私有模块。公共测试仅通过 CLI 调用两侧包装器，不规定私有函数名。

## 固定 CLI

```powershell
python -X utf8 -B <validator.py> --manifest <model-manifest.json> --out <new-receipt.json>
```

- 建模默认入口：`comsol-modeling/scripts/validate_manifest.py`。
- 计算默认入口：`comsol-compute/scripts/input_record.py`，由计算维护方适配本接口。
- `--out` 必须另存；已有文件不得覆盖。输入 manifest 不改写。输出是 UTF-8 JSON 单个对象。合法和合同错误输入均输出结构化结果；测试优先读取新建 receipt，未生成时解析 stdout；无法解析属于 CLI 接口失败，不能当作无公共错误。
- 错误对象使用 `code`、`instance_path`、`message`。manifest 的 `instance_path` 是稳定的声明位置：根为 `$`，字段为 `$.field`，数组为 `$.items[0]`；不是文件系统路径。schema 缺失字段定位所属对象，精确语义检查可定位所需字段；涉及文件的错误定位声明该文件的字段。文件系统路径可放提示文字，不参与符合性比较。
- 公共错误 `errors`、侧别错误 `side_errors`、待办 `todos` 分开。兼容 `public_errors` 可以保留 `{code,path,message}`，但新测试不使用它。三类数组均必需；无此类内容才为空。

```json
{
  "errors": [{"code": "FILE_HASH", "instance_path": "$.model", "message": "Model SHA-256 does not match"}],
  "side_errors": [],
  "todos": [],
  "comsol_model_check_performed": false,
  "authorization_granted": false
}
```

消息仅作说明，示例不代表任何真实检查。符合性比较是排序去重后的 `(code, instance_path)` 集合；退出码、message、侧别错误和待办可以不同。公共 errors 为空不等于执行就绪，需读取 operation_review.status 并另核对授权。

## 公共错误分类

| 类别 | code |
|---|---|
| 输入/模式 | JSON_INVALID, SCHEMA_VERSION, SCHEMA_STRUCTURE |
| 唯一标识 | DUPLICATE_ID |
| 选择/几何/配对 | SELECTION_REFERENCE, SELECTION_DIMENSION, GEOMETRY_REFERENCE, PAIR_REFERENCE |
| 物理关联 | SELECTION_REFERENCE（包括材料 required_by 和物理初态的悬空物理接口引用） |
| 目标定义 | EXPRESSION_BLANK, TARGET_STATE, SOLUTION_REFERENCE, COORDINATE_REFERENCE |
| 文件/依赖 | FILE_MISSING, FILE_HASH, DEPENDENCY_REQUIRED |
| 检查/证据 | CHECK_EVIDENCE, CHECK_MODEL_BINDING, STRUCTURE_DETAILS, STRUCTURE_CONTRADICTION, MODELING_EXECUTION |
| 未知/范围 | INVENTORY_STATE, UNRESOLVED_REFERENCE, UNRESOLVED_SCOPE, SCOPE_REFERENCE |
| 来源/旧节点 | LEGACY_BINDING, LINEAGE_BINDING, SOURCE_OVERWRITE |

同一输入可能同时出现 schema 与精确语义错误；不能仅选一个隐藏其他分类。精确分类以公共实现及正负例锁定，双方不得在本地修改公共映射。`LINEAGE_PENDING` 为待办，不能伪装成已核实来源。

operation_review 另使用同版 operation_review.py 的 `OP_*` 规则；按实际 errors/side_errors/todos 分类，不把 OP 前缀统称公共错误。既有 OP_SOLUTION_PIN_MISSING 位于 side_errors；它不属于 manifest 符合性 errors 比较入口。建模运行器自身 `MODELING_*` 属于 side_errors。公共核心不决定授权。

## 符合性测试

```powershell
python -X utf8 -B handoff-review/tests/test_public_contract.py --modeling-validator comsol-modeling/scripts/validate_manifest.py --compute-validator comsol-compute/scripts/input_record.py --out validation/public-v2-candidate03-joint-01
python -X utf8 -B handoff-review/tests/test_public_contract.py --modeling-only --modeling-validator comsol-modeling/scripts/validate_manifest.py --out validation/modeling-v2-candidate03/public-01
```

输出目录必须全新。两侧用同一份运行时生成的模拟 fixture，所有 `.mph` 字节明确写明不是 COMSOL 模型；模拟检查文件不冒充真实证据。fixture 中文件路径相对其 manifest；生成时重新计算哈希。任何一侧尚未同步时只能报告“已发布，待计算侧联调”，不得用建模单侧结果宣布协作通过。

candidate04 增加父模型/载解文件、逻辑/实际解 ID、清理后文件缺失正反例。既有 CLI、公共分类和 schema 不变。还可运行：

```powershell
python -X utf8 -B handoff-review/tests/test_solution_roles.py --modeling-reviewer comsol-modeling/scripts/operation_review.py --compute-reviewer comsol-compute/scripts/operation_review.py --runtime-module comsol-compute/scripts/run_bundle.py --out validation/offline-revision-20261102/solution-roles-01
```

前两项通过显式两侧公共 CLI 检查正确载解 ready（非授权）及父模型误绑 blocked，比较规范化公共错误（这两个操作例的 errors 均为空），并分别断言既有 side_errors 中的 OP_SOLUTION_PIN_MISSING。非空公共分类的比较另由实际ID误用为逻辑引用、继承错绑、清理后缺文件等 manifest 用例覆盖。可选 runtime-module 仅是测试适配器，读取指定实现的现有观察门禁，测试实际 solution_id/tag 错绑；其拒绝属于侧别运行行为，不加入公共 errors 分类，不成为任一 skill 的运行依赖。不将辅助模拟称作 COMSOL 验证。
