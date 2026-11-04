# 小型稳态电热耦合适配器

仅在任务符合 `examples/joule-slab/case-spec.json` 时使用。它覆盖二维单域直边矩形、常数各向同性电导率与热导率、两端电位和恒温、其他边界绝缘/绝热、单一 ElectromagneticHeating 耦合。电流产生热源，材料参数不随温度变化；这是单向电热耦合，不是温度反馈或非线性双向耦合验证。

建模侧拥有几何、材料、`ConductiveMedia`/`HeatTransfer`、电热耦合、厚度及物理边界。计算适配器只读检查这些约定，创建新网格/研究/求解器和结果读取节点；任何不匹配返回建模侧，不修改物理定义换取运行成功。

## 按需入口

- `examples/joule-slab/scripts/prepare_case.py --case CASE --out NEW_DIRECTORY` 只生成 pending 配置，资源、路径、编码和运行身份保持待定，不编译、不启动 COMSOL、不授予授权。
- `src/JouleComputeAdapter.java` 是单顶层类的 Java 批处理入口。`solve` 创建新结果并保存；独立 `readback` 进程载入保存解；`export` 只读现有解，缺失、空解或身份歧义时停止。
- `scripts/stage_driver.py` 由通用 `run_bundle.py` 调用，消费新建的公共/计算操作审查、当前授权及 source/class/config pins。必须同时固定本例及 `steady-slab/scripts/prepare_case.py`、`stage_driver.py`，因为资源、日志、短路径和网格读取检查复用这些随同一 skill 发布的模块。
- 案例科学定义的摘要校验有意限制此专用实现的范围。改变目标语义、物理参数集合、位置、单位或统计方式时，先审阅并适配代码；不要只改摘要使旧适配器接受新问题。

## 结果与物理核验

本例返回 45 个固定笛卡尔点上的温度、电位、电流密度、焦耳热源及导热通量，并分别计算体积焦耳功率、左右端外向热率及电极供电功率。所有二维积分只计一次厚度。左右边界均用实际三角形邻接验证其为单邻域外边界，之后才使用 `mean(d(...))` 域侧迹；这一约定不适用于一般内部界面。

设两端电位为 0 和 U、两端温度为 T0，则本验证例的解析量为 `V=U*x/L`、`Jx=-sigma*U/L`、`Q=sigma*(U/L)^2`、`T=T0+Q*x*(L-x)/(2*k)`。应分别核对采样场、体积热源积分、两端散热和电极供能；不能只检查一项平衡式。U 翻倍时电流翻倍，热源、功率及温升变为四倍；电压变化必须由建模侧另建并检查模型。

保存解读取绑定实际 solver、study、载解文件和单一 stationary solnum。数据集在读取会话内创建，不声称持久化。网格质量显式取域维度，实际 FE 三角形与保存序列的坐标/连接逐项对应；该证明只覆盖已支持的二维直边一/二阶三角形布局。

本机 COMSOL 6.3 官方来源：`llmatlab_introduction.2.15.html`/`.2.16.html` 的 ConductiveMedia 与 ElectromagneticHeating；`.2.27.html` 的 `ec.Qh` 功率积分；`comsol_api_results.52.077.html` 的 IntSurface/IntLine 数值积分。来源支持 API 用法，真实能力以 [本轮验证记录](live-validation-v3-20261102.md) 中的最终源码与运行证据为准。

常数参数下的线性电位和二次温度能被所用离散表示。因此解析吻合或两个网格吻合不证明一般收敛率、实验有效性、温度依赖材料、非线性、多域界面、瞬态或可靠续算。误差限及资源预算由当前任务确定。
