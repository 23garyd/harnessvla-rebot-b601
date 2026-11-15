# B601 对照、恢复与运行证据

整理日期：2026-11-14。实现沿用 2026-09-01 的已提交代码；本目录收集已有 2026-08-28 试验，不是新增实验。

| 技术工作 | 实现 | 原始结果与文档 |
|---|---|---|
| ACT 与 harness 对照 | [harness](../../../b601/planner/harness.py)、[实机 I/O](../../../b601/planner/live_io.py) | [比较来源与汇总](comparison-summary.json)、[15 次计分试验结果](hardware/20260828_071714/results.json) |
| 失败检测、重试与恢复 | [执行保护](../../../b601/planner/io_support.py)、[逐次试验门禁](../../../b601/planner/trial_gate.py) | [第一次排查](hardware/20260828_074607/results.json)、[第二次排查](hardware/20260828_082005/results.json)、[trial 1 遥测](hardware/20260828_082005/trial_001.jsonl) |
| 实机失败示例 | 同上 | [trial 1 视频](hardware/20260828_082005/trial_001_agentview.mp4)、[视频来源及转换](hardware/20260828_082005/video-provenance.json) |
| 软件边界检查 | [测试](../../../b601/tests/) | [89 项通过、1 项跳过的输出](verification/2026-11-14-tests.txt) |

## 如何解释结果

计分对照中 baseline 与 harness 均为 12/15。harness 的 12 次成功全部在第一次策略尝试完成，没有 recovery-completed 成功；不能把 I 层的 +20 个百分点解释为恢复机制有效。baseline 数字核对自原有 [技术研究记录](../../../reports/harnessvla_b601_report.pdf) 第 10 页，本次未重新评分 baseline 原始数据；harness 数字则逐条核对本目录原始 JSON。

计分轮有 6 次恢复分支进入，随后两轮排查分别为 6 次和 4 次，合计 16 次，没有记录到恢复分支持物成功。这解释了原注册表部分条目按排查轮写 0/10、后续技术记录按三轮写 0/16 的统计范围差异；这些分支进入并不保证机械臂实际执行了下降与闭爪，未收敛时程序会拒绝继续。

`20260828_082005` trial 3 的原 JSON 为 `success`，原技术记录同时保留 operator 判 `fail` 的争议；此处保留原文件并明确未裁决，不把它混入 `071714` 的 15 次计分对照。该 trial 的遥测也已保存。

## 来源及附件范围

[来源回执](hardware/source-receipts.json) 记录复制出的结果和遥测哈希。视频保留完整 38.867 秒时序，仅缩小并重新编码；其 trial 1 结果为 `gave_up`。它不是恢复成功、危险中止或无线链路降级演示。源软件的精确历史运行状态不能仅由今天的 HEAD 推定。

本目录没有执行 Wi-Fi、Bluetooth、NearLink 对比，也没有共存、移动性、能耗或规模化实验。软件恢复与日志可以检查，无线比较结果仍缺失。固定臂拾放是已有实机用例，不自动构成两项代表性工业场景均已演示。

[implementation-commits.csv](implementation-commits.csv) 对应实际代码修改提交；[manifest.csv](manifest.csv) 校验全部技术附件。审批报告与发票不在本目录。
