#!/usr/bin/env python
"""Staging v4: grasp anchored to the end of the first sustained gripper-OPEN
run. Gripper convention (measured on this rig): LOW = closed, HIGH = open.
Episodes start closed (~4-25), the operator opens (~250-270) during the
reach, closes onto the block (stalls at the hold value, ~150), and opens
again at release. v3 mistook the first half-open crossing for "closure
onset" — an anchor that was CONSISTENT (good LOO) but sat mid-reach,
46-122 degrees short of the pre-grasp pose in 147/168 episodes.

t_grasp = last frame of the first run of >= 5 consecutive frames with
grip >= OPEN_THRESH: the gripper is fully open directly over the block and
starts closing. Staging pose = state K=10 frames (0.3 s) earlier — measured
sweep k in {0..30}: consistency and LOO are flat for k <= 20 and degrade
by k=30 (descent speed varies by episode, so far-back offsets decohere).

Two measured facts shape the rest (2026-08-14):
- wrist_roll at grasp tracks the block's RANDOM orientation, not its
  position (neighborhood spread med 20 deg, max 101 deg), and the block's
  agentview minAreaRect angle does NOT predict it (r=-0.2, residuals no
  better than a constant). Roll is therefore NEUTRALIZED to the corpus
  median in every stored pose; orienting the wrist is the frozen policy's
  job. The consistency filter and LOO accordingly use the POSITIONAL
  joints (pan, lift, elbow, wrist_flex) only.
- States come from the parquet tables (no video decode); only the
  block-pixel lookup decodes agentview frames."""
import sys
sys.path.insert(0, "/home/demo/Public/harnessvla-rebot-b601")
import cv2
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from b601.staging.table import StagingTable

OPEN_THRESH = 210.0   # midway between hold (~150) and full open (~270)
MIN_OPEN_RUN = 5      # frames; rejects single-frame blips
HOLD_RANGE = (40.0, 210.0)   # sane hold values for the one 40 mm block
K_BEFORE = 10         # frames before closure onset (see module docstring)
ROLL_DIM = 5          # wrist_roll index in the state vector
POSITIONAL = slice(0, 4)     # pan, lift, elbow, wrist_flex

ds = LeRobotDataset("local/b601_train_v2",
                    root="/home/demo/Public/harnessvla-rebot-b601/datasets/b601_train_v2",
                    tolerance_s=0.04)
eps = ds.meta.episodes
n = ds.meta.total_episodes
states = np.stack([np.asarray(s) for s in ds.hf_dataset["observation.state"]])

def agent_red(idx):
    try:
        img = (ds[int(idx)]["observation.images.agentview"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
    except Exception:
        return None
    hsv = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 55, 90), (14, 255, 255)) | cv2.inRange(hsv, (168, 55, 90), (180, 255, 255))
    mask[:60, :] = 0
    cnt, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
    best = max((i for i in range(1, cnt) if stats[i, cv2.CC_STAT_AREA] >= 250),
               key=lambda i: stats[i, cv2.CC_STAT_AREA], default=None)
    return cents[best] if best is not None else None

def grasp_anchor(grip, merge_gap=10):
    """Frame where the first sustained open run ends (closing onto block).
    Runs separated by <= merge_gap frames are MERGED: v2 ep34 showed a
    6-frame trigger flutter splitting one open phase into two runs, which
    would anchor the grasp mid-flutter."""
    runs, run = [], 0
    for t, o in enumerate(grip >= OPEN_THRESH):
        if o:
            run += 1
        else:
            if run >= MIN_OPEN_RUN:
                runs.append([t - run, t - 1])
            run = 0
    if run >= MIN_OPEN_RUN:
        runs.append([len(grip) - run, len(grip) - 1])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    if not merged:
        return None, None
    return merged[0][1], merged[0][0]

points, poses, poses_deep, epids, skipped = [], [], [], [], []
holds = []
for ep in [e for e in range(n) if e not in (75, 85, 160, 162)]:
    a, b = int(eps["dataset_from_index"][ep]), int(eps["dataset_to_index"][ep])
    grip = states[a:b, 6]
    t_grasp, t_open = grasp_anchor(grip)
    if t_grasp is None:
        skipped.append((ep, "no sustained open run")); continue
    g_hold = float(np.median(grip[t_grasp + 10:t_grasp + 60]))
    if not HOLD_RANGE[0] <= g_hold <= HOLD_RANGE[1]:
        skipped.append((ep, f"hold value {g_hold:.0f} out of range")); continue
    p = None
    for f in (0, 15, 30, 45):
        p = agent_red(a + f)
        if p is not None:
            break
    if p is None:
        skipped.append((ep, "no block")); continue
    stage_i = max(0, t_grasp - K_BEFORE)
    points.append((float(p[0]), float(p[1])))
    poses.append([float(v) for v in states[a + stage_i]])
    poses_deep.append([float(v) for v in states[a + t_grasp]])
    epids.append((ep, t_grasp))
    if (ep + 1) % 40 == 0:
        print(f"...{ep + 1}/{n}", flush=True)
    holds.append(g_hold)
