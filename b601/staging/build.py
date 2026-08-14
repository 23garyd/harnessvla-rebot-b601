#!/usr/bin/env python
"""Staging v3: closure onset anchored to each episode's own open/hold gripper
values, staging pose 1s before onset, then neighborhood-consistency
filtering — nearby placements must agree on pose; disagreement marks an
extraction mistake, not operator variety."""
import sys
sys.path.insert(0, "/home/demo/Public/harnessvla-rebot-b601")
import cv2
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from b601.staging.table import StagingTable

ds = LeRobotDataset("local/b601_train",
                    root="/home/demo/Public/harnessvla-rebot-b601/datasets/b601_train",
                    tolerance_s=0.04)
eps = ds.meta.episodes
n = ds.meta.total_episodes

def agent_red(idx):
    try:
        img = (ds[int(idx)]["observation.images.agentview"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
    except Exception:
        return None
    hsv = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 70, 90), (14, 255, 255)) | cv2.inRange(hsv, (168, 70, 90), (180, 255, 255))
    mask[:60, :] = 0
    cnt, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
    best = max((i for i in range(1, cnt) if stats[i, cv2.CC_STAT_AREA] >= 250),
               key=lambda i: stats[i, cv2.CC_STAT_AREA], default=None)
    return cents[best] if best is not None else None

points, poses, epids, skipped = [], [], [], []
for ep in range(n):
    a, b = int(eps["dataset_from_index"][ep]), int(eps["dataset_to_index"][ep])
    L = b - a
    p = None
    for f in (0, 15, 30, 45):
        p = agent_red(a + f)
        if p is not None:
            break
    if p is None:
        skipped.append((ep, "no block")); continue
    st = np.stack([ds[int(i)]["observation.state"].numpy() for i in range(a, b)])
    grip = st[:, 6]
    g_open = float(np.median(grip[:10]))
    g_hold = float(np.median(grip[int(L*0.4):int(L*0.6)]))     # mid-carry
    if abs(g_hold - g_open) < 15:
        skipped.append((ep, "no clear hold value")); continue
    midpoint = (g_open + g_hold) / 2
    toward = np.sign(g_hold - g_open)
    crossed = np.nonzero(toward * (grip - midpoint) > 0)[0]
    crossed = crossed[crossed > 5]
    if len(crossed) == 0:
        skipped.append((ep, "no closure crossing")); continue
    t_grasp = int(crossed[0])
    stage_i = max(0, t_grasp - 30)
    points.append((float(p[0]), float(p[1])))
    poses.append([float(v) for v in st[stage_i]])
    epids.append(ep)
    if (ep + 1) % 40 == 0:
        print(f"...{ep + 1}/{n}", flush=True)
print(f"extracted {len(points)}; skipped {len(skipped)}", flush=True)

# neighborhood consistency filter
P = np.array(points); Q = np.array(poses)
keep = []
dropped = []
for i in range(len(P)):
    d = np.hypot(P[:, 0] - P[i, 0], P[:, 1] - P[i, 1])
    nb = np.nonzero((d < 40) & (d > 0))[0]
    if len(nb) < 2:
        keep.append(i); continue                 # too sparse to judge; keep
    med = np.median(Q[nb, :6], axis=0)
    dev = float(np.abs(Q[i, :6] - med).max())
    if dev <= 15.0:
        keep.append(i)
    else:
        dropped.append((epids[i], round(dev, 1)))
print(f"consistency filter: kept {len(keep)}, dropped {len(dropped)}")
if dropped[:8]:
    print("dropped (ep, max joint dev):", dropped[:8])

pts = [points[i] for i in keep]; ps = [poses[i] for i in keep]
errs = []
for i in range(len(pts)):
    t = StagingTable.fit(pts[:i] + pts[i+1:], ps[:i] + ps[i+1:])
    try:
        pred, _ = t.query(*pts[i])
    except Exception:
        continue
    errs.append(np.abs(np.array(pred[:6]) - np.array(ps[i][:6])))
E = np.stack(errs)
print("\nLOO error after filtering (deg):")
print("  median:", [round(float(v), 1) for v in np.median(E, axis=0)])
print("  p90   :", [round(float(v), 1) for v in np.percentile(E, 90, axis=0)])

table = StagingTable.fit(pts, ps)
for i, (hx, hy) in enumerate([(180, 260), (240, 260), (210, 295), (180, 330), (240, 330)], 1):
    try:
        _, d = table.query(hx, hy)
        print(f"  H{i}: {d:.0f}px answerable")
    except Exception as e:
        print(f"  H{i}: REFUSED {e}")
table.write("/home/demo/Public/harnessvla-rebot-b601/b601/setup/staging_table.json")
print("TABLE v3 WRITTEN")
