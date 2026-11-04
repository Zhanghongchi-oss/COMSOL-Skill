# 温度反馈电热耦合建模

本例在常系数焦耳热案例上加入温度相关电导率 `sigma_slab/(1+beta*(T-T_ref))`。温度改变电导率与电流，`ec.Qh` 通过实际 `emh=ElectromagneticHeating` 驱动温度，因此是双向反馈；它与先计算电流再代入固定热源的单向案例有不同的物理定义。

使用 [NonlinearJouleModel.java.in](../examples/nonlinear-joule/NonlinearJouleModel.java.in) 和 [case-spec.json](../examples/nonlinear-joule/case-spec.json)。经 `assets/conduction-readback/render.py --record-method ok` 生成同名 Java 单类源码，使用正式 `Invoke-ComsolJava.ps1` 入口、当前操作审查和本任务权限。build/check 作业字段与 Joule 模板相同，额外明确 `beta`、`T_ref`。案例参数、尺寸、材料、温度、电压和几何检查容差都是合成测试定义，不是默认值。

建模侧拥有电导本构和反馈参数。实际检查必须同时读取：电导率标量或精确各向同性对角表达式、`cucn1` 的材料来源与全局坐标系、`ht` 与 `ec` 的厚度/域覆盖、耦合节点的激活与源/目标接口、两个电位与两个温度边界、余下绝缘边界，并排除重复 HeatSource。只看到 `emh` 节点或表达式里含 `T` 不足以确认完整物理绑定。保存后重载并重复检查，再以独立只读阶段核验实际保存文件。

这是稳态模型，没有定义物理瞬态初值；现有 init 节点属于数值初始化元数据。计算侧不得为了收敛将 `beta` 清零、把电导率改回常量、关闭耦合、删除边界或改变温度/电压。计算侧必须使用实际温度相关电导率计算电流和功率，且需要核验本构分母在实际温度场中为正；不能将常电导案例的功率公式、四倍温升结论或收敛经验直接移植。

建模负责几何、材料、物理与保存重载；网格、研究、非线性求解及独立数值验收由计算侧负责。模板明确不创建网格/研究/解。数值核验应包含独立解析参考、场量、热电功率平衡及实际网格加密；文档和静态审查不等于这些测试已完成，不能沿用 v3 常电导模型的通过状态。

2026-11-02 的 v4 实际建模证据：正式模板和正式 renderer 生成的源码，经正式运行入口完成 build 保存重载 354 项检查、独立只读 check 178 项检查；当前 InspectModel 读取 2237 行、0 读取错误。模型 SHA-256 为 `04b8aaacb21219a9d1a011f1f46e1d0fd0cfbbb91f53be8fdb77c376fa9e1454`。原始报告分别位于候选工作区 `v4/n/extra/nl-build/check.json`、`nl-check/check.json` 和 `nl-inventory/inventory.tsv`；只读阶段保留原文件哈希。此处通过范围是该特定温度反馈模型的几何、材料、物理绑定和保存重载。

同轮真实负例将电导率仅改成常量 `sigma_slab`，另存到 `v4/n/extra/nl-wrong-law/wrong-conductivity.mph`；原正式检查在 `v4/n/extra/nl-wrong-check/check.json` 记录首个失败为 `nonlinear_isotropic_electric_conductivity`，实际读数 `[sigma_slab]`。正确源与负例源文件在各自只读阶段均不变。COMSOL 启动器退出零，但失败断言使验收拒绝，未将该副本交付为有效模型。

计算侧另以当前同一物理模型完成粗/细网格求解及保存结果独立读回，实际三角形 86→332；独立非线性解析与能量检查记录于 `v4/review/nonlinear-complete-independent.json`。这些是计算侧证据，不是建模侧执行了求解，也不证明任意温度本构或通用非线性收敛。清理后应读取保留报告与清理回执，不把已删除 MPH 的历史检查当成当前文件仍存在。
