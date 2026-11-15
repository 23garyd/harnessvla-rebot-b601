# Technical recommendations and follow-up engineering for physical robot control

Existing evidence: [comparison and recovery summary](../nov-m4/comparison-summary.json), [implemented protection path](../../../b601/planner/io_support.py), and [experiment registry](../../../b601/registry/experiment_registry.md).

- Retain per-step execution speed/delta safeguards and per-trial geometry gates; ordinary success videos cannot replace fault-rejection demonstrations. Check SafeDriver and the actual lerobot policy path separately.
- Data distribution, camera stability, and operating protocols are part of performance attribution. The overall B601 v2 comparison is tied; do not attribute differences between strata to recovery benefits.
- Online control and latency-sensitive safety states should have local constraints; local execution and remote training describe the existing division of work, rather than comparison results for three inference deployment modes.
- Resolve the recovery branch perception/action convergence issues and disputed scoring before deciding whether to expand experiments; new parameters should have matching data, software versions, and results. Do not infer historical states from a later HEAD.
- Wireless technology selection still requires Wi-Fi/Bluetooth/NearLink measurements using the same data stream. No unmeasured rankings, energy consumption figures, or recovery latency figures are provided.

Follow-up engineering: add physical safety rejection and recovery demonstrations; design same-task comparisons for actual robot/edge/hybrid inference configurations; provide retrievable data/model archives; pin all vendor dependencies and then rebuild on a clean machine. These are follow-up items, not completed work or new acceptance commitments.
