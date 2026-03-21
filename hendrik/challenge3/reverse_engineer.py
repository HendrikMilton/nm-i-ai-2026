"""
Reverse engineer simulation rules from query observations.
Each query = 1 stochastic sim outcome for a viewport.
Compare initial_grid cells to observed outcome cells to extract transition rules.
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict, Counter
from scipy.ndimage import distance_transform_edt

ELIAS_DIR = Path('/home/hendrik/Documents/agentic-avengers-nm-ai/elias/logs/offline')
TERRAIN_NAMES = {0: "empty", 1: "settlement", 2: "port", 3: "ruin", 4: "forest", 5: "mountain", 10: "ocean", 11: "plains"}
# Map observed codes to output codes (in case sim uses same terrain codes)
# From the sim output, cells can be: 0=empty, 1=settlement, 2=port, 3=ruin, 4=forest, 5=mountain


def count_neighbors_at(grid, r, c, code):
    count = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            nr, nc = r + dy, c + dx
            if 0 <= nr < grid.shape[0] and 0 <= nc < grid.shape[1]:
                if grid[nr, nc] == code:
                    count += 1
    return count


def extract_transitions():
    """Extract all (initial_context, outcome) pairs from query observations."""
    transitions = []  # list of dicts with context features + outcome

    n_files = 0
    for f in sorted(ELIAS_DIR.glob('*.json')):
        d = json.loads(f.read_text())
        seeds = d.get('seeds', {})
        if not isinstance(seeds, dict):
            continue

        for sid, s in seeds.items():
            ig = s.get('initial_grid')
            queries = s.get('queries', [])
            if ig is None or not queries:
                continue

            ig = np.array(ig, dtype=np.int32)
            h, w = ig.shape

            # Precompute features on full initial grid
            settle_mask = (ig == 1).astype(np.float32)
            ocean_mask = (ig == 10).astype(np.float32)
            forest_mask = (ig == 4).astype(np.float32)

            dist_settle = distance_transform_edt(1 - settle_mask) if settle_mask.sum() > 0 else np.full_like(settle_mask, 99)
            dist_ocean = distance_transform_edt(1 - ocean_mask) if ocean_mask.sum() > 0 else np.full_like(ocean_mask, 99)

            for q in queries:
                if 'grid' not in q or 'viewport' not in q:
                    continue
                vp = q['viewport']
                vx, vy, vw, vh = vp['x'], vp['y'], vp['w'], vp['h']
                obs = np.array(q['grid'], dtype=np.int32)

                if obs.shape != (vh, vw):
                    continue

                for lr in range(vh):
                    for lc in range(vw):
                        gr, gc = vy + lr, vx + lc
                        if gr >= h or gc >= w:
                            continue

                        init_code = ig[gr, gc]
                        outcome = obs[lr, lc]

                        transitions.append({
                            'init': init_code,
                            'outcome': outcome,
                            'n_settle': count_neighbors_at(ig, gr, gc, 1),
                            'n_forest': count_neighbors_at(ig, gr, gc, 4),
                            'n_ocean': count_neighbors_at(ig, gr, gc, 10),
                            'n_mountain': count_neighbors_at(ig, gr, gc, 5),
                            'n_plains': count_neighbors_at(ig, gr, gc, 11),
                            'dist_settle': int(min(dist_settle[gr, gc], 20)),
                            'dist_ocean': int(min(dist_ocean[gr, gc], 20)),
                            'is_edge': int(gr <= 0 or gr >= h-1 or gc <= 0 or gc >= w-1),
                            'row': gr,
                            'col': gc,
                        })

        n_files += 1

    print(f"Processed {n_files} files, extracted {len(transitions)} cell transitions")
    return transitions


def section(title):
    print(f"\n{'=' * 80}")
    print(title)
    print('=' * 80)


def analyze_transitions(transitions):
    # ================================================================
    # 1. RAW TRANSITION MATRIX
    # ================================================================
    section("1. RAW TRANSITION COUNTS (init_terrain → observed outcome)")

    matrix = defaultdict(Counter)
    for t in transitions:
        matrix[t['init']][t['outcome']] += 1

    all_outcomes = sorted(set(t['outcome'] for t in transitions))
    outcome_names = {c: TERRAIN_NAMES.get(c, f"?{c}") for c in all_outcomes}

    print(f"  {'Initial':>12} | " + " ".join(f"{outcome_names[c]:>10}" for c in all_outcomes) + " |      Total")
    print("  " + "-" * (15 + 11 * len(all_outcomes) + 14))

    for code in sorted(matrix.keys()):
        total = sum(matrix[code].values())
        pcts = [matrix[code][c] / total * 100 for c in all_outcomes]
        print(f"  {TERRAIN_NAMES.get(code, str(code)):>12} | " +
              " ".join(f"{p:>9.1f}%" for p in pcts) +
              f" | {total:>10}")

    # ================================================================
    # 2. SETTLEMENT SURVIVAL by neighbor count
    # ================================================================
    section("2. SETTLEMENT SURVIVAL by # neighboring settlements")

    settle_trans = [t for t in transitions if t['init'] == 1]
    by_ns = defaultdict(Counter)
    for t in settle_trans:
        by_ns[t['n_settle']][t['outcome']] += 1

    print(f"  {'#SettleNbr':>10} | {'N':>7} | {'→empty':>8} {'→settle':>8} {'→port':>8} {'→ruin':>8} {'→forest':>8} {'→mtn':>8}")
    for ns in sorted(by_ns.keys()):
        total = sum(by_ns[ns].values())
        print(f"  {ns:>10} | {total:>7} | " +
              f"{by_ns[ns].get(0,0)/total*100:>7.1f}% " +
              f"{by_ns[ns].get(1,0)/total*100:>7.1f}% " +
              f"{by_ns[ns].get(2,0)/total*100:>7.1f}% " +
              f"{by_ns[ns].get(3,0)/total*100:>7.1f}% " +
              f"{by_ns[ns].get(4,0)/total*100:>7.1f}% " +
              f"{by_ns[ns].get(5,0)/total*100:>7.1f}%")

    # ================================================================
    # 3. SETTLEMENT SURVIVAL by coast proximity
    # ================================================================
    section("3. SETTLEMENT: coast vs inland")

    for label, filt in [("coastal (ocean nbr>0)", lambda t: t['n_ocean'] > 0),
                        ("inland (ocean nbr=0)", lambda t: t['n_ocean'] == 0)]:
        subset = [t for t in settle_trans if filt(t)]
        c = Counter(t['outcome'] for t in subset)
        total = len(subset)
        if total == 0:
            continue
        print(f"  {label}: N={total}")
        for code in sorted(c.keys()):
            print(f"    → {TERRAIN_NAMES.get(code, str(code)):>12}: {c[code]/total*100:.1f}%")

    # ================================================================
    # 4. PLAINS → what, by distance to settlement
    # ================================================================
    section("4. PLAINS outcome by distance to nearest settlement")

    plains_trans = [t for t in transitions if t['init'] == 11]
    by_dist = defaultdict(Counter)
    for t in plains_trans:
        d = min(t['dist_settle'], 10)
        by_dist[d][t['outcome']] += 1

    print(f"  {'Dist':>6} | {'N':>7} | {'→empty':>8} {'→settle':>8} {'→port':>8} {'→ruin':>8} {'→forest':>8}")
    for d in sorted(by_dist.keys()):
        total = sum(by_dist[d].values())
        print(f"  {d:>6} | {total:>7} | " +
              f"{by_dist[d].get(0,0)/total*100:>7.1f}% " +
              f"{by_dist[d].get(1,0)/total*100:>7.1f}% " +
              f"{by_dist[d].get(2,0)/total*100:>7.1f}% " +
              f"{by_dist[d].get(3,0)/total*100:>7.1f}% " +
              f"{by_dist[d].get(4,0)/total*100:>7.1f}%")

    # ================================================================
    # 5. FOREST behavior by neighbors
    # ================================================================
    section("5. FOREST outcome by # neighboring forests")

    forest_trans = [t for t in transitions if t['init'] == 4]
    by_nf = defaultdict(Counter)
    for t in forest_trans:
        by_nf[t['n_forest']][t['outcome']] += 1

    print(f"  {'#ForNbr':>7} | {'N':>7} | {'→empty':>8} {'→settle':>8} {'→forest':>8} {'→ruin':>8}")
    for nf in sorted(by_nf.keys()):
        total = sum(by_nf[nf].values())
        print(f"  {nf:>7} | {total:>7} | " +
              f"{by_nf[nf].get(0,0)/total*100:>7.1f}% " +
              f"{by_nf[nf].get(1,0)/total*100:>7.1f}% " +
              f"{by_nf[nf].get(4,0)/total*100:>7.1f}% " +
              f"{by_nf[nf].get(3,0)/total*100:>7.1f}%")

    # ================================================================
    # 6. OCEAN — what happens at edges?
    # ================================================================
    section("6. OCEAN cells: do they ever change?")

    ocean_trans = [t for t in transitions if t['init'] == 10]
    c = Counter(t['outcome'] for t in ocean_trans)
    total = len(ocean_trans)
    print(f"  Total ocean observations: {total}")
    for code in sorted(c.keys()):
        print(f"    → {TERRAIN_NAMES.get(code, str(code)):>12}: {c[code]:>6} ({c[code]/total*100:.2f}%)")

    # ================================================================
    # 7. MOUNTAIN — stable?
    # ================================================================
    section("7. MOUNTAIN cells")

    mtn_trans = [t for t in transitions if t['init'] == 5]
    c = Counter(t['outcome'] for t in mtn_trans)
    total = len(mtn_trans)
    print(f"  Total mountain observations: {total}")
    for code in sorted(c.keys()):
        print(f"    → {TERRAIN_NAMES.get(code, str(code)):>12}: {c[code]:>6} ({c[code]/total*100:.2f}%)")

    # ================================================================
    # 8. PORT formation — what creates ports?
    # ================================================================
    section("8. PORT FORMATION — which cells become ports?")

    port_outcomes = [t for t in transitions if t['outcome'] == 2]
    print(f"  Total port outcomes: {len(port_outcomes)}")
    by_init = Counter(t['init'] for t in port_outcomes)
    for code in sorted(by_init.keys()):
        subset = [t for t in port_outcomes if t['init'] == code]
        coast_pct = sum(1 for t in subset if t['n_ocean'] > 0) / max(len(subset), 1) * 100
        print(f"    from {TERRAIN_NAMES.get(code, str(code)):>12}: {by_init[code]:>5} "
              f"({coast_pct:.0f}% are coastal)")

    # ================================================================
    # 9. RUIN formation — what creates ruins?
    # ================================================================
    section("9. RUIN FORMATION — which cells become ruins?")

    ruin_outcomes = [t for t in transitions if t['outcome'] == 3]
    print(f"  Total ruin outcomes: {len(ruin_outcomes)}")
    by_init = Counter(t['init'] for t in ruin_outcomes)
    for code in sorted(by_init.keys()):
        print(f"    from {TERRAIN_NAMES.get(code, str(code)):>12}: {by_init[code]:>5}")

    # ================================================================
    # 10. SETTLEMENT EXPANSION — new settlements on previously empty land
    # ================================================================
    section("10. NEW SETTLEMENT formation on plains/empty by context")

    new_settle = [t for t in transitions if t['outcome'] == 1 and t['init'] in (0, 11)]
    total_plains = len([t for t in transitions if t['init'] in (0, 11)])
    print(f"  Plains/empty → settlement: {len(new_settle)}/{total_plains} ({len(new_settle)/max(total_plains,1)*100:.2f}%)")

    by_ds = defaultdict(lambda: [0, 0])
    for t in transitions:
        if t['init'] not in (0, 11):
            continue
        d = min(t['dist_settle'], 12)
        by_ds[d][0] += 1
        if t['outcome'] == 1:
            by_ds[d][1] += 1

    print(f"\n  {'DistSettle':>10} | {'Total':>7} | {'→Settle':>7} | {'Rate':>7}")
    for d in sorted(by_ds.keys()):
        total, settle = by_ds[d]
        print(f"  {d:>10} | {total:>7} | {settle:>7} | {settle/max(total,1)*100:>6.2f}%")

    # ================================================================
    # 11. CONSISTENCY CHECK — do same initial conditions give similar distributions?
    # ================================================================
    section("11. CONSISTENCY: same cell across multiple observations")

    # Group by (round_file, seed, row, col) — if same cell observed multiple times
    cell_obs = defaultdict(list)
    for f in sorted(ELIAS_DIR.glob('*.json')):
        d = json.loads(f.read_text())
        seeds = d.get('seeds', {})
        if not isinstance(seeds, dict):
            continue
        rid = d.get('round_id', f.stem)
        for sid, s in seeds.items():
            for q in s.get('queries', []):
                if 'grid' not in q or 'viewport' not in q:
                    continue
                vp = q['viewport']
                obs = np.array(q['grid'])
                for lr in range(obs.shape[0]):
                    for lc in range(obs.shape[1]):
                        key = (rid, sid, vp['y'] + lr, vp['x'] + lc)
                        cell_obs[key].append(obs[lr, lc])

    multi = {k: v for k, v in cell_obs.items() if len(v) >= 3}
    print(f"  Cells observed 3+ times: {len(multi)}")
    if multi:
        agreements = []
        for k, obs_list in multi.items():
            most_common = Counter(obs_list).most_common(1)[0][1]
            agreements.append(most_common / len(obs_list))
        print(f"  Mean agreement rate: {np.mean(agreements):.1%}")
        print(f"  (1.0 = deterministic, 0.5 = highly random)")

        # Show variance distribution
        buckets = [0, 0, 0, 0, 0]  # 100%, 80-99%, 60-79%, 40-59%, <40%
        for a in agreements:
            if a >= 1.0: buckets[0] += 1
            elif a >= 0.8: buckets[1] += 1
            elif a >= 0.6: buckets[2] += 1
            elif a >= 0.4: buckets[3] += 1
            else: buckets[4] += 1
        total = len(agreements)
        print(f"  100% agree: {buckets[0]/total:.1%}, 80-99%: {buckets[1]/total:.1%}, "
              f"60-79%: {buckets[2]/total:.1%}, 40-59%: {buckets[3]/total:.1%}, <40%: {buckets[4]/total:.1%}")


if __name__ == "__main__":
    transitions = extract_transitions()
    analyze_transitions(transitions)
