"""
Deep settlement-level correlation analysis.

For each settlement from query responses, correlate its attributes
(population, food, wealth, defense, owner_id, has_port) with:
1. GT at that cell (survival probability)
2. GT at neighboring cells (expansion probability)
3. GT at cells owned by same faction
4. Faction-level aggregates → GT dynamics
5. Settlement clusters → expansion patterns
"""

import json, numpy as np, os, time
from pathlib import Path
from scipy import stats
from scipy.ndimage import distance_transform_edt, uniform_filter
from sklearn.metrics import normalized_mutual_info_score
from collections import defaultdict

BASE = Path(__file__).parent.parent / "round_data"


def safe_corr(a, b):
    if len(a) < 10 or np.std(a) < 1e-8 or np.std(b) < 1e-8:
        return np.nan
    return np.corrcoef(a, b)[0, 1]


def safe_spearman(a, b):
    if len(a) < 10 or np.std(a) < 1e-8 or np.std(b) < 1e-8:
        return np.nan
    return stats.spearmanr(a, b)[0]


def load_rounds_with_settlements():
    """Load rounds that have query_grids with settlement data + GT."""
    data = []
    for rn in range(17, 23):
        rpath = BASE / f"round_{rn:02d}.json"
        spath = BASE / f"round_{rn:02d}_submit.json"
        if not spath.exists():
            continue
        rd = json.load(open(rpath))
        sd = json.load(open(spath))

        for sid in range(5):
            sub = sd["seeds"].get(str(sid), {})
            qg = sub.get("query_grids", [])
            gt_entry = rd["seeds"][sid] if sid < len(rd.get("seeds", [])) else {}
            gt = gt_entry.get("ground_truth")
            if gt is None or not qg:
                continue

            grid = np.array(sub.get("initial_grid", rd.get("initial_grid")), dtype=np.int32)
            gt = np.array(gt, dtype=np.float32)

            # Deduplicate settlements by (x, y)
            seen = set()
            settlements = []
            for q in qg:
                for s in q.get("settlements", []):
                    key = (s["x"], s["y"])
                    if key not in seen:
                        seen.add(key)
                        settlements.append(s)

            data.append({"round": rn, "seed": sid, "grid": grid, "gt": gt,
                         "settlements": settlements})
    return data


