# 解身份、生成顺序与历史证据（2.0.0 candidate04）

本页解释既有字段，无 schema 扩展。依据为 2026-11-01 实机审核中的载解文件误绑、逻辑 ID 误用两个反例；既有操作门禁和计算运行门禁正确拒绝，不能弱化。

## 生成时逐步映射

1. 分别读取并散列生成父模型、当前输入模型、实际载解 MPH。记录父模型于 source_model/lineage；不得复制父模型哈希到旧解 applies_to.source_model_sha256。当前模型与载解文件可以相同，父模型另存。
2. 仅在 kind=existing 时，用 `target.required_solution.id` 精确查找 `legacy.solutions[].id`。从该项取得实际 `solution_id` 与 `tag`，从 applies_to 取得适用模型及载解哈希。缺记录、unknown 有效性或未核实范围保持 pending/blocked；不猜 sol1，不替换 logical ID。kind=planned 仅声明未来解请求，可没有 legacy 项；不得因此生成假旧解。
3. 只读实际载解文件、实际 solution/solver tag、可用位置和参数范围，形成独立读回证据。运行适配器使用实际 solution_id；逻辑 legacy ID 另列作为关联键。载解文件加入适用 runtime pins；只固定 manifest 不够。
4. dataset 属于计算侧实现。记录 tag、何时创建及是否已保存；内存 dataset 可用于本次已授权提取，但不标记为 MPH 中已有节点。manifest 不增加 dataset 字段；引用独立读回/实现记录。
5. 逐条筛选可继承检查，保留 original_check / original_model。只继承有来源审计和实际读回支持的未变物理定义；删除继承候选中的无 study/无 solution 等已失效断言，原始证据仍不改。不将原 232/117 条历史检查计作当前输出的新检查。
6. 目标保持科学定义。若 API 需要实现映射，另存 audit 记录说明表达式、单位、方向、统计、几何邻接前提和等价依据；原记录不可覆写。仅实测成功后填本次求值证据。
7. 当前输入与完整证据存在且通过相应操作审查后，另核对当前授权。仅提取缺解立即停止，不转求解；历史操作授权不继承。

例如（仅身份示意，不是模型默认）：父文件哈希 A，载解文件哈希 B，A≠B；逻辑 ID `registered-result`，实际解 ID `solution-data`，solver tag `solver-sequence`。required_solution.id=`registered-result`；legacy.solution_id=`solution-data`；legacy.tag=`solver-sequence`；source_model_sha256=B。将 A 作为 export 源但未提供实际载解 runtime 文件，会触发既有 OP_SOLUTION_PIN_MISSING；把实际 ID 放入 required_solution.id 会触发 SOLUTION_REFERENCE。把逻辑 ID 写入运行观察的 solution_id 由计算运行身份门禁拒绝。

## 本次导热实现的适用范围

科学量为域温度全局 x 导数在外边界的迹，API 使用 `mean(d(T,x))`。只有经审核该边界恰有一个邻接域时，平均值才是同一迹。多域内部边界、不同导热率或方向约定不能套用。线积分被积量单位与最终热率单位分开；厚度恰乘一次。具体数值、实体编号、误差限均不成为通用配置。

## 历史与当前可用性

真实记录包括 `shared-handoff-live-review.json`、`export-solution-carrier-definition-v2.json`、`export-identifier-definition-review.json`、`coarse-export-inheritance-review.json`、`boundary-target-implementation-decision.json`，位于本次发布清单引用的只读 `validation/live-validation-20261101/review`。发布另存这些文件的内容哈希，不把其绝对路径作为运行依赖。

cleanup 已删除的 MPH：历史观察仍可引用，当前 FILE_MISSING 不得改成通过。公共测试使用明确标记的假字节，正反例故意使用不同 A/B、不同逻辑/实际 ID；它们验证合同与映射拒绝，不能证明 API 或旧解科学有效。
