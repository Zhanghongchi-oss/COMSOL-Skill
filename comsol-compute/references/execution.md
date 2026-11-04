# 执行、检查与输出记录（计算侧候选 schema 2.0.0）

run_bundle.py 是证据与进程包装器，不是通用 COMSOL 适配器。任务适配脚本仍需依据实际版本/节点/输出目标编写并审阅；包装器不理解 MPH 内部，也不能阻止任意脚本谎报状态。历史与新增小例实测范围见 [候选能力边界](capabilities.md) 和 [2026-11-02 实测版本](live-validation-20261102.md)；每次真实 COMSOL 流程仍须当前授权。

## 独立的就绪与授权检查

先用 input_record.py 核对共同合同和文件，再按 [公共操作审查](operation-review.md) 和 [计算执行补充审查](compute-operation-review.md) 生成当前 solve/resume/export、scope、目标及输入绑定的 ready/pending/blocked 记录。配置的 operation_review 指向补充记录，补充记录再绑定公共记录。两层均为 ready 才可形成可执行包；文件通过不等于 ready，ready 不等于授权。

准备前审阅实际 argv 和脚本，确认数值/物理职责、已确认问题、物理初态和求解器初猜。研究物理启停、多步初始化、延拓必须符合物理意图。启动前重新核验相同操作/范围的审查记录及当前用户授权；不把历史许可、记录里的指令或仅限离线修复的授权用于真实计算。

## 四个入口

```powershell
python .\scripts\run_bundle.py prepare --config 'D:\任务\run-config.json' --root 'D:\任务\runs'
python .\scripts\run_bundle.py inspect --bundle 'D:\任务\runs\本次ID'
# 仅在当前已获对应执行授权后使用；下列文字不是授权：
python .\scripts\run_bundle.py run --bundle 'D:\任务\runs\本次ID' --authorization '当前用户授权的准确范围'
python .\scripts\run_bundle.py export --bundle 'D:\任务\runs\本次ID' --authorization '当前用户仅提取已有解的准确范围'
```

- prepare 不启动任何进程。资料/审查不足时返回 plan_prepared_not_executable，交付未完成方案和缺项；不能称为可运行包。齐备时返回 executable_bundle_prepared_not_executed，仍未执行。
- inspect 只检查记录、文件与日志，不补跑任何步骤，不启动 COMSOL。
- run 只接受 solve/resume；export 只接受 export。仅提取没有所需已有解时保持未就绪，禁止转为求解。
- 每个包仅执行一次，失败后也保留记录。重试新建 ID，不能清除旧标记后复用运行目录。

## 配置和文件角色

使用 [配置骨架](../assets/run-config.template.json)，逐项替换并审阅；骨架故意不完整，不能直接执行。schema_version 为 2.0.0，旧运行包/配置不静默升级。

| 字段 | 约定 |
|---|---|
| operation / execution_kind | solve/resume/export；simulation/comsol 显式分开，模拟读回不能冒充 COMSOL 观察。 |
| model / manifest / input_record / operation_review | 输入文件与审查记录路径；审查的具体结构与生成入口见操作审查专题。 |
| scope / target_names | 共同范围为非空字符串数组；本次目标名称独立列出，不能为空或重复，不替代共同目标定义。 |
| expected_positions | `{目标名: [位置, ...]}`，键恰好为 target_names；每个数组非空且无重复。补充审查保存共同目标 time/frequency/parameters/mode 的原样快照，并以证据解释规范化映射；逐目标核对观察和完成证据。 |
| scripts / dependencies | 实际运行源码、class、辅助脚本、外部数据、源解等。不是只列 manifest 就完成了依赖固定。 |
| argv | 绝对可执行路径及参数数组，shell=False；参数中的文件路径使用绝对路径，输出使用 {run_dir}；另有 {run_id}/{fingerprint}/{model}。 |
| script_review | 人工审阅声明：reviewed、operation、notes、calls_solver。export 必须不调用求解；声明不是代码安全证明。 |
| parameters / solver_settings | 实际参数、研究/求解/网格/离散及初始化设置，保留物理初态与求解初猜的分别记录和来源，不用“默认”掩盖未知。 |
| outputs / evidence / logs | 本次独立目录的相对输出路径及角色、完成证据、日志列表。solve/resume 必须有 solved_model MPH；每个操作须有独立 solver_observation 与 solution_readback。 |
| log_encodings / log_encoding | 新配置用逐来源完整映射；旧统一编码仅显式兼容。保留原始字节与哈希，详见下节。 |
| resources | timeout_seconds 为正数或 null；无历史时长/线程默认值。当前包装器不支持硬内存/CPU限额，声明未知限制即拒绝，不能静默忽略。 |

