#!/usr/bin/env python3
"""
NBA Record Alerts — Nightly Update
Fetches 2025-26 box scores, checks against historical record book,
generates alerts for new records broken by country/college/state/position.
"""
import csv, gzip, io, json, os, sys
from datetime import datetime
from collections import defaultdict

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vSp9Dyp62wra-_9vCmOlSzuelR8RkigcQsRX8MJs0s9Npabi7r0eVFA6deVdmd19X5DJc5V5Ci2m-nc"
    "/pub?gid=0&single=true&output=csv"
)
BASELINE_FILE = "alerts_baseline.bin"
OUTPUT_FILE = "alerts.json"

def safe_int(v):
    try: return int(float(v))
    except: return 0

GAME_STATS = {"game_pts":"points","game_reb":"rebounds","game_ast":"assists",
              "game_stl":"steals","game_blk":"blocks","game_tpm":"3-pointers"}
GAME_MINS = {"game_pts":20,"game_reb":10,"game_ast":8,"game_stl":4,"game_blk":3,"game_tpm":4}

STREAK_CHECKS = {
    "pts20":("20+ PTS",lambda p,r,a,s,b,t:p>=20),
    "pts25":("25+ PTS",lambda p,r,a,s,b,t:p>=25),
    "pts30":("30+ PTS",lambda p,r,a,s,b,t:p>=30),
    "pts35":("35+ PTS",lambda p,r,a,s,b,t:p>=35),
    "pts40":("40+ PTS",lambda p,r,a,s,b,t:p>=40),
    "reb10":("10+ REB",lambda p,r,a,s,b,t:r>=10),
    "reb15":("15+ REB",lambda p,r,a,s,b,t:r>=15),
    "ast10":("10+ AST",lambda p,r,a,s,b,t:a>=10),
    "ast15":("15+ AST",lambda p,r,a,s,b,t:a>=15),
    "dd":("double-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=2),
    "td":("triple-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=3),
    "stl2":("2+ STL",lambda p,r,a,s,b,t:s>=2),
    "stl3":("3+ STL",lambda p,r,a,s,b,t:s>=3),
    "blk2":("2+ BLK",lambda p,r,a,s,b,t:b>=2),
    "blk3":("3+ BLK",lambda p,r,a,s,b,t:b>=3),
    "tpm3":("3+ 3PM",lambda p,r,a,s,b,t:t>=3),
    "tpm5":("5+ 3PM",lambda p,r,a,s,b,t:t>=5),
}

COMPOUND_LABELS = {
    "pts30_ast10":"30+ PTS & 10+ AST","pts30_reb10":"30+ PTS & 10+ REB",
    "pts35_ast10":"35+ PTS & 10+ AST","pts40_reb10":"40+ PTS & 10+ REB",
    "pts20_reb10_ast10":"20-10-10 (PTS/REB/AST)","pts25_reb10_ast10":"25-10-10 (PTS/REB/AST)",
    "reb20":"20+ REB","ast15":"15+ AST","stl5":"5+ STL","blk5":"5+ BLK",
    "pts50":"50+ PTS","pts60":"60+ PTS","5x5":"5x5 (5+ in PTS/REB/AST/STL/BLK)",
}
COMPOUND_CHECKS = {
    "pts30_ast10":lambda p,r,a,s,b,t:p>=30 and a>=10,
    "pts30_reb10":lambda p,r,a,s,b,t:p>=30 and r>=10,
    "pts35_ast10":lambda p,r,a,s,b,t:p>=35 and a>=10,
    "pts40_reb10":lambda p,r,a,s,b,t:p>=40 and r>=10,
    "pts20_reb10_ast10":lambda p,r,a,s,b,t:p>=20 and r>=10 and a>=10,
    "pts25_reb10_ast10":lambda p,r,a,s,b,t:p>=25 and r>=10 and a>=10,
    "reb20":lambda p,r,a,s,b,t:r>=20,
    "ast15":lambda p,r,a,s,b,t:a>=15,
    "stl5":lambda p,r,a,s,b,t:s>=5,
    "blk5":lambda p,r,a,s,b,t:b>=5,
    "pts50":lambda p,r,a,s,b,t:p>=50,
    "pts60":lambda p,r,a,s,b,t:p>=60,
    "5x5":lambda p,r,a,s,b,t:all(v>=5 for v in [p,r,a,s,b]),
}


def filter_label(fk):
    if fk == "all": return ""
    cat, val = fk.split(":", 1)
    if cat == "country": return f"by a {val} player"
    if cat == "college": return f"by a {val} alum"
    if cat == "state": return f"by a player from {val}"
    if cat == "pos": return f"by a {val}"
    return ""


def load_baseline():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BASELINE_FILE)
    if not os.path.exists(path):
        print(f"ERROR: {BASELINE_FILE} not found"); sys.exit(1)
    with gzip.open(path, "rb") as f:
        data = json.loads(f.read())
    print(f"Baseline: {len(data['records'])} record groups, {len(data.get('valid_groups',[]))} valid groups")
    return data


def fetch_2526():
    import requests
    print("Fetching 2025-26 box scores...")
    resp = requests.get(SHEET_CSV_URL, timeout=30); resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    try: next(reader); next(reader)
    except: pass
    blocks = []; cb = None
    for row in reader:
        if len(row) < 23: continue
        ds = row[0].strip(); pl = row[1].strip()
        if not ds or "/" not in ds: continue
        try: dt = datetime.strptime(ds, "%m/%d/%Y")
        except: continue
        if dt < datetime(2025, 10, 1): continue
        tm = row[22].strip()
        if pl == "TOTALS":
            if cb: blocks.append(cb); cb = None; continue
        if pl in ("PLAYER", ""): continue
        gd = {"player": pl, "dt": dt, "team": tm,
              "pts": safe_int(row[20]), "reb": safe_int(row[14]), "ast": safe_int(row[15]),
              "stl": safe_int(row[16]), "blk": safe_int(row[17]), "tpm": safe_int(row[6])}
        if cb is None or cb[0] != ds or cb[1] != tm:
            if cb: blocks.append(cb)
            cb = (ds, tm, [])
        cb[2].append(gd)
    if cb: blocks.append(cb)
    # Pair blocks
    games = []
    i = 0
    while i < len(blocks) - 1:
        d1, t1, p1 = blocks[i]; d2, t2, p2 = blocks[i + 1]
        if d1 == d2:
            for g in p1: g["opp"] = t2; games.append((d1, g))
            for g in p2: g["opp"] = t1; games.append((d2, g))
            i += 2
        else: i += 1
    games.sort(key=lambda x: x[1]["dt"])
    print(f"  {len(games)} player-games")
    return games


def detect_alerts(baseline, games):
    records = baseline["records"]
    streak_records = baseline["streak_records"]
    streaks_current = baseline.get("streaks_current", {})
    compound_history = baseline.get("compound_history", {})
    bio = baseline["bio"]
    valid_groups = set(baseline.get("valid_groups", []))

    def get_fkeys(name):
        keys = ["all"]
        b = bio.get(name, {})
        if b.get("country"):
            k = f"country:{b['country']}"
            if k in valid_groups: keys.append(k)
        if b.get("college"):
            k = f"college:{b['college']}"
            if k in valid_groups: keys.append(k)
        if b.get("state"):
            k = f"state:{b['state']}"
            if k in valid_groups: keys.append(k)
        if b.get("pos"):
            k = f"pos:{b['pos']}"
            if k in valid_groups: keys.append(k)
        return keys

    alerts_by_date = {}
    alert_count = 0

    for date_str, g in games:
        dt = g["dt"]
        iso = dt.strftime("%Y-%m-%d")
        name = g["player"]
        pts, reb, ast = g["pts"], g["reb"], g["ast"]
        stl, blk, tpm = g["stl"], g["blk"], g["tpm"]
        team = g["team"]; opp = g.get("opp", "")
        fkeys = get_fkeys(name)
        line = f"{pts} PTS, {reb} REB, {ast} AST"
        if stl >= 3 or blk >= 3 or tpm >= 5:
            line += f", {stl} STL, {blk} BLK, {tpm} 3PM"

        day_alerts = []

        # 1. Single-game records
        stat_vals = {"game_pts": pts, "game_reb": reb, "game_ast": ast,
                     "game_stl": stl, "game_blk": blk, "game_tpm": tpm}
        for fk in fkeys:
            if fk == "all": continue
            for stat, val in stat_vals.items():
                if val < GAME_MINS.get(stat, 0): continue
                rec = records.get(fk, {}).get(stat, {})
                old_val = rec.get("value", 0)
                old_player = rec.get("player", "")
                if val > old_val and old_val > 0:
                    fl = filter_label(fk)
                    sl = GAME_STATS[stat]
                    if old_player == name:
                        text = f"New personal record: Most {sl} in a game {fl} ({val}), surpassing own record of {old_val}"
                    else:
                        text = f"🏆 NEW RECORD: Most {sl} in a game {fl} ({val}), breaking {old_player}'s record of {old_val} ({rec.get('date', '')})"
                    day_alerts.append({"type": "record", "player": name, "team": team, "opp": opp,
                        "line": line, "alert": text, "_fk": fk, "_pri": 1 if old_player != name else 2})
                    if fk not in records: records[fk] = {}
                    records[fk][stat] = {"value": val, "player": name, "date": iso, "season": 2026}

        # 2. Streaks
        if name not in streaks_current: streaks_current[name] = {}
        for sk, (label, check_fn) in STREAK_CHECKS.items():
            passed = check_fn(pts, reb, ast, stl, blk, tpm)
            streaks_current[name][sk] = streaks_current[name].get(sk, 0) + 1 if passed else 0
            cur = streaks_current[name][sk]
            if cur < 5: continue
            for fk in fkeys:
                if fk == "all": continue
                sr = streak_records.get(fk, {}).get(sk, {})
                old_val = sr.get("value", 0)
                old_player = sr.get("player", "")
                if cur > old_val:
                    if old_player != name:
                        fl = filter_label(fk)
                        text = f"🔥 STREAK RECORD: {cur} consecutive games with {label} {fl}, breaking {old_player}'s record of {old_val}"
                        day_alerts.append({"type": "streak_record", "player": name, "team": team,
                            "opp": opp, "line": line, "alert": text, "_fk": fk, "_pri": 1})
                    elif cur % 25 == 0:
                        fl = filter_label(fk)
                        text = f"🔥 STREAK: {cur} consecutive games with {label} {fl} (extending own record)"
                        day_alerts.append({"type": "streak_extend", "player": name, "team": team,
                            "opp": opp, "line": line, "alert": text, "_fk": fk, "_pri": 3})
                    if fk not in streak_records: streak_records[fk] = {}
                    streak_records[fk][sk] = {"value": cur, "player": name, "date": iso, "season": 2026}

        # 3. Compound first-ever
        for ck, check_fn in COMPOUND_CHECKS.items():
            if not check_fn(pts, reb, ast, stl, blk, tpm): continue
            for fk in fkeys:
                if fk == "all": continue
                ch = compound_history.get(fk, {}).get(ck, {})
                if ch.get("count", 0) == 0:
                    fl = filter_label(fk)
                    cl = COMPOUND_LABELS[ck]
                    text = f"⭐ FIRST EVER: {cl} game {fl}"
                    day_alerts.append({"type": "first_ever", "player": name, "team": team,
                        "opp": opp, "line": line, "alert": text, "_fk": fk, "_pri": 1})
                if fk not in compound_history: compound_history[fk] = {}
                if ck not in compound_history[fk]:
                    compound_history[fk][ck] = {"count": 0, "last": None}
                compound_history[fk][ck]["count"] += 1
                compound_history[fk][ck]["last"] = {"player": name, "date": iso, "season": 2026}

        # Dedup
        if day_alerts:
            seen = set()
            deduped = []
            for a in sorted(day_alerts, key=lambda x: x.get("_pri", 9)):
                key = (a["player"], a["type"], a["alert"][:80])
                if key not in seen:
                    seen.add(key)
                    deduped.append(a)
            for a in deduped:
                a.pop("_fk", None); a.pop("_pri", None)
            if iso not in alerts_by_date: alerts_by_date[iso] = []
            alerts_by_date[iso].extend(deduped)
            alert_count += len(deduped)

    print(f"  {alert_count} alerts across {len(alerts_by_date)} dates")
    return alerts_by_date


def save_output(alerts):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(path, "w") as f:
        json.dump(alerts, f, separators=(",", ":"))
    size_kb = os.path.getsize(path) / 1024
    print(f"\nSaved {OUTPUT_FILE} ({size_kb:.0f} KB)")
    dates = sorted(alerts.keys(), reverse=True)
    print(f"\nMost recent alerts:")
    for d in dates[:5]:
        als = alerts[d]
        print(f"\n  {d} ({len(als)} alerts):")
        for a in als[:5]:
            print(f"    {a['player']}: {a['alert'][:80]}")


def main():
    print("=" * 56)
    print("  NBA RECORD ALERTS — Update Script")
    print("=" * 56)
    print()
    baseline = load_baseline()
    games = fetch_2526()
    alerts = detect_alerts(baseline, games)
    save_output(alerts)
    print("\nDone! ✓")


if __name__ == "__main__":
    main()
