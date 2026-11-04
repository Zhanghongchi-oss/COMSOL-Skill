# 小型瞬态导热与保存场接续

`examples/transient-slab` 是固定二维、单域、常数材料、静止几何的正弦初温验证例。它不是任意瞬态模型的通用求解器。物理初态由建模侧配置为 `T_base+T_amp*sin(pi*x/L)`，计算侧不修改该表达式、材料、边界、几何或物理启停。

## 准备与执行

`scripts/prepare_case.py --case ... --out 新目录` 只写 `plan_prepared_not_executable` 方案；它不编译、不开 COMSOL、不授予权限。正式执行仍需本 skill 的公共与计算审查、当前授权、`run_bundle.py`、受审查 Java/class 和资源保护。实际执行依赖包含本例 helper/driver、steady-slab 的共享 helper/driver/resource_guard、运行配置及私有偏好模板；不能只 pin 一个 Java 文件。

本例的完整、半程和接续目标分别固定为 0–1 s、0–0.5 s 和 0.5–1 s，每 0.1 s 输出。在每个实际保存时刻读取 9×5 个域内温度点，包括矩形端点；T/K、实体、坐标系、统计、时间和参数定义必须匹配固定 case。语义 digest 或任何科学字段变更都需要重新审查适配器；不能修改 case 后直接宣称支持新任务。参数和门槛只属于这个验证例。

## 接续的准确含义

这里验证的是**从已保存场重新初始化时间积分器**。输入必须是已审核半程载解文件，实际 `getPVals` 的最后时刻为 0.5 s。新的 study/solver 使用同一保存网格，在 Variables 中显式选择源解、`initmethod=sol`、`solnum=last`。原物理 Initial Values 节点保持不变。

保存场重新初始化不保留 BDF 的全部历史，也不等于崩溃恢复或任意中断续算。记录源文件哈希、源解 tag、源末尾 solnum/time、新解起始 getU 与源末尾 getU 的差异；独立进程重载结果，并和未分段计算、解析衰减比较。checkpoint 的字符串一致性不能代替这些实际证据。

`getU` 可能同时含温度和边界约束乘子。先用官方 XmeshInfo 的 `dofNames/nameInds/solVectorInds` 识别分量和排列；不能把整个向量差写成 K。只有已识别的温度分量或明确 T[K] 的点值可使用温度误差门槛；其他分量保留原始量及未知单位，不虚构共同容差。不同排列不能直接逐索引相减。

本机官方 `comsol_api_solver.51.56.html` 列出 Variables 的 `useinitsol`，但 6.3 build 290 的自动生成节点可能不公开此属性。读取实际 `properties()/hasProperty()`；缺失保存为 `available=false,value=null`，不能当作默认 off 或伪造 on。实际暴露时才设置/读取该属性。初始化方法、源解、solnum 和 control 仍要从 API 读回；保存后再读一次。最终用实际场接缝验证，不能仅凭设置成功证明接续。

## 证据与限制

每个求解阶段之后使用新的 COMSOL 进程打开保存文件。原始 JSON 含实际时间列表、全部 getU 向量、45 点温度、保存的初态配置、tlist/rtol、Xmesh 与网格序列坐标/连接匹配；stdout/stderr/batch/资源记录分别保留。退出零或保存文件出现不等于通过。

静止直边三角形的网格匹配沿用已验证的狭窄检查，不推广到曲边、高阶任意单元、重网格或移动网格。该例没有温度依赖材料、参数扫描、外部运动状态或事件；这些模型的接续必须另查场状态和求解器历史。数值准确性与接续接缝由独立验收计划裁决，runner 的 `resume_reliability` 不自动升级。

本轮实际测试状态以工作区 `v4/c` 和 `v4/review` 的最终记录为准；失败尝试同样保留，模型删除后不得把历史散列记录冒称为仍可实时检查的 MPH。

## 仅提取已保存瞬态解

正式 `run_bundle.py export --bundle ... --authorization ...` 使用 `operation=export`，不能调用 `run` 代替。目标的 `required_solution.kind` 必须为 `existing`，`id` 指向已审核有效的 legacy 记录；逻辑记录 id、实际 solution_id/solver tag 和载解 MPH 路径/哈希分别核对。完整科学目标仍由 `kind=full/half/resume` 的区间定义决定，不能以仅提取为由改时间、单位、采样或统计。

审查后的 settings 记录 `legacy_solution_id`、`solution_id`、`solution_tag` 与共享 `resolve_export_identity` 返回的 `export_identity`，其余运行依赖照常 pin。导出分支仅启动一个 `export` 阶段：重新打开已有 MPH，按实际 solnum 读取保存时刻和 45 点 T[K]，写入 JSON 与网格证据；不会创建网格/研究、求解或保存源 MPH。缺解、身份错误或实际时间不匹配即拒绝，不退回求解。

输出同时记录实际数据集绑定的 solution tag、逐个 solnum 和时刻、坐标单位 m、温度表达式 T/单位 K。数据集只在本次读取进程内创建，`dataset_persisted=false`，不能宣传成源 MPH 内已有数据集。正式入口是否实测及其精确范围，以对应本轮验收记录为准；不能仅从 Java 支持 `mode=export` 推断整条交付链已通过。

2026-11-03 的完整0–1 s正式export已在新载解模型上实测，通过独立比对；half/resume区间导出没有本轮单独实测，见 [v5记录](live-validation-v5-20261103.md)。