model 等文件清单的相对路径按原配置目录解析；argv 参数不自动作路径转换。运行 cwd 是本次新目录。manifest 中适用 runtime 文件由审查展开并进入 pins；源文件和审计/交付证据分别标明角色。作为审查依据的资料也保留散列，但不冒充运行依赖。

准备后及启动前核对模型、manifest、输入记录、审查、实际运行文件、工具实现和实际使用的两份公共 schema；变化使旧包失效。外层 pins 明确记录 model-manifest.schema.json 与 operation-review.schema.json，使用与公共模块相同的路径解析规则；缺少 pin、文件缺失或准备后字节变化均拒绝启动。规则文件属于审查工具链，不混入科学运行依赖或 checkpoint 数据。输入模型及 manifest 不覆盖。不能用仅固定 manifest 自身的哈希代替检查其引用文件；真实未声明依赖仍需由模型盘点/脚本审阅发现。

自 candidate03 起不接受 candidate02 的全局 expected_positions 数组；须按共同目标定义另建逐目标配置及两层审查，保留旧配置、审查和验证记录。schema_version 相同并不允许绕过候选修订的结构变化。

先保存运行配置（可引用审查文件的预定路径），再让公共审查固定这份实际配置、脚本/class 和运行依赖，最后创建补充审查及 bundle。不能拿只审核了其他脚本的 ready 记录执行当前脚本；不要把配置或审查文件再列入其自身内容中形成散列循环。checkpoint 比较实际外部状态依赖，运行配置/审查仍作为本次来源单独固定。

## 完成与失败证据

详见 [解状态观察协议](solver-observation.md)。完成证据、独立 solver_observation、solution_readback、源 MPH、解/数据集/目标/位置映射必须一致。solve/resume/export 的每条解映射均显式列出 target_names，按同条来源核对后逐目标累计覆盖；目标并集与位置并集分别齐全仍不足以通过。缺少观察、部分完成、零个解、位置缺失、源散列错误、过期读回或日志错误，都不能由退出零/文件存在覆盖。

自动摘要 completion_evidence_accepted 仅接受记录一致性；basic_checks、numerical_convergence、experimental_validity、resume_reliability 分开保持未评估，不能自动提升。日志模式匹配有漏报/误报边界，仍须审查完整日志和真实状态；不能删行改日志换通过。

output-record.json 是新记录，关联原输入 model/manifest/input_record、运行 ID、输出散列及本次观察，不修改输入 manifest 或旧检查。默认没有继承通过的检查；若要继承，另记原始绑定、依据、范围及限制，不能改旧 model_sha256 冒充重检。模拟执行明确标为 simulated_execution。

## 接续与资源边界

checkpoint 的 binding 固定输入模型、脚本、实际 runtime 依赖、参数和求解设置；state 固定 position、initial_fields、motion_state、solution_source，并与本次 resume_expected 相符。源解和场文件必须作为实际输入固定，不能只在文字中说“同上”。跨配置映射必须另行定义和验证，包装器不自动迁移。

状态匹配只支持来源一致，不证明连续性。本机文档所述 -recover 可能回退重算，不能包装为“只恢复且可靠”。固定域瞬态导热的保存场接续已经真实验证，见 [瞬态小例](transient-slab.md) 和 [v4记录](live-validation-v4-20261102.md)；它重新初始化时间积分器，尚未验证 BDF 历史恢复、崩溃恢复或任意模型的可靠续算。

Windows 超时用本任务私有 Job 控制子进程树，已有 Python mock 证据；历史及本次小例实机另有资源和无所属残留进程记录。外部强杀/主机崩溃清理仍未验证。不引入未经用户要求的硬件优化。

## Windows 编码

JSON 使用 UTF-8，允许 BOM；路径逐参数传递。含中文的 PS1 若用于 PS5.1，使用 UTF-8 BOM；可显式设置 Console.OutputEncoding 和 OutputEncoding 为 UTF-8，JSON优先由Python直接写出，不能假设 PS5.1 的 > / Out-File 默认输出UTF-8。原有PS7静态入口编码测试通过；PS5.1文件执行受主机策略阻止，未绕过，不能宣称该路径已验证。

