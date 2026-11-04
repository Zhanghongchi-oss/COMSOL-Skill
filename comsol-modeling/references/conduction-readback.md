# 已验证问题的窄范围导热检查规则

适用：生成或修订**二维、标准各向同性固体导热**的建模/修改/独立检查源码时。它不是矩形模型模板；不提供尺寸、温度、材料值、实体号、容差、研究或求解配置。其他本构、维度或耦合须另查证。

使用 [共享检查片段](../assets/conduction-readback/ConductionChecks.java.inc) 和 [生成入口](../assets/conduction-readback/render.py)，避免在 Build、Modify、Check 中各自维护三份判断。

## 三项修复

1. 默认 Solid 的选择可被接口锁定。创建代码仅设已查证的本构来源，不对该默认节点调用 `selection().named/set/all`。读回先核对 `physics.geom()` 及物理/Solid/材料选择的 `geom()`、`dim()` 均绑定预期几何与二维域，再比较实际实体集合，并检查材料覆盖、激活及本构来源。相同实体编号可能属于不同几何，不能只比编号。集合符合只是覆盖检查，不证明空间位置正确；边界位置及额外覆盖关系须由任务断言验证。
2. `thermalconductivity` 的已证明读回等价形式仅为 `[k]` 或精确九分量 `[k,0,0,0,k,0,0,0,k]`。k 是本任务审核的表达式；不把未知长度、不同对角、非零非对角、空值或任意数组视为等价。`0.0`、代数变形及其他张量表示也不在此证据范围，先查证，不能放宽为“能转成数值即可”。同时核对实际 `from_mat/dommat/Standard/GlobalSystem`，不能孤立检查材料数组。
3. 只有精确 `LayerOpacity` 类型、实际 inactive，并已确认相关 PhysicalModelProperty 标志关闭及本构/厚度符合预期，才能接受该节点。未知类型和意外激活仍失败；读不到状态不能当 inactive。递归检查子特征。此规则不是允许在所有物理问题中忽略 inactive 节点。

读取异常直接中止该检查，调用方记录 failed/blocked 或明确 not_read，不能继续写 passed。当前片段只生成同一顶层类的方法，不生成嵌套类、Sink 接口或回调实例。显式记录函数应保存每条明细；`crRequire` 在调用记录函数后仍独立对 false 抛出，不能由只记日志的记录函数吞掉失败。

## 生成及三个操作的统一调用

在本任务新源码的唯一顶层类体内放置一行 `// @CONDUCTION_READBACK@`；模板提供明确的静态记录函数，必须无 throws 子句，签名为 `static void <名称>(boolean, String, String)`。默认名为 `recordConductionCheck`，也可通过 `--record-method ok` 指定已有函数。记录函数必须保存本任务真实检查明细，不能使用空实现来冒称检查已记录。生成器仅核对声明形状，不能证明记录函数语义。

```java
private static void recordConductionCheck(boolean passed, String name, String detail) {
    // 接入本任务已审阅的明细存储逻辑；不得使用空实现作为验收证据。
    recordCheck(passed, name, detail);
}
// @CONDUCTION_READBACK@

// 在任务专属检查函数中：
crCheck(model, componentTag, geometryTag, physicsTag, solidTag,
    materialTag, materialGroupTag, semanticDomainSelection,
    reviewedConductivityExpression, reviewedThicknessExpression);
```

所有参数来自当前任务；接口/本构/单位及二维厚度约定先审核。辅助片段不替代其他材料、边界/初态、几何位置、配对或目标量断言。

```powershell
python -X utf8 -B comsol-modeling/assets/conduction-readback/render.py --source <本任务源码模板> --output <新目录/同名Java文件.java> --record-method recordConductionCheck
```

上述新模板使用默认 `recordConductionCheck`；历史模板已有 `ok` 函数时才使用 `--record-method ok`。Python 接口相应为 `render(source, output, record_method="ok")`。输入必须是保留 marker 的模板，不能把已经展开的旧生成源码再次输入。旧模板中的 `ConductionChecks.check(十个任务参数, (a,b,c) -> ok(a,b,c))` 可直接输入当前生成器：只对选定记录函数的三参数原序直转形式自动改成 `crCheck(十个任务参数)`。调序、常量替代、代码块 lambda、其他回调方法均拒绝；不要求手改 Build/Modify/Check 三个生成文件。新模板直接使用 crCheck，不需要任何回调。

`crRequire/crIds/crExactIsotropic/crDisabled/crKnownFeature/crCheck` 是保留方法名。重复旧 helper、嵌套类型、匿名类、剩余 lambda、非类体 marker、block comment 中的假 marker、Java text block 和 recorder 的 throws 子句均不在此入口支持范围，必须先修订并审阅模板。该有限词法处理不是任意 Java 解析器或编译器，也不是权限沙箱。