print(f"extracted {len(points)}; skipped {len(skipped)}: {skipped}", flush=True)
H = np.array(holds)
print(f"hold values: min={H.min():.0f} p5={np.percentile(H,5):.0f} "
      f"med={np.median(H):.0f} p95={np.percentile(H,95):.0f} max={H.max():.0f}")

# neighborhood consistency filter — positional joints only (roll is
# orientation-driven and legitimately disagrees between neighbors)
P = np.array(points); Q = np.array(poses)
keep = []
dropped = []
for i in range(len(P)):
    d = np.hypot(P[:, 0] - P[i, 0], P[:, 1] - P[i, 1])
    nb = np.nonzero((d < 40) & (d > 0))[0]
    if len(nb) < 2:
        keep.append(i); continue                 # too sparse to judge; keep
    med = np.median(Q[nb, POSITIONAL], axis=0)
    dev = float(np.abs(Q[i, POSITIONAL] - med).max())
    if dev <= 15.0:
        keep.append(i)
    else:
        dropped.append((epids[i][0], round(dev, 1)))
print(f"consistency filter: kept {len(keep)}, dropped {len(dropped)}")
if dropped:
    print("dropped (ep, max positional dev):", dropped)

pts = [points[i] for i in keep]
ps = [list(poses[i]) for i in keep]
roll_neutral = float(np.median([p[ROLL_DIM] for p in ps]))
for p in ps:
    p[ROLL_DIM] = roll_neutral
print(f"wrist_roll neutralized to corpus median {roll_neutral:.1f} deg")

errs = []
for i in range(len(pts)):
    t = StagingTable.fit(pts[:i] + pts[i+1:], ps[:i] + ps[i+1:])
    try:
        pred, _ = t.query(*pts[i])
    except Exception:
        continue
    errs.append(np.abs(np.array(pred[:4]) - np.array(ps[i][:4])))
E = np.stack(errs)
print("\nLOO error after filtering, positional joints (deg):")
print("  median:", [round(float(v), 1) for v in np.median(E, axis=0)])
print("  p90   :", [round(float(v), 1) for v in np.percentile(E, 90, axis=0)])
print("  max   :", [round(float(v), 1) for v in E.max(axis=0)])

table = StagingTable.fit(pts, ps)
for i, (hx, hy) in enumerate([(390, 260), (460, 260), (425, 290), (390, 320), (460, 320),
                              (280, 260), (330, 380), (250, 410), (450, 410), (300, 190)], 1):
    tag = ("H" if i <= 5 else "I") + str((i - 1) % 5 + 1)
    try:
        _, d = table.query(hx, hy)
        print(f"  {tag}: {d:.0f}px answerable")
    except Exception as e:
        print(f"  {tag}: REFUSED {e}")
table.write("/home/demo/Public/harnessvla-rebot-b601/b601/setup/staging_table.json")
print("TABLE v4 WRITTEN")

# DEEP table: pose AT closure onset (k=0), for retry attempts — after a
# near-miss the retry stages with the fingers essentially at the block,
# leaving the policy minimal room to drift (probes: the policy continues
# from every funnel depth). Same kept episodes, same neutral roll.
ps_deep = [list(poses_deep[i]) for i in keep]
for p in ps_deep:
    p[ROLL_DIM] = roll_neutral
StagingTable.fit(pts, ps_deep).write(
    "/home/demo/Public/harnessvla-rebot-b601/b601/setup/staging_table_deep.json")
print("DEEP TABLE WRITTEN")

# visual spot-check: wrist view at the new anchor should show the block
# between the open fingers, directly below
OUT = "/tmp/claude-1000/-home-demo-Public-harnessvla-rebot-b601/abf8fe42-e843-4b14-8367-6ca9a032c043/scratchpad"
tiles = []
for ep, t_grasp in epids[::28]:
    a = int(eps["dataset_from_index"][ep])
    img = (ds[int(a + t_grasp)]["observation.images.eye_in_hand"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    cv2.putText(bgr, f"ep{ep} t_grasp={t_grasp}", (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    tiles.append(bgr)
rows = [np.hstack(tiles[i:i+3]) for i in range(0, len(tiles) - len(tiles) % 3, 3)]
if rows:
    cv2.imwrite(f"{OUT}/v4_anchor_check.jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])
    print("anchor check image written")
