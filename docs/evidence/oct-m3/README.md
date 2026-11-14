# B601 实机实现与技术证据索引

整理日期：2026-11-14。实现基线：`689526cdf4ec9126fec67f1a3017cb443893752f`。
本次整理新增技术索引、既有试验附件和检查记录，未改变控制程序、重新训练模型或新增实机试验。源代码已在基线提交中。

| 功能 | 实现 | 可检查的技术证据 |
|---|---|---|
| 观察、定位、抓取、验证、重试与放置 | [状态机](../../../b601/planner/harness.py)、[执行入口](../../../b601/planner/run_harness.py)、[实机 I/O](../../../b601/planner/live_io.py) | [实机试验附件](hardware/20260822_213019/)、[历史技术记录](snapshot-2026-08-25/b601_progress_log.md) |
| 视觉抓取验证与规划辅助 | [验证器](../../../b601/planner/grasp_verifier.py)、[感知](../../../b601/planner/perception.py) | [测试输出](verification/2026-11-14-tests.txt) |
| 有界执行与异常终止 | [实际执行保护](../../../b601/planner/io_support.py)、[实机执行路径](../../../b601/planner/live_io.py)、[通用安全驱动](../../../b601/driver/base.py) | [测试代码](../../../b601/tests/test_live_servo.py)、[安全测试](../../../b601/tests/test_safety.py)、[测试输出](verification/2026-11-14-tests.txt) |
| 状态反馈及每步日志 | [TickRecorder](../../../b601/planner/live_io.py) | [trial 1 遥测](hardware/20260822_213019/trial_001.jsonl) |
| 数据集与策略来源 | [数据记录快照](snapshot-2026-08-25/b601_dataset_card_168_episodes.md)、[当前实验注册表](../../../b601/registry/experiment_registry.md) | 原始数据和权重不包含在此目录，见下文边界 |
| 部署分工 | [部署技术说明](placement.md) | 已有分工与配置，尚无三类推理部署的成组实测结果 |

## 附件解释

[2026-08-22 实机记录](hardware/20260822_213019/results.json) 为完整五次试验结果；此处只附 trial 1 的完整时序视频及逐步遥测。trial 1 的原始结果为 `gave_up`，三次尝试后结束，不能作为任务成功的证据。

[视频](hardware/20260822_213019/trial_001_agentview.mp4) 从原始 155,260,459 字节文件缩小到 640 像素宽重新编码，未剪切时序、未添加动作。原始文件哈希已与版本库中的 [原始清单](../../../b601/registry/harness_trials_manifest.csv) 匹配。转换命令、原始哈希及附件哈希保存在 [来源记录](hardware/20260822_213019/provenance.json)。视频播放时长与结果记录的墙钟耗时不是同一指标，不应互相替代。

`snapshot-2026-08-25/` 是已有技术文档的字节级快照，描述当时的 168 episodes 数据及实验状态；不是把当前版本重新运行所得的结果。当前代码和历史证据分别标注版本与日期。

## 验证

[2026-11-14 输出](verification/2026-11-14-tests.txt) 记录所列 187 项无硬件测试通过，不代表完整测试套件、实机试验或降级演示通过。用仓库所需依赖环境执行输出中列出的命令。

本仓库同时有 `SafeDriver` 抽象与基于 lerobot 的实机路径；不能只凭通用驱动测试推断实际策略路径受到同样保护。此索引因此同时指向 `live_io.py`、`io_support.py` 和相关测试。

## 尚未由这些附件证明的内容

- 本次未提供新的物理机器人降级／拒绝动作演示；软件测试与普通试验录像不替代该演示。
- 尚无 robot-local、edge、hybrid 三类推理部署的成组评估记录。
- 168 episodes 原始数据与策略权重仍在原实验存储中；目录内的数据卡不等于可下载数据或模型。本索引不声称这些大文件已提交或可由外部审阅者取回。

[manifest.csv](manifest.csv) 给出本技术证据目录中每个文件的字节数、SHA-256 与来源。

[implementation-commits.csv](implementation-commits.csv) 将每项功能对应到实现文件、最后修改该文件的历史提交、完整基线中的代码链接和附件路径。历史实现提交与本次证据整理提交分别保留，避免把文档整理称作新增实现。