输入源码与输出文件须分开，目标必须不存在；读取期间模板/片段变化即拒绝生成。生成器仅文本处理，不能编译、构建、执行或授予运行权。记录模板、片段、生成器、记录函数名、迁移调用数和生成后实际源码的哈希，并将实际执行源码纳入 runtime pins。三个操作使用同一片段，不在各输出副本继续手工维护不同版本。methodexec 的正式路径仍必须对最终生成源码做真实验证；编译成功、源码同等或退出零都不足以证明装载和模型通过。

| 操作 | 同一检查函数的调用点 | 额外不变量 |
|---|---|---|
| 新建 | 几何构建后、保存卸载后新加载的模型 | 任务专属几何/边界断言都执行；默认 Solid 不重选 |
| 修改 | 修改前、几何变化后、另存并重新加载后 | 保留源文件及哈希；受影响选择/材料/边界重新验证，最小修改，不无条件删除旧节点 |
| 独立检查 | 新进程加载已保存 MPH 后 | 只读；输入文件哈希前后相等；证据绑定实际文件，不继承“无 study/solution”等可能失效断言 |

三个调用点共享谓词不会使它们的证据共享：各自产生真实明细、各自绑定实际模型；没有运行时都保持 not_run。修改报告可同时包含来源模型与输出模型断言，不能整批改绑到新模型；当前模型的通过证据应使用对应输出上的独立检查。

## 查证与验证等级

依据只读历史目录 `validation/live-validation-20261101/modeling/sources-v05` 的 BuildSlab/CheckSlab/ModifySlab、`verification-summary.json` 及 `build-10`/`check-01` 检查记录；汇总指向 COMSOL 6.3 build 290 中验证副本的 232/117 项历史断言。`build-06` 暴露锁定选择，`build-07` 暴露标量读回，`build-09` 暴露 inactive LayerOpacity。原失败记录保留。

2026-11-02 `validation/live-candidate-validation-20261102` 真实记录进一步发现：原嵌套 `ConductionChecks/Sink` 在 methodexec 装载时失败，build-01 未产生模型/报告；build-03 使用完整 JAR 的 -dev 尝试仍失败，**-dev 不是已验证修复**。原日志和失败状态保持不变，runner 的 pending_evidence 不能升级为 passed。

历史 `create_single_class_bridge.py` / `sources-single-class` 验证副本去掉嵌套类并直接连接 ok 记录函数，新建/独立检查/修改/再次独立检查为 244/123/367/123 条通过；该事实仅属于已散列的桥接源码和该单域案例。修改的 367 条包含来源断言，最终模型当前检查是独立 123 条，不可批量换哈希。InspectModel 两次盘点各 1694 条、0 读取错误也不替代物理断言。

当前正式生成器已将同类方法和明确记录接口纳入单一维护源。34项离线测试验证三个历史 marker 模板经最终生成器输出的完整 Java token 与审阅桥接源码相同（包括谓词、读回、字面值、抛错、保存卸载重载调用），并覆盖迁移和拒绝路径；离线等价本身不证明真实装载。

2026-11-02 获当次四阶段授权后，`validation/modeling-single-class-repair-20261102/preparation/attempts/candidate-02` 使用最终正式 renderer（SHA-256 `603ad0f700e378e66dd525442ae37fb1877284366b27cebfd2bf2312ccde1ba3`）、片段（`1fb1a0403a4acb593c8bf2e6a0e8ae4130998834dec2c2fe609d6fa238819ed7`）和正式 Invoke-ComsolJava 入口，完成 Build244、独立Check123、Modify367、独立Check123。三份源码未经桥接手改，实际仅产出各自顶层class；逐项检查、源文件不变、另存、保存卸载重载、独立进程加载均有原始证据，详见该修复目录 `independent/live-review.json`。这补充了最终候选的真实编译与methodexec证据，不改写历史失败。367包含源模型断言，修改后文件只绑定其独立123项。

此轮未重新运行全面InspectModel。基准交接清单保留参数/选择的partial及坐标系/目标量/初态节点的not_inspected，总体structure仍not_run；窄范围L-only修改审查通过不能当作求解就绪。模型及class/cache按授权清理后，日志与哈希是历史检查证据，不能当作当前文件仍存在。

这些证据不推广到其他物理接口或任意多域模型，不将夹具参数、编号、资源限额或误差阈值变成默认。真实测试后按当前任务要求清理本次生成 MPH/class/JAR/私有缓存，保留源码、原始日志、断言、哈希与清理回执；已清理模型的历史哈希不能当作当前文件验证通过。

几何身份 getter 已核对本机 6.3 Java API：`physics/Physics.html#geom()` 返回物理接口所属几何；`AbstractSelection.html#geom()` 返回选择几何或全局 null，`#dim()` 返回最大实体维度或 -1。历史 inventory-03 的 ht、solid1、mat1 选择维度均为 2。跨几何同编号反例仅是离线模拟，不代表双几何 COMSOL 模型实测。
