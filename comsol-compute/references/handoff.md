# 输入与共同交接 2.0.0

共同维护入口是开发工作区 handoff-review，由建模执行者维护；计算侧携带 [共同协议](protocol.md)、[schema](model-manifest.schema.json) 和公共代码的逐字节发布副本，独立运行时不依赖该开发目录或另一个 skill。candidate03 的 [公共接口](validator-interface.md) 返回 errors / side_errors / todos；公共 errors 条目为 code/instance_path/message，符合性比较 (code, instance_path)。public_errors 仅为旧版兼容别名，error_messages 仅供显示。三类分别处理；双方公共分类应相同，侧别检查与待办可以不同。

## 接收入口

```powershell
python .\scripts\input_record.py --manifest 'D:\任务\model-manifest.json' --out 'D:\任务\本次输入记录.json'
python .\scripts\input_record.py --mph 'D:\任务\原模型.mph' --out 'D:\任务\仅文件待检记录.json'
```

只读输入，输出为新文件。相对模型、依赖、证据路径按 manifest 目录解析；兼容 UTF-8 BOM。输入记录包含唯一 ID、manifest 原文快照和散列、公共副本散列、模型来源及分类结果。

- input_files_verified / 退出 0：公共与计算侧文件检查无错误；不表示内部模型正确或已授权。仍需处理 todos，并产生本次 operation_review。
- rejected / 退出 2：版本、字段、文件或侧别条件失败；保留原件和分类，不能忽略后运行。
- pending_model_inspection / 退出 3：只有 MPH，已散列但未打开/盘点模型。记录未知依赖而非空依赖；可以独立准备方案，后续在获授权范围内只读盘点。

execution_readiness 保持 not_assessed；ready/pending/blocked 属于独立操作审查。文件检查、操作就绪、当前授权和科学验证是不同状态。

## 必查声明及共同语义

核对模型/来源路径和 SHA-256、COMSOL 版本/build、当前所需模块、物理接口、材料与选择、参数/假设、目标量和未解决项。许可声明不代表当前许可可用；本轮候选修复不进行任何许可探测。

selection_ref 按 kind 解读，不再猜字符串：

| kind | 计算侧核对 |
|---|---|
| named | 组件/选择存在且归属匹配；维度/几何取已登记选择。 |
| all | 明确组件、geometry、entity_dimension；不能从字符串 all 推断范围。 |
| inline | 明确生成规则、作用范围与检查证据；不当成命名选择节点。 |
| global | 明确非实体或全局量；与未知选择不同。 |
| pending | 原因及 unresolved_ids 必须可追溯；不能补成 all。 |

配对两侧只能使用该配对适用的实体引用；公共校验检查声明一致，不证明空间重合、方向或真实位置。实际选择仍需模型检查。

目标量 name 唯一。expression、unit、coordinate_system、statistic、time、frequency、parameters、mode 统一使用共同 definition={status,value,reason,unresolved_ids}：complete 的值非空白；pending 明确原因及关联问题；not_applicable 给理由。使用共同 selection_ref 和 required_solution，删除旧私有 extensions.compute_output_definitions 约定。不能从历史案例补单位、坐标或统计规则。

所需解明确 existing/planned/pending/none；existing 引用 legacy.solutions，不能仅凭 tag 猜已有解。export 需要的解缺失或只是 planned 时保持未就绪，不能自动求解。

inventory 的 complete/partial/not_inspected 与内容分别对应已确认盘点、部分盘点、未盘点；未盘点集合为 null，空数组只表示已确认没有。unresolved 逐条记录 id、问题、owner、evidence、affected_scope 及 solve/resume/export 的 effect/reason；未知影响不能被当作无影响。

## 依赖、旧证据和输出

dependencies 明确 category=runtime/source/audit、角色、存在状态、必需性、适用操作和散列。公共审查自动收集适用 runtime 文件；计算配置补充实际脚本/class/源解等输入。运行前检查所有声明的适用运行文件都在 pins 中并重新散列；只 pin manifest 不充分。审计资料为审查依据时同样保留散列，但不冒充 runtime 文件。

legacy.valid 必须说明适用模型/来源哈希、节点或解、参数/时间范围及证据。校验器只证明声明与来源一致，不证明旧解有效。旧检查的模型绑定不可改写；继承通过 inherited_checks 另记原始检查、原模型、适用范围、依据和限制。

输入 manifest 保持不变。求解后另建输出记录，关联输入记录、输出 MPH 哈希和本次检查；不能把原检查哈希替换为输出哈希后继续标 passed。跨文件继承的有效性仍须独立评估。

## 版本与显式迁移

仅消费候选 schema_version=2.0.0。旧 1.0.0 或未知版本拒绝自动解释，不能只改版本号后重试。若需要迁移，单独生成新文件，保留原始 manifest 的路径/哈希与来源关系；对未盘点内容、待定目标和旧证据保持未知/原绑定，不能凭空产生 passed 或证据文件。

本计算侧未提供自动迁移器；按 [显式迁移规则](migration.md) 另存并验证。来源绑定矛盾为 LINEAGE_BINDING，无法核实的 v1 来源保留 LINEAGE_PENDING 待办。同为 2.0.0 的候选也按发布清单哈希区分；candidate02 操作审查须从原输入重建，不改写旧证据。公共 schema/核心若有歧义或缺陷，提供最小复现反馈共同维护者修订，不能单方更改公共发布副本或错误分类。

共同 candidate04 的 [解身份与证据继承说明](solution-identity.md) 适用于生成父模型/实际载解文件、逻辑ID/实际解ID及内存dataset的区分；schema_version仍为2.0.0，以发布清单哈希识别修订。