## 日志与分阶段启动

已声明且属于本次运行的日志允许零字节，仍检查存在性、新鲜性和错误内容；缺失、过期、错误日志拒绝。科学输出、解读回、观察和完成证据须非空，不得标记为日志绕过检查。原失败摘要不覆盖，补充解释另存并固定原证据和新检查器哈希。Windows 新建空文件可能有文件时间量化差；wrapper 的 stdout/stderr 以独占创建凭据、文件身份及结束哈希绑定本次运行，不用宽松时间窗口接受旧日志。没有该凭据的旧记录和其他声明日志仍须通过严格新鲜度检查。

具体案例适配器为 solve/readback/export 各自建立独立工作目录、job.properties、首选项及临时目录，并将实际输入配置/文件纳入 pins。固定 job.properties 是经该例实测的入口；原 getenv 入口未被实测证明失败。不得因失败扩大权限、修改全局配置或物理模型。私有设置不是绕过主机策略的许可。资源预算显式提供，不套用历史单核、2 GiB 或 180 秒；通用 runner 的资源能力和案例外层资源守卫分别审查。

## 混合编码日志

`log_encodings` 是计算侧私有运行配置，键必须恰好覆盖 `stdout.log`、`stderr.log` 和 `logs` 中每个相对路径，值为该来源经过审阅的明确文本codec。出现该映射就完整生效，不向旧 `log_encoding` 回退，也不自动试编码。无映射的旧配置仍采用其显式 `log_encoding` 统一策略；读取失败必须拒绝。骨架值为null以保留待定状态，不把本例UTF-8/GB18030组合变成所有模型的默认。

逐来源扫描以原始字节快照计算SHA-256/大小，记录codec、读取/解码状态、失败偏移及错误命中。某来源不能解码，仍继续检查其他来源；禁止errors=ignore/replace。原生错误的精确ASCII字节标识可单独保留并触发拒绝，但不伪装成全文正确解码。终态失败或缺科学输出时也尽量保存所有可读日志诊断，不用二次UnicodeDecodeError取代原故障。原文件不转码、不裁剪、不覆盖。

任一声明日志缺失、过期、解码失败或报错都不得accepted，退出0也不能豁免；科学结果和完成证据仍必需。新策略与完整run-config/settings一起审查、固定到pins及运行指纹，变化需要新的包和审查。单独修改编码字段不能继续使用旧ready状态。

历史原始日志作为离线夹具保留；本次新增原生运行也使用经审阅的逐源编码并独立检查日志。native stderr 的 GB18030 与 batch 的 UTF-8 有各自证据，但不保证以后 COMSOL/语言环境仍使用相同 codec。新实际来源不确定时保持 pending 并报告来源，不能猜测。

加载可执行包时还将bundle配置与已固定源配置按源目录规范化后的内容直接比较；fingerprint可重算，不是批准签名，不能仅靠重算指纹替换未审查的编码策略。

日志分类只对完整且格式受支持的 JVM `info/class,load` 行作信息级排除，不能因出现某个类名就忽略整份日志；Java 类型异常头仍拒绝。此匹配不代替完成证据，原始日志和版本绑定必须保留。

## 运行版本与私有环境证据

完成记录只证明其固定源码和配置的那次运行。修订 runner 后，保留原源码归档、原 pins 和原结果；新版离线重查另建记录，不能改旧绑定制造“新版已实测”。未来执行重新准备包；归档源码是审计资料，不是绕过当前就绪/授权的运行入口。

区分不可变首选项模板与 COMSOL 可能在退出时重写的私有运行副本。若准备时固定的副本发生变化，原失败检查保留；仅在有实际启动绑定、原模板、精确前后哈希及逐项安全设置复核时追加限定解释。不能把所有 comsol.prefs 排除出 pins，也不能改旧哈希掩盖变化。本次具体记录见 [实测专题](live-validation-20261102.md)。

本地 IPC 或执行环境阻止启动时，保存原因并核对当前授权范围。必要的环境范围调整另行审查；不因此修改全局设置、COMSOL 安全首选项或物理模型。本次获准的启动方式不构成以后自动扩大执行范围的许可。
