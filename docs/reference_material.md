# Reference material

## RPent (the released HarnessVLA harness)

**Not vendored here.** It is an 11 MB pinned upstream clone that the B601
track reads for architecture, and runs nothing from. The simulation repo holds
it at the pin used for the reproduction:

    repo:   github.com/23garyd/harnessvla-sim-reproduction
    path:   RPent/
    pin:    6e4ba1805a459d74ad53569e833bae7ae2c59985

What the B601 plan asks you to read (Day 1):
- `RPent/robots/libero/` — the reference implementation of the harness loop
- `RPent/docs/` — architecture notes and diagram
- the HarnessVLA paper, arXiv:2607.08448

### The two files worth studying closely

`RPent/robots/libero/prompts/system.py` — how the planner is told to observe,
consult memory, and record what it read. Note it names the camera views
directly (`agentview`, wrist) ~75 times: the prompt is part of the camera
contract, not just the code.

`RPent/robots/libero/tools.py` — the primitive surface, and how a **scene +
wrist** camera pair is handled: separate RGB, metric depth, and depth→world
XYZ maps per camera, plus high-res variants. That two-camera structure maps
1:1 onto a D435-fixed + D405-wrist setup, which is why that hardware choice is
architecturally cheap here.

## Simulation track

`docs/sim_findings_that_transfer.md` in this repo distils the measured results
that constrain design decisions here. Read it before Day 16 (verification) and
Day 17 (memory) — several of its findings are the difference between a design
that works and one that reproduces a known failure.

Full record: `github.com/23garyd/harnessvla-sim-reproduction`, in particular
`track/registry/` (experiment registry, risk log, per-day progress with result
tables) and `track/report/reproduction_report.md`.
