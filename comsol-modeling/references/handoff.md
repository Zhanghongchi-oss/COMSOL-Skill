# v2 接收、交付与操作准备

本页处理建模侧工作流。字段及公共错误的唯一维护源是候选工作区 handoff-review；本 skill 独立携带 [共同规范](protocol.md)、[manifest schema](model-manifest.schema.json)、[公共接口](validator-interface.md)、[迁移](migration.md)、[操作审查规范](operation-review.md) 及其实现副本。运行时不读取另一个 skill 或 handoff-review。共同版本 2.0.0 candidate04；按发布 SHA-256 同步，计算侧未同步时不得宣称三方一致或联调通过。

## 接收

```powershell
python ./scripts/validate_manifest.py --manifest ./model-manifest.json --out ./input-receipt.json
python ./scripts/validate_manifest.py --mph ./input.mph --out ./mph-receipt.json
```

输出文件必须新建。前者调用本 skill 携带的公共校验实现，区分 errors/side_errors/todos，公共 errors 使用 code/instance_path/message（public_errors 仅旧接口兼容）；后者只散列原 MPH 并返回 pending_model_inspection，内部 inventory 未检查。都不启动 COMSOL。缺另一 skill 或 manifest 时可继续准备方案，不能据文件名或空数组补造内部状态。

input_files_verified/退出 0 只说明文件合同声明一致。它不证明空间位置、物理适定性、旧解有效、执行就绪或授权。待盘点字段用 null 和 inventory 的明确未盘点状态；完整盘点且确认无内容才用空数组。

## 准备与执行门槛

使用 scripts/operation_review.py 产生独立 operation_review，具体命令见 [操作审查](operation-review.md)。审查绑定输入 manifest 与模型哈希、操作和 scope，逐项处理未解决问题、目标完整性与依赖。scope 以明确 ID 表示；超出范围的问题仍保留并说明不影响的依据。ready/pending/blocked 是准备状态，均不是当前授权。

依赖分类为运行、来源、审计/交付资料。运行所需外部数据、源解、脚本、class 等全部纳入 pins；manifest 自身的 pin 不替代它引用的文件。准备后复核文件变化、必要依赖遗漏和范围变化。Java 入口要求独立审查及当前授权；只提取缺少已有解时返回待办/阻断，不能自动转求解。

未知或阻断项可以随 prepare 交付，但标为未完成方案；不得将文件校验返回 0 包装成可执行运行包。新建尚无模型时用明确 new_model 准备记录，不生成假 MPH/manifest；只有 MPH 的只读盘点使用 mph_only 记录，不能升级为求解准备。

## 建模交付和证据

交付保存后的 MPH、可复现源码/入口、建模说明、检查记录及 manifest。材料/选择/配对/本构等按实际执行的检查填状态；未执行保留 not_run/blocked。输出量的 expression、unit、selection_ref、coordinate_system、statistic、time/frequency/parameters/mode、required_solution 均使用共同定义；不保留计算私有输出扩展，不抄旧实验默认值。

输入 manifest 保持不可变。修改输出另建 manifest/记录，关联输入记录、输入模型和输出 MPH；lineage 的源 manifest 内 model 必须与 input_model 对应，源记录内相对路径以其自己的目录为基准。输出变化不能只替换原检查中的模型哈希。旧检查保留原始绑定，若有继承，另记原证据、理由、适用范围和限制，不能冒称新检查。legacy.valid 还须给出适用模型/来源哈希、节点或解标识、参数/时间范围与证据；只读文件工具仅能核对来源一致。

物理初态属于建模事实或显式假设；求解器初始猜测属于计算配置。研究物理启停、多步初始化及延拓若改变已确认物理问题，须返回建模决策，不能以研究配置为由自行改变。

生成父模型与实际载解 MPH 分开绑定；目标引用逻辑 legacy ID，实际 solution_id、solver tag 与 dataset 生命周期另核验。按 [解身份与证据生成](solution-identity.md) 操作，不继承已失效的无 study/无 solution 断言。历史 MPH 清理后只可引用历史观察，不能宣布当前文件校验通过。

## v1 的显式迁移

v1 输入按 SCHEMA_VERSION 拒绝自动消费。若用户请求迁移，先保留原 v1 文件和 SHA256，另建 v2 文件并在来源记录中关联原件；不覆盖原 manifest。逐项重新解释旧字符串选择和输出语义，能由证据确认的才填 complete，无法确定的建 pending 与对应 unresolved，未盘点内容保持 null。旧 checks 连同原模型绑定保留为来源证据，不换哈希升级；重新检查没有执行就标未执行。迁移完成仍需共同校验和操作审查，不构成运行授权。
