# COMSOL 6.3 本机查证索引

本索引于 2026-10-31 只读核验。以下是**文档支持**，不是本候选 skill 的 COMSOL 实机测试结果。其他版本先重新定位对应版本资料；存在同名属性不代表不同节点可互换。

## 查证方法

本机文档根目录 `<COMSOL_ROOT>\doc\help\wtpwebapps\ROOT\doc`，下文 `C/` 代表其子目录 `com.comsol.help.comsol/`。应用库根目录 `<COMSOL_ROOT>\applications`。这些路径是当前机器的只读资料位置，不是可移植 skill 的硬编码运行依赖。

1. 先识别模型/运行时版本、组件和节点类型、tag、物理接口及可用模块，再搜索对应版本文档。用 `rg -l -g '*.html' '关键词' <文档子目录>` 缩小文件范围，读取正文、属性表、可用值及适用条件。
2. API 方法签名查 Programming Reference 与 `C/api/com/comsol/model/` Javadoc；物理表达式查物理接口手册及模型实际变量定义；应用库用于理解配置关系。GUI 另存 Java 或 Copy as Code 可辅助定位，但不要把记录中含有的 `run()`、求解或物理修改当作已授权操作。
3. 对未知属性/接口错误，保留完整异常、节点路径、版本、已尝试值；核对属性属于研究步骤还是求解器节点、对象是否生成、值类型/单位及模块要求。`C/comsol_api_general.47.09.html` 列出 `properties()`、`getAllowedPropertyValues(String name)` 等内省方法；只对支持这些方法的实际对象使用。
4. 只有找到新证据才修改。原因仍不明时停止该配置路径，报告待查证点或改用已证实的 GUI 操作；不要猜属性名轮流重试，也不要通过改物理设置掩盖数值错误。记录来源文件、节点、属性/值、修改原因和验证结果。

## 研究与求解关系

| 任务 | 已核验来源（均在 C/ 下） | 关键判断与查证词 |
|---|---|---|
| 稳态 | `comsol_api_solver.51.78.html`；`comsol_ref_solver.36.015.html` | `Stationary`；适用于稳态目标。非线性分支/初始猜测要说明，不能把求解初猜当作物理初始条件。 |
| 瞬态 | `comsol_api_solver.51.80.html`；`comsol_ref_solver.36.016.html`、`36.120.html`、`36.136.html` | 研究节点类型 `Transient`；`tlist`、`tunit`、`usertol`、`rtol`。输出时间列表不等于内部积分步长；时间积分、最大步长、误差控制需查求解器节点。 |
| 频域/小信号 | `comsol_api_solver.51.68.html`；`comsol_ref_solver.36.027.html` | `Frequency`/`Frequencylinearized`；`plist`、`punit`。适用于线性或线性化谐波响应；偏置解与扰动解不可混淆。 |
| 特征值/模态 | `comsol_api_solver.51.66.html`、`51.23.html`；`comsol_ref_solver.36.025.html`、`36.122.html` | `Eigenvalue`；`linpmethod`、`linpsol`、`linpsolnum`、搜索范围/shift、返回模态数。特征频率的物理接口预设与通用特征值并非可任意互换。 |
| 参数扫描 | `comsol_api_solver.51.74.html`；`comsol_ref_solver.36.048.html`、`36.119.html` | `Parametric`；`pname`、`plistarr`、`punit`、`sweeptype`、`reusesol`、`keepsol`。区分指定组合、全组合和延续，记录每个参数元组及失败点。 |
| 多步数据传递 | `comsol_ref_solver.36.012.html` | **Using a Solution from Previous Study Steps**；分别指定求解变量的初值、未求解变量的来源；记录源 study/solution、时间/参数/模态、目标变量。 |
| 实际解位置 | `comsol_api_solver.51.08.html`、`51.10.html` | `getSize()`、`SolutionInfo`、`getSolnum`、`getISol`；内部/外部解编号及多网格解要按实际对象解释，不能假定“最后一个数组元素”就是目标解。 |

研究节点创建语法已在上述各页核实，例如：

```java
// 配置片段；stdTag/stepTag 必须替换为实际且无冲突的 tag。未执行求解。
model.study(stdTag).create(stepTag, "Transient");
```

不在此给通用容差、步长、搜索频率或扫描范围。研究允许启用/停用物理的 API 并不授予修改物理问题的权限；发生物理接口、边界条件或本构问题时返回建模侧。

## 网格：检查生成结果而不只看设置

