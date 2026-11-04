# 小型瞬态导热建模

本例补充稳态模板不覆盖的**物理初始条件、密度与热容**检查。它只构建几何、材料和物理场，不创建网格、研究或求解器。使用 [TransientModel.java.in](../examples/transient-slab/TransientModel.java.in) 和 [case-spec.json](../examples/transient-slab/case-spec.json)；参数均为本例明示的合成验证常数，不能作为其他问题的默认值。

通过正式 `assets/conduction-readback/render.py --source … --output …/TransientModel.java --record-method ok` 生成单类源码，再使用 `scripts/Invoke-ComsolJava.ps1` 的当前授权、操作审查与私有运行环境。`job.properties` 包含 case 中八个参数、`audit_tolerance`、当前 `case_spec_sha256`、`mode=build|check`、`check_output`；build 另含 `output_model`、`diagnostic_output`，check 使用绝对 `input_model`。输出名相对于新运行目录，绝不能复用旧运行目录。

物理问题为二维矩形：两端温度 `T_base`，上下边绝热，初值 `T_base+T_amp*sin(pi*x/L)`。材料的 `thermalconductivity`、`density`、`heatcapacity` 分别明确绑定 `k_slab`、`rho_slab`、`Cp_slab`。所有物理值由建模侧拥有，计算侧可以从已验证旧解恢复计算状态，但不得把 `ht/init1/Tinit` 改成别的物理初值来冒充续算。

检查保留标准导热片段的材料、厚度、默认节点及覆盖断言，另外读取 `solid1/rho_mat`、`Cp_mat` 是否 `from_mat`、材料标量表达式、正值、`init1` 类型/激活/来源/表达式/实际域覆盖，并排除额外初值节点。仅存在 `init1` 或默认 293.15 K 不能算瞬态问题已定义。build 保存后重载执行相同检查，还必须另开只读 check；只有实际检查报告可以决定通过，启动器退出零不足以验收。

COMSOL 6.3 本地依据：`com.comsol.help.heat/heat_ug_ht_features.09.019.html` 说明 Initial Values 是瞬态初始条件或非线性初猜；`.09.042.html` 给 Solid 的密度、热容和扩散率定义。属性键的依据是 v3 同版本真实只读诊断中的 `rho_mat/Cp_mat/Tinit_src/Tinit`，本例须以自己的实际读回再核验，不能仅凭历史字段通过。

数值验证交给计算侧：本例精确解为 `T_base+T_amp*sin(pi*x/L)*exp(-k_slab*pi^2*t/(rho_slab*Cp_slab*L^2))`。解析式由恒定系数热方程与上述初边值推导；实际求解精度、时间点、保存重载和续算仍需各自证据。

2026-11-02 的 v4 建模实测：当前正式模板经同一正式 renderer 生成，build 保存重载完成 272 项检查，独立只读 check 完成 137 项，原版入口调用的当前 InspectModel 盘点 1709 行、0 读取错误；模型没有网格/研究/解。另存将物理初值改成常值 `T_base` 的小模型，正式 check 在 `physical_initial_expression` 真实拒绝，源文件未变。该负例的进程仍退出零，因此验收明确使用失败报告，不采纳退出码为通过。证据和当前源/输入绑定位于候选工作区 `v4/m/modeling-summary.json`；这只证明上述模型定义与拒绝路径，不证明全部瞬态物理接口或可靠数值续算。
