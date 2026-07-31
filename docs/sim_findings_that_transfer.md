# What the simulation track learned that applies to B601

Source: `23garyd/harnessvla-sim-reproduction` (HarnessVLA reproduction on
LIBERO-Pro, Days 1–12). These are *measured* results, not intuitions, and each
one has a concrete consequence for a design decision here. Cited so the B601
work starts from them rather than rediscovering them on hardware, where a
mistake costs a demonstration session instead of a rollout.

## 1. The harness wins at the perception seam, not the motor seam

Gains concentrated where the perturbation broke *perception* (object
relocated, fixture swapped). Where it lived inside the policy's motor program,
the harness had no lever — a redirection cell went 1/5 → 1/5 because the
frozen policy re-enacted a memorised pick-and-place and dropped the object,
and no amount of planning fixed that.

**For B601:** the planner's value is staging, verification and re-grounding.
Do not expect it to repair a bad ACT grasp trajectory. If the Day-12 policy is
weak in a way that is *motor*, retraining (Day 13) is the fix, not the harness.

## 2. Successes complete on analytic primitives, and the VLA is invoked once

10 of 11 harness successes fired the success predicate during an **analytic**
primitive (release/move), with a median of **1** policy invocation per
success. Failures invoked the policy 3× more.

**For B601:** the frozen ACT primitive should be a *grasp specialist* called
sparingly, with transport and release done analytically. Repeated policy calls
correlate with failure, so "invocations so far" is a usable early-warning
signal for the retry controller.

## 3. Cached reference coordinates act as confirmation anchors

The one cell where the harness did *worse* than the raw policy: released
memory contained a seed-0 basket coordinate, and planners selected the
perception estimate that **matched the cached absolute** over the accurate one
their own tools returned. Failing releases were +0.078–0.082 m off-centre in
x, outside the container footprint. Grep-based audits could not see it — the
stale number never entered an action, it biased estimator *selection*.

**For B601 (Day 17, memory):** store *relative* offsets and procedures, never
absolute workspace coordinates. Memory must not be able to override current
perception. This is also the physical analogue of a drifted camera mount, and
it is why calibration is pinned.

## 4. Policies report grasps they did not make

`feedback_pi0_false_positive_lift`: the policy signalled a successful lift
when it had not grasped.

**For B601 (Day 16, verification):** independent verification is mandatory,
and it must not consume the policy's own success signal. The wrist camera is
the right sensor for "is the object actually between the fingers"; a fixed
camera at 0.8 m cannot resolve it. `MockDriver(grasp_succeeds=False)` induces
empty grasps for testing the verifier with no hardware.

## 5. Budget exhaustion is not task failure — report them separately

The Day-12 memory ablation's entire positive result came from three runs that
hit a wall-clock planner timeout at 46–51 turns, *below* the turn cap and
still working. Folded into a success rate they read as "memory enables
grounding"; separated out they read as "memory saves deliberation time" — a
different and much weaker claim.

**For B601 (Day 18 comparison):** report safety aborts, timeouts and genuine
task failures as distinct terminal reasons. A retry-enabled success rate that
silently absorbs safety aborts is not measuring what the gate claims.

## 6. Ablation conditions leak through channels you did not enumerate

Hiding memory required three attempts. The planner found an in-repo stash with
a repo-wide `find`; a download cache leaked note *filenames* via `.lock` files
and silently contaminated two runs that had already been accepted and
published; the teardown then failed and left the assets hidden, while the
integrity check reported "clean" because it was structurally blind to that
directory.

**For B601:** any held-out or ablated condition needs an explicit, tested
detector, and each guard should state in its header what it does **not**
cover. Held-out placements are the analogue here — leakage must be checked
automatically at the Day-10 gate, not asserted.

## 7. Half the cells carried no signal

4 of 8 sim cells came back `direct == harness`, and 3 of 4 ablation cells
showed no effect at all. Much of the matrix was measuring nothing.

**For B601:** pilot the variation matrix before committing to full collection
(the plan's Day-6 pilot study does exactly this). A cell where both arms
saturate cannot show an improvement, and the Day-18 gate needs cells with
headroom to move.
