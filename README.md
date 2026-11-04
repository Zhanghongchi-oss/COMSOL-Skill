# COMSOL Modeling & Compute Skills

两个通过脚本协作的 COMSOL Skill。发布版本：v5；本公开分发包整理于 2026-11-04。

| 目录 | 职责 |
|---|---|
| `comsol-modeling` | 几何、材料、物理场、耦合、物理边界与初值，以及建模检查 |
| `comsol-compute` | 网格、研究、求解、保存场接续、已有解提取及数值验证 |
| `handoff-review` | 共同 2.0.0 协议的维护源快照；不是第三个 Skill |

## 环境与配置

已实测环境为 Windows、COMSOL 6.3 build 290、Python 3.14、Windows PowerShell 5.1 / PowerShell 7。需要对应物理接口的有效 COMSOL 许可。本包不包含 COMSOL 软件。

保留每个 Skill 的完整文件夹，不能只复制 SKILL.md。将需要的 Skill 文件夹放入使用者配置的技能目录；共同协议的运行副本已经包含在两侧。

使用前修改 `comsol-modeling/assets/environment.local.json`：`comsol_root` 当前是示例路径，须替换为真实安装目录；`history_root` 为空，公开包不依赖作者的历史资料。可使用建模入口的 `-ConfigPath` 指定单独的本地配置，使用 `-Python` 指定已核实的 Python 解释器。计算的路径、输出目录和资源限制按当前任务显式准备。

## 使用示例

```text
使用 $comsol-modeling，按以下需求创建模型，检查保存后的模型并交付 model-manifest.json：……
使用 $comsol-compute，接收这份 model-manifest.json，先准备计算方案：……
```

运行前明确本次是准备、求解、接续还是仅提取，以及资源预算。准备和验收不构成真实运行授权；仅提取缺少已有解时不得自动求解。计算侧不得通过更改几何、本构、物理接口、边界或物理初值来获取收敛。

## 验证范围

v5 已完成两个小型模型（瞬态导热、温度反馈电热）的建模、交接、求解和正式仅导出，导出与独立读回的数值逐项一致；缺解导出负例被拒绝。共同协议完成 75 项正负例符合性检查。v4 有保存场接续证据，但不等于恢复 BDF 历史或崩溃恢复，v5 未重新执行真实接续。

具体范围见 `comsol-compute/references/live-validation-v5-20261103.md` 及各 Skill 的能力说明。任意物理场、大型模型和所有版本组合均未全面验证。案例参数、误差阈值及资源预算不是通用默认值。

此分发包保留已验收的执行源码、SKILL.md 和共同协议；只泛化环境配置及历史资料定位。没有为打包重新启动 COMSOL。原始验收 JSON、机器路径、运行日志、模型和缓存不发布；文档中的历史证据路径仅是原记录的定位信息，并非本仓库中的可读文件。完整开发回归套件不在本分发包中，不能把此包当成完整开发工作区。

## 上传与维护

解压后将本 README、两个 Skill 目录、handoff-review、.gitignore 和 package-manifest.json 一起放入仓库根目录。ZIP 也可作为发布附件。修改配置后不要提交个人路径；源码变更应另建版本并复验。package-manifest.json 记录此发布包各文件的 SHA-256；修改任何文件后应重新生成清单。

## 许可证

作者尚未指定开源许可证。本包未擅自加入 MIT、Apache 等授权；公开可见不代表已授予开源许可。正式开源时由权利人确定许可证，并核对涉及第三方示例的权利。本项目不包含或授予 COMSOL 软件许可。
