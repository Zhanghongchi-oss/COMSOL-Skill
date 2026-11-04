# 小型电热耦合建模

仅在需要构造可解析核验的稳态电热耦合小例时使用 [JouleModel.java.in](../examples/joule-slab/JouleModel.java.in) 和 [case-spec.json](../examples/joule-slab/case-spec.json)。它展示如何从两个物理接口和实际多物理耦合构建模型，不是通用材料、尺寸、边界条件或误差默认值。

从 skill 根目录生成一个新的、同顶层类源码：

```powershell
python assets/conduction-readback/render.py --source examples/joule-slab/JouleModel.java.in --output <新目录>/JouleModel.java --record-method ok
```

模板支持 `mode=build` 和 `mode=check`。使用正式 `Invoke-ComsolJava.ps1` 及当前操作审查；build 另存并卸载重载，check 在新进程只读加载实际文件。job 按案例明确提供 L/H/thickness、k_slab/sigma_slab、T_left/T_right、V_left/V_right、audit_tolerance、case_spec_sha256、check_output；build 另需 output_model/diagnostic_output，check 另需 input_model。新建/修改/检查的授权与资源按当前任务确定。模板不创建网格、研究或求解器，不求解。

本例使用 `HeatTransfer` 和电流接口实际 API 类型 `ConductiveMedia`。`emh` 为实际 `ElectromagneticHeating` 耦合，读取其 `EMHeat_physics=ec` 与 `Heat_physics=ht` 证明绑定；不额外添加第二个 HeatSource。温度、电势、材料来源、实际实体覆盖与激活状态逐项检查。单域标准导热检查继续从已有维护片段生成；电流本构读取 `cucn1` 的 `ConstitutiveRelationJcE=ElectricalConductivity`、`sigma_mat=from_mat`、全局坐标系和实际域选择。两个物理接口各自的二维厚度均显式为 `thickness`，其中电流是 `ec.prop("d").getString("d")`。不能只确认两个接口或耦合节点存在。

API 来源为本机 COMSOL 6.3 官方 `com.comsol.help.llmatlab/llmatlab_introduction.2.15.html`（接口和电势边界）、`.2.16.html`（实际电磁热耦合），以及 Java API `physics/MultiphysicsCoupling.html`。这些相同的 Java 对象方法无需安装 LiveLink for MATLAB；文档中的 MATLAB 调用形式在 Java 中使用方法括号。COMSOL 6.3 的非求解属性盘点已确认上述属性名和值；新接口/版本仍须查证，不根据界面显示名猜 API 类型。

计算交接区分科学输入与数值配置。基准 0.1 V 和第二模型 0.2 V 是两个由建模侧明确定义的物理问题；几何、材料和边界类别保持一致。计算侧可检查电势、焦耳热密度、温度分布和能量平衡，并验证电压翻倍时功率及超温四倍；不得为了收敛改动这些物理输入。有限的抛物解析解测试不证明其他电磁接口、热物性非线性或通用续算。

本例发现 `component.measure().getBoundingBox()` 将 0.02 m 返回为恰好等于 float32 舍入后扩展的 double 值；官方 API 只声明返回 double[]，没有承诺单精度。检查保留 job 中原始几何容差，并仅为该 getter 额外接受“等于期望值的精确 float32 roundtrip 且误差不超过半个 float ULP”的读数；不接受任意相近但不满足该条件的坐标。同时读取矩形 size/pos 的精确参数表达式。此项不修改实际尺寸、材料或数值结果验收门槛，也不应推广到其他 getter。首次失败及修复依据保留，离线边界测试只说明该算术规则，不能冒充实际 Java/API 行为。

2026-11-02 的 v3 验证使用正式生成器和正式建模运行入口：0.1 V、0.2 V 两个模型各完成 350 项保存前/重载后检查；各自独立新进程只读检查为 176 项。实际源码 SHA-256 为 `0b03e916b76f957a3f8b4c86251e561ad33fec4009d3063644e0d11e3b25b4fe`，源、job、断言和资源记录位于验证工作区 `v3/modeling`。这证明所述模型的构建和实际读回，不替代计算侧的求解、能量平衡、加密或续算验证；不能提升为任意多物理接口已验证。清理后原 MPH 不再可现场复验，应使用保留的原始证据及清理回执，不改写历史绑定。

同轮两个隔离故障副本提供真实负例：导热材料首对角项变为 `2*k_slab` 后，原正式导热检查拒绝 `isotropic_conductivity`；电热模型仅禁用 `emh` 后，正式电热检查拒绝 `joule_coupling_active`。这些副本不作为有效模型交付，原模型保持不变。COMSOL launcher 两次仍退出零，因此判断来自实际失败断言及日志，不能以退出码替代检查。