| 问题 | 已核验来源（C/） | 约束 |
|---|---|---|
| 数量、局部统计、质量 | `comsol_api_mesh.49.026.html`、`49.027.html`、`49.028.html`；`comsol_ref_mesh.24.25.html` | `stat().selection()` 限定实体；记录单元类型/数量、质量量度、最小值/分布。全局数量相同不能单独证明网格相同，全局数量增加也不能证明目标区域已加密；需实际坐标/连接或局部尺寸与统计证据。 |
| 尺寸未生效 | `comsol_ref_mesh.24.86.html`；`comsol_api_mesh.49.099.html` | 重叠 Size 节点采用后出现者；自定义非默认 Size 的具体参数需启用。最小尺寸、曲率、窄域和相邻高维实体约束均可能影响结果；文档不保证所有生成单元严格满足尺寸设置。 |
| 配对面复制顺序 | `comsol_ref_mesh.24.49.html`；`comsol_api_mesh.49.061.html` | Copy Face 的源面须已网格化；目标面不可邻接已网格化体域；先完成相应面操作再体网格。此规则适用于所选复制操作，不要求所有配对面都用 Copy Face。不得为适应复制而擅自改几何。 |
| 曲面与高阶 | `comsol_api_general.47.23.html`；`comsol_api_mesh.49.028.html`；`api/com/comsol/model/ModelNode.html` | `component(...).sorder()` 是几何形函数；`curvedInterior()` 与内部曲面网格有关；检查物理离散阶次、几何阶次和 `curvedskewness`/`reldetjacmin`。不能把线性几何替换二次曲面产生的偏差算成单纯 h 加密结果。 |

已核验的只读 API 形式（tag 需来自模型，且网格必须已生成）：

```java
int count = model.component(ctag).mesh(mtag).stat().getNumElem();
double qmin = model.component(ctag).mesh(mtag).stat().getMinQuality();
double qmean = model.component(ctag).mesh(mtag).stat().getMeanQuality();
String measure = model.component(ctag).mesh(mtag).stat().getQualityMeasure();
String geometryOrder = model.component(ctag).sorder();
```

质量量度及适用单元类型需同时保存；没有跨问题通用的最小质量门槛。

## Windows 执行与恢复

来源：`C/comsol_installation.02.043.html`、`C/comsol_ref_running.38.31.html`（**COMSOL Commands on Windows**，batch 选项约第 895–1222 行）、`C/comsol_ref_environment.18.22.html`（**Keeping and Opening Recovery Files**）。

- 文档示例为 `comsolbatch -inputfile in.mph -outputfile out.mph -study std1`；它会求解，只能用于当前明确运行授权。`-batchlog`、`-np`、输入/输出与 study tag 按本次配置指定，不从历史记录继承资源值。
- `-continue` 表示继续；恢复文件可能在输出时间点、参数点、成功的非线性 Newton 迭代后更新。需实际核验保存位置及完整性，不把任意已保存 MPH 当作完整求解器检查点。
- **`-recover` 有重算回退：文档明确，恢复目录模型打开失败时会转而求解输入文件。** 因而不能把它包装为“只恢复且绝不重算”，也不能仅凭使用此参数声称可靠续算。
- 恢复需要当前授权及模型/脚本/参数/求解设置的匹配，还须检查实际时间、初始场、运动/变形状态、解来源和接续连续性。文档支持不等于本候选流程已验证。
- 直接参数数组调用，路径逐项传递；保留日志原始字节并明确解码。不得把 log/status 文件的旧内容当作本次成功证据。不要手工清理正在使用的恢复目录。

## 结果提取及跨物理场参考

`C/comsol_api_results.52.007.html`（数值结果）、`52.009.html`–`52.013.html`（解选择）、`52.049.html`（EvalGlobal）、`52.064.html`（Global）、`52.077.html`（IntVolume/IntSurface/IntLine）。具体数据集、表达式、实体、单位、坐标系、时间/频率/内外解及统计定义必须显式对应目标。

- `Global` 是 API 专用节点；`getData()` 布局为 `[expression][solnum][value]`，复数虚部使用 `getImagData()`，不能丢弃后宣称幅值/RMS。
- 积分节点 `getReal()` 默认每行包含各解编号的结果；`computeResult()` 不含参数列。单独保存时间/参数映射，避免把列顺序误认成扫描点。
- `dataseries` 的 average/integral/rms 等是对序列的变换；空间积分、时间平均、RMS 和峰值应分别定义。复数等效应力等非线性派生量不能普遍用实部、模长或除以根号二互换。

非电磁官方示例（只读查阅；本次未打开、复制或求解 MPH）：

| 模型 | 文档相对根路径 | 应用库相对路径 | 可借鉴判断 |
|---|---|---|---|
| 轴对称瞬态传热 | `com.comsol.help.models.mph.heat_transient_axi/heat_transient_axi.html` | `COMSOL_Multiphysics/Heat_Transfer/heat_transient_axi.mph` | Heat Transfer in Solids + Time Dependent；温度位置/时刻/单位及 NAFEMS 对照。案例几何、材料、温度和时间不是默认值；两情景的边界改变不属于本 skill 可自行执行的数值调整。 |
| 支架频率响应 | `com.comsol.help.models.sme.bracket_frequency/bracket_frequency.html` | `Structural_Mechanics_Module/Tutorials/bracket_frequency.mph` | 结构谐波响应及预应力；共振附近频率分辨率、相位/峰值/RMS；应力非线性派生量的统计定义。 |
| 支架特征频率 | `com.comsol.help.models.sme.bracket_eigenfrequency/bracket_eigenfrequency.html` | `Structural_Mechanics_Module/Tutorials/bracket_eigenfrequency.mph` | 模态符号可翻转、振型幅值无直接物理意义；预应力先稳态再模态，模型假设不能自行更改。 |

这些资料支持按需配置研究的工作方法；候选版本未提供通用且经实机验证的 COMSOL 求解/恢复适配器。
