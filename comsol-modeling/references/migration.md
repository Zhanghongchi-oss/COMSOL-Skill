# 1.0.0 → 2.0.0 显式迁移

迁移是单独授权的数据整理操作，不是对旧记录的自动容错。v2 校验器遇到 v1 返回 SCHEMA_VERSION，不静默解释成 v2。迁移不启动 COMSOL，不赋予后续真实计算授权。

1. 保留原 manifest、原模型及原证据文件，记录 SHA-256；在新路径写 v2。不得覆盖输入。`lineage.relation=migrated`，`input_manifest` 指向原记录，`input_model` 指向核实的原模型；迁移记录应保留原文件关联。
2. 只转换能由原记录或明确证据确认的字段。旧字符串选择不能直接映射为 named/all；分别核对组件、几何、实体维度、命名选择是否真实登记。无法确定用 pending，给原因及结构化 unresolved。
3. 目标逐项迁移表达式、单位、选择、坐标系、统计、时间/频率/参数/模态位置及所需解。非空白表达式才可为 complete；未知项待定，不从历史案例补单位或位置。旧私有输出扩展经逐项解释进入共同 target_outputs，不能直接原样保留为新语义。
4. 未盘点数组为 null，inventory 为 not_inspected；部分清单为 partial 并保留未知项。只有确认完整且没有节点才可空数组。材料、本构、物理初态、依赖等未知内容不得自动补值。
5. 每条 unresolved 填 id、问题、责任方、证据、影响范围，以及 solve/resume/export 的影响和理由。未知影响为 unknown，不默认 none。
6. 原 checks 保持原模型绑定，不换成新文件哈希。没有运行的当前检查为 not_run/blocked；确需继承时另写 inherited_checks 的 original_model/original_check、依据、适用范围、限制和证据。旧记录的 passed 不能自动成为当前 passed。
7. 旧网格/研究/解逐项标 valid/invalid/unknown。valid 需要明确适用模型、来源模型、节点/解标识、参数/时间等范围与证据；文件存在不证明数值有效。几何/物理修改的影响明确记录，不能无条件删除全部旧节点。
8. 依赖重新分 runtime/source/audit；按实际操作登记运行所需文件并核实 pins。不能因原 manifest 已固定而认为其引用文件均固定。
9. 静态检查另存结果。未核实项保持待办，后续操作审查重新生成。源 v1 若只有可核对的 model.path（或 file）和 sha256，可仅用于来源绑定核验；不能提取时 LINEAGE_PENDING，不能伪造绑定或通过证据。

本候选没有自动迁移脚本。显式人工整理后仍须使用 v2 公共校验器；生成符合 schema 的 JSON 本身不是模型检查。
