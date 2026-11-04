# 温度相关电导率的双向电热小例

仅用于 `sigma(T)=sigma_slab/(1+beta*(T-T_ref))`、常数各向同性 `k_slab`、二维直边矩形、两端固定温度/电位和侧面绝缘的稳态案例。温度反馈至电导率，电损耗通过唯一的实际 `ElectromagneticHeating` 耦合进入热方程。参数是合成验证定义，不能当作材料数据或通用默认值。

源码位于 [NonlinearJouleComputeAdapter.java](../examples/nonlinear-joule/src/NonlinearJouleComputeAdapter.java)，准备与阶段检查位于 [prepare_case.py](../examples/nonlinear-joule/scripts/prepare_case.py) 和 [stage_driver.py](../examples/nonlinear-joule/scripts/stage_driver.py)，完整科学定义见 [case-spec.json](../examples/nonlinear-joule/case-spec.json)。该例复用本 skill 的 steady-slab 资源守卫、日志检查、隔离路径和直边三角网格对应检查；实际运行须固定这些共享模块与本例源码、class、设置和当前授权。纯 prepare 仍只生成未就绪计划，不能推断执行权。

计算代码不修改物理模型。进入运行及独立重载时读取并核对电导本构和材料来源；导出场量、热流、焦耳热积分及两端供电功率。边界供电功率也必须使用温度相关电导率，不允许套用常数电导公式。45 个采样位置检查电导分母为正并记录最小值；这是采样检查，不是整个有限元域的区间下界证明。

本例存在独立解析解。记 `theta=T-T_ref`，`U=V_right-V_left`，`z=atan(U/2*sqrt(sigma_slab*beta/k_slab))`，`a=2*z/L`，`j=a*sqrt(k_slab*sigma_slab/beta)`。则

```
T = T_ref + (cos(a*(x-L/2))/cos(z)-1)/beta
V = V_left + j/sigma_slab*(sin(a*(x-L/2))+sin(z))/(a*cos(z))
Jx = -j
Q = j^2*(1+beta*theta)/sigma_slab
P = j*U*H*thickness
```

上下绝缘、两端等温条件下每端散热为 `P/2`。验证应比较实际保存解的场量、供电/生热/散热和网格加密后的误差；求解器迭代终止本身不证明数值准确。应在看结果前为具体任务给出误差标准，不从本例提取万能阈值。此单一平滑正电阻分支不能证明热失控、接触、电磁波、任意非线性或任意续算可靠。

2026-11-02 的 v4 已完成本例两次正式求解及各自独立进程重载。实际三角形从 86 增至 332，整体及左/中/右区域最大、平均边长均减小；各解析场量和能量误差均下降。细网格最大温度误差为 `2.6972e-5 K`，最大 x 向电流密度误差为 `67.941 A/m²`，生热与两端散热残差为 `7.3352e-5 W`，均满足求解前冻结的案例门槛。真实材料、参数、解身份、FE 网格与保存载体绑定均由读回与独立审计核对。

证据在开发工作区 `v4/n/final-summary.json`、`v4/review/nonlinear-complete-independent.json`，保留当前正式源码、运行包和原始数值；MPH/class/私有缓存按用户要求在最终审核后清理。源模型的常电导负例被建模正式检查拒绝。此前 v3 常电导案例是不同问题，不作为本例的实测证据。此处仅有两级网格误差下降支持，未证明渐近收敛阶或一般非线性可靠性；本例的正式仅提取入口尚未单独实测。

2026-11-03 用新的0.2 V模型完成粗网格求解、独立读回和正式仅导出；全部9目标与保存解读回一致，载解文件未改写，见 [v5记录](live-validation-v5-20261103.md)。
