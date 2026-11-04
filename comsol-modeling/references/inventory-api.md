# 只读盘点：API 修复与解释边界

使用 [InspectModel.java](../assets/InspectModel.java) 时读取本页。此入口仅 loadCopy 和读取，不构建、保存、配置网格/研究/求解器或求值解。job 使用 UTF-8 key=value 子集、正斜杠路径；读取失败保留 `.read_error`，不支持的属性类型保留 `not_read`。

## 参数、变量与选择

- 参数声明集合使用 `ExpressionBase`：`ModelParamGroup` 继承它而不是 `ParamBase`。表达式从组读，单位通过所属 `ParamBase` 的 `evaluateUnit(name)` 读；不能强制将组转换成 ParamBase。当前模型参数组的所属对象是 `model.param()`。
- 全局及组件变量使用 `ExprList` / `Expr` 读取选择与 `varnames()/get(name)`。变量不能冒充参数；上下文单位保留 `not_read: variable_unit_requires_context_review`，不靠求解或缺省材料猜单位。
- `Selection.isGeom()` 表示**整个几何**，不是“属于几何的实体选择”。它为 false 的命名边界/域选择仍可有效。只有 `isGlobal()` 为 true 才标记全局不适用；非全局选择按 `dim()` 调用 `entities(dim)`。维度未指定时记 not_read，不改写为 global。
- 实体 ID/数量是该文件的读回快照，不是稳定编号，也不证明位置、预期集合或几何修改后的关联正确。空间与成员断言另作语义检查。

## 盘点覆盖与缺项

资产遍历参数及参数组、全局/组件函数（含子特征）、变量声明与选择、材料属性组、组件坐标系属性、几何特征状态、命名选择/配对、物理特征及 physics.prop 属性组。组件 `sorder()` 和物理属性中的离散阶次仅作读回，不由建模入口设置。不同接口的属性名、返回类型和默认节点需在对应版本查证。

枚举或遍历失败保留 `aborted_with_read_error`，已有 TSV 不删除；单属性读取失败计入 read_error_count。没有支持的 getter 时 `not_read` 仍保留；inventory_status=completed 只表示计划中的遍历结束且无读取异常，**不表示所有值已读取或模型物理正确**。需逐项审阅 not_read、外部依赖和未覆盖树，才能确定共同 manifest 各 inventory 的 complete/partial/not_inspected。

constitutive/boundary、材料覆盖、配对正确性、空间选择及网格/求解验证仍是 not_run；旧网格/研究/解标签存在不证明有效性。盘点不得将空标签列表用于超出该清单的“整个模型无此内容”结论。

## 来源与验证分层

修复依据为 2026-11-01 历史 `sources-inventory-v03/InspectModel.java`（SHA-256 `ad6cfa1e63eb6387b4b765bea8689f03dc936f398c8891edb378a40059a0d64b`）。该副本曾在一个二维导热模型上完成 1662 行盘点、0 读取错误，仍存在 `material.customize` 的 None/not_read；原始报告与哈希不改写。模型已清理，不能据此声称当前文件校验通过。

本地 COMSOL 6.3 Java API 查证页：`ExpressionBase`、`ModelParamGroup`、`ParamBase`、`Selection`、`Expr`、`ExprList`、`ExpressionEntity`、`XDLocalSelection`、`ModelNode`、`physics.Physics`。通过配置的安装目录定位 `doc/help/wtpwebapps/ROOT/doc/com.comsol.help.comsol/api`，不把本机路径作为通用常量。

2026-11-02 的 `validation/live-candidate-validation-20261102/modeling/verification-summary.json` 记录：当时资产 SHA-256 `0da3af2e278dd9ac24e139e0cc5453a89ce598b83db94e1b525ebe04407c41a5` 的 InspectModel 已真实编译，并分别读回新建及修改后的单域导热模型，各 1694 行、0 读取错误，包含非空参数组及全局/组件变量。变量单位和不支持属性仍为 not_read；这是该精确源码及该两个模型的历史读取证据，不是物理断言或其他接口的通过。该轮单类生成修复未改该资产字节，验证等级以各份带日期和哈希的证据为准。历史模型已清理，不能声称当前文件存在；复杂参数组及其他物理场仍未验证。

2026-11-02 的 v4 仅修正源码头部陈旧验证说明，当前 InspectModel 源码 SHA-256 为 `d91c293997075c0eecd47036fabd1af79d95b1672e9dfeb8ff12d8440175aff4`。它已在本轮瞬态导热新模型上重新编译和只读运行，1709 行、0 读取错误，源文件哈希不变；记录位于验证工作区 `v4/m/extra/transient-inventory` 与 `v4/m/modeling-summary.json`。此盘点包含材料密度、热容与物理初值节点，但正确性来自另行执行的137项物理断言。其他复杂接口及 not_read 项不因此获得验证。