def main():
    t0 = time.time()
    data = load_rounds_with_settlements()
    total_setts = sum(len(d["settlements"]) for d in data)
    print(f"Loaded {len(data)} seed-rounds, {total_setts} unique settlements ({time.time()-t0:.1f}s)")

    # ================================================================
    # 1. SETTLEMENT ATTRIBUTES → OWN CELL GT
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  1. SETTLEMENT ATTRIBUTES → GT AT SAME CELL")
    print(f"{'='*70}")

    # Collect: for each settlement, its attributes + GT at its cell
    rows = []
    for d in data:
        gt = d["gt"]
        grid = d["grid"]
        for s in d["settlements"]:
            x, y = s["x"], s["y"]
            if not (0 <= y < 40 and 0 <= x < 40):
                continue
            rows.append({
                "round": d["round"],
                "pop": s.get("population", 1),
                "food": s.get("food", 0.5),
                "wealth": s.get("wealth", 0),
                "defense": s.get("defense", 0.5),
                "has_port": int(s.get("has_port", False)),
                "alive": int(s.get("alive", True)),
                "owner_id": s.get("owner_id", 0),
                "gt_empty": gt[y, x, 0],
                "gt_settle": gt[y, x, 1],
                "gt_port": gt[y, x, 2],
                "gt_ruin": gt[y, x, 3],
                "gt_forest": gt[y, x, 4],
                "gt_mountain": gt[y, x, 5],
                "terrain": grid[y, x],
            })

    print(f"  {len(rows)} settlement-GT pairs")

    attrs = ["pop", "food", "wealth", "defense", "has_port"]
    targets = ["gt_empty", "gt_settle", "gt_port", "gt_ruin", "gt_forest"]

    print(f"\n  {'':>10}", end="")
    for t in targets:
        print(f"  {t:>10}", end="")
    print()

    for attr in attrs:
        print(f"  {attr:>10}", end="")
        a = np.array([r[attr] for r in rows])
        for tgt in targets:
            b = np.array([r[tgt] for r in rows])
            c = safe_corr(a, b)
            print(f"  {c:>+10.3f}", end="")
        print()

    # Spearman
    print(f"\n  Spearman:")
    print(f"  {'':>10}", end="")
    for t in targets:
        print(f"  {t:>10}", end="")
    print()
    for attr in attrs:
        print(f"  {attr:>10}", end="")
        a = np.array([r[attr] for r in rows])
        for tgt in targets:
            b = np.array([r[tgt] for r in rows])
            c = safe_spearman(a, b)
            print(f"  {c:>+10.3f}", end="")
        print()

    # ================================================================
    # 2. SETTLEMENT ATTRIBUTES → NEIGHBORING CELL GT
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  2. SETTLEMENT ATTRIBUTES → GT AT NEARBY CELLS (d=1,2,3)")
    print(f"{'='*70}")

    for dist in [1, 2, 3]:
        nbr_rows = []
        for d in data:
            gt = d["gt"]
            grid = d["grid"]
            for s in d["settlements"]:
                x, y = s["x"], s["y"]
                for dy in range(-dist, dist+1):
                    for dx in range(-dist, dist+1):
                        if dy == 0 and dx == 0:
                            continue
                        if max(abs(dy), abs(dx)) != dist:
                            continue
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < 40 and 0 <= nx < 40 and grid[ny, nx] not in (10, 5):
                            if not np.isin(grid[ny, nx], [1, 2]):  # non-settlement neighbor
                                nbr_rows.append({
                                    "pop": s.get("population", 1),
                                    "food": s.get("food", 0.5),
                                    "wealth": s.get("wealth", 0),
                                    "defense": s.get("defense", 0.5),
                                    "gt_settle": gt[ny, nx, 1],
                                    "gt_empty": gt[ny, nx, 0],
                                    "gt_forest": gt[ny, nx, 4],
                                    "terrain": grid[ny, nx],
                                })

        print(f"\n  d={dist}: {len(nbr_rows)} settlement-neighbor pairs")
        for attr in ["pop", "food", "wealth", "defense"]:
            a = np.array([r[attr] for r in nbr_rows])
            b = np.array([r["gt_settle"] for r in nbr_rows])
            c = safe_corr(a, b)
            s = safe_spearman(a, b)
            print(f"    {attr:>8} → gt_settle: pearson={c:+.3f}  spearman={s:+.3f}")

    # ================================================================
    # 3. FACTION ANALYSIS: same owner_id settlements correlate?
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  3. FACTION ANALYSIS: faction size/strength → GT")
    print(f"{'='*70}")

    faction_rows = []
    for d in data:
        gt = d["gt"]
        grid = d["grid"]
        # Group settlements by owner_id
        factions = defaultdict(list)
        for s in d["settlements"]:
            factions[s.get("owner_id", -1)].append(s)

        for fid, members in factions.items():
            if len(members) < 2:
                continue
            # Faction stats
            f_size = len(members)
            f_pop = np.mean([m["population"] for m in members])
            f_food = np.mean([m["food"] for m in members])
            f_wealth = np.mean([m["wealth"] for m in members])
            f_defense = np.mean([m["defense"] for m in members])
            f_ports = sum(1 for m in members if m.get("has_port"))

            # Faction territory: avg GT for all faction settlement cells
            gt_survives = []
            gt_expands = []
            for m in members:
                x, y = m["x"], m["y"]
                if 0 <= y < 40 and 0 <= x < 40:
                    gt_survives.append(gt[y, x, 1])  # settle survival
                    # Expansion: avg P(settle) in non-settle neighbors
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < 40 and 0 <= nx < 40 and (dy != 0 or dx != 0):
                                if not np.isin(grid[ny, nx], [1, 2, 10, 5]):
                                    gt_expands.append(gt[ny, nx, 1])

            if gt_survives:
                faction_rows.append({
                    "size": f_size, "pop": f_pop, "food": f_food,
                    "wealth": f_wealth, "defense": f_defense, "ports": f_ports,
                    "survival": np.mean(gt_survives),
                    "expansion": np.mean(gt_expands) if gt_expands else 0,
                })

    print(f"  {len(faction_rows)} factions (size >= 2)")

    for attr in ["size", "pop", "food", "wealth", "defense", "ports"]:
        a = np.array([r[attr] for r in faction_rows])
        for tgt in ["survival", "expansion"]:
            b = np.array([r[tgt] for r in faction_rows])
            c = safe_corr(a, b)
            s = safe_spearman(a, b)
            print(f"    {attr:>8} → {tgt:>10}: pearson={c:+.3f}  spearman={s:+.3f}")

    # ================================================================
    # 4. SETTLEMENT DENSITY / CLUSTERING → GT
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  4. SETTLEMENT CLUSTERING → GT DYNAMICS")
    print(f"{'='*70}")

    # For each settlement: how many other settlements within d=1,2,3?
    cluster_rows = []
    for d in data:
        gt = d["gt"]
        sett_positions = set()
        for s in d["settlements"]:
            sett_positions.add((s["x"], s["y"]))

        for s in d["settlements"]:
            x, y = s["x"], s["y"]
            if not (0 <= y < 40 and 0 <= x < 40):
                continue

            # Count nearby settlements
            n1 = sum(1 for sx, sy in sett_positions if max(abs(sx-x), abs(sy-y)) == 1)
            n2 = sum(1 for sx, sy in sett_positions if max(abs(sx-x), abs(sy-y)) <= 2) - 1
            n3 = sum(1 for sx, sy in sett_positions if max(abs(sx-x), abs(sy-y)) <= 3) - 1

            cluster_rows.append({
                "n_nbr1": n1, "n_nbr2": n2, "n_nbr3": n3,
                "pop": s.get("population", 1),
                "food": s.get("food", 0.5),
                "gt_survive": gt[y, x, 1],
                "gt_ruin": gt[y, x, 3],
                "gt_empty": gt[y, x, 0],
            })

    print(f"  {len(cluster_rows)} settlements with cluster data")

    for attr in ["n_nbr1", "n_nbr2", "n_nbr3", "pop", "food"]:
        a = np.array([r[attr] for r in cluster_rows])
        for tgt in ["gt_survive", "gt_ruin", "gt_empty"]:
            b = np.array([r[tgt] for r in cluster_rows])
            c = safe_corr(a, b)
            print(f"    {attr:>8} → {tgt:>12}: pearson={c:+.3f}")

    # ================================================================
    # 5. INTERACTION EFFECTS
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  5. INTERACTION EFFECTS (combined features)")
    print(f"{'='*70}")

    # pop × food → survival
    pop = np.array([r["pop"] for r in rows])
    food = np.array([r["food"] for r in rows])
    wealth = np.array([r["wealth"] for r in rows])
    defense = np.array([r["defense"] for r in rows])
    gt_survive = np.array([r["gt_settle"] for r in rows])
    gt_ruin = np.array([r["gt_ruin"] for r in rows])
    gt_empty = np.array([r["gt_empty"] for r in rows])

    interactions = [
        ("pop*food", pop * food),
        ("pop*defense", pop * defense),
        ("food*defense", food * defense),
        ("pop/food", pop / np.clip(food, 0.01, None)),
        ("wealth/pop", wealth / np.clip(pop, 0.01, None)),
        ("pop*food*def", pop * food * defense),
        ("log(pop)", np.log(np.clip(pop, 0.01, None))),
        ("pop^2", pop ** 2),
        ("food^2", food ** 2),
    ]

    for name, vals in interactions:
        c_surv = safe_corr(vals, gt_survive)
        c_ruin = safe_corr(vals, gt_ruin)
        c_empty = safe_corr(vals, gt_empty)
        print(f"  {name:>15} → survive={c_surv:+.3f}  ruin={c_ruin:+.3f}  empty={c_empty:+.3f}")

    # ================================================================
    # 6. PER-ROUND BREAKDOWN
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  6. PER-ROUND: pop → survival correlation")
    print(f"{'='*70}")

    for rn in range(17, 23):
        r_rows = [r for r in rows if r["round"] == rn]
        if len(r_rows) < 20:
            continue
        a = np.array([r["pop"] for r in r_rows])
        b = np.array([r["gt_settle"] for r in r_rows])
        c = safe_corr(a, b)
        s = safe_spearman(a, b)

        # Also food
        a2 = np.array([r["food"] for r in r_rows])
        c2 = safe_corr(a2, b)

        # Defense
        a3 = np.array([r["defense"] for r in r_rows])
        c3 = safe_corr(a3, b)

        print(f"  R{rn}: pop→surv={c:+.3f}  food→surv={c2:+.3f}  def→surv={c3:+.3f}  (n={len(r_rows)})")

    print(f"\nTotal: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
