#!/usr/bin/env python3
"""
NBA Record Alerts — Nightly Update
Checks new 2025-26 games against historical record book.
Detects records by country, college, state, position, team, and age.
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

def parse_bday(s):
    for fmt in ["%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"]:
        try: return datetime.strptime(s.strip(), fmt)
        except: continue
    return None

def age_at_date(bday, game_date):
    if not bday or not game_date: return None
    return round((game_date - bday).days / 365.25, 2)

def age_str(a):
    yrs = int(a); days = int((a - yrs) * 365.25)
    return f"{yrs} years, {days} days"

NICK_TO_TEAM = {
    "Hawks":"Hawks","Celtics":"Celtics","Nets":"Nets","Hornets":"Hornets","Bulls":"Bulls",
    "Cavaliers":"Cavaliers","Mavericks":"Mavericks","Nuggets":"Nuggets","Pistons":"Pistons",
    "Warriors":"Warriors","Rockets":"Rockets","Pacers":"Pacers","Clippers":"Clippers",
    "Lakers":"Lakers","Grizzlies":"Grizzlies","Heat":"Heat","Bucks":"Bucks",
    "Timberwolves":"Timberwolves","Pelicans":"Pelicans","Knicks":"Knicks","Thunder":"Thunder",
    "Magic":"Magic","Sixers":"Sixers","Suns":"Suns","Trail Blazers":"Trail Blazers",
    "Kings":"Kings","Spurs":"Spurs","Raptors":"Raptors","Jazz":"Jazz","Wizards":"Wizards",
    "Oklahoma City":"Thunder","San Antonio":"Spurs","Golden State":"Warriors",
    "New Orleans":"Pelicans","LA Lakers":"Lakers","LA Clippers":"Clippers",
    "New York":"Knicks","Brooklyn":"Nets","Philadelphia":"Sixers","Washington":"Wizards",
    "Charlotte":"Hornets","Indiana":"Pacers","Milwaukee":"Bucks","Cleveland":"Cavaliers",
    "Detroit":"Pistons","Atlanta":"Hawks","Miami":"Heat","Orlando":"Magic","Toronto":"Raptors",
    "Boston":"Celtics","Chicago":"Bulls","Minnesota":"Timberwolves","Denver":"Nuggets",
    "Utah":"Jazz","Portland":"Trail Blazers","Sacramento":"Kings","Phoenix":"Suns",
    "Dallas":"Mavericks","Houston":"Rockets","Memphis":"Grizzlies",
}

GAME_STATS = {"game_pts":"points","game_reb":"rebounds","game_ast":"assists",
              "game_stl":"steals","game_blk":"blocks","game_tpm":"3-pointers"}
GAME_MINS = {"game_pts":20,"game_reb":10,"game_ast":8,"game_stl":4,"game_blk":3,"game_tpm":4}

STREAK_CHECKS = {
    "pts20":("20+ PTS",lambda p,r,a,s,b,t:p>=20),"pts25":("25+ PTS",lambda p,r,a,s,b,t:p>=25),
    "pts30":("30+ PTS",lambda p,r,a,s,b,t:p>=30),"pts35":("35+ PTS",lambda p,r,a,s,b,t:p>=35),
    "pts40":("40+ PTS",lambda p,r,a,s,b,t:p>=40),"reb10":("10+ REB",lambda p,r,a,s,b,t:r>=10),
    "reb15":("15+ REB",lambda p,r,a,s,b,t:r>=15),"ast10":("10+ AST",lambda p,r,a,s,b,t:a>=10),
    "ast15":("15+ AST",lambda p,r,a,s,b,t:a>=15),
    "dd":("double-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=2),
    "td":("triple-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=3),
    "stl2":("2+ STL",lambda p,r,a,s,b,t:s>=2),"stl3":("3+ STL",lambda p,r,a,s,b,t:s>=3),
    "blk2":("2+ BLK",lambda p,r,a,s,b,t:b>=2),"blk3":("3+ BLK",lambda p,r,a,s,b,t:b>=3),
    "tpm3":("3+ 3PM",lambda p,r,a,s,b,t:t>=3),"tpm5":("5+ 3PM",lambda p,r,a,s,b,t:t>=5),
}

COMPOUND_LABELS = {"pts25_reb10": "25+ PTS & 10+ REB", "pts30_reb10": "30+ PTS & 10+ REB", "pts30_reb15": "30+ PTS & 15+ REB", "pts40_reb10": "40+ PTS & 10+ REB", "pts40_reb15": "40+ PTS & 15+ REB", "pts25_ast10": "25+ PTS & 10+ AST", "pts30_ast10": "30+ PTS & 10+ AST", "pts30_ast15": "30+ PTS & 15+ AST", "pts35_ast10": "35+ PTS & 10+ AST", "pts40_ast10": "40+ PTS & 10+ AST", "pts20_blk5": "20+ PTS & 5+ BLK", "pts25_blk5": "25+ PTS & 5+ BLK", "pts30_blk5": "30+ PTS & 5+ BLK", "pts20_stl5": "20+ PTS & 5+ STL", "pts25_stl5": "25+ PTS & 5+ STL", "pts30_stl5": "30+ PTS & 5+ STL", "pts30_tpm5": "30+ PTS & 5+ 3PM", "pts30_tpm8": "30+ PTS & 8+ 3PM", "pts40_tpm5": "40+ PTS & 5+ 3PM", "ast10_reb10": "10+ AST & 10+ REB", "ast15_reb10": "15+ AST & 10+ REB", "ast10_blk3": "10+ AST & 3+ BLK", "ast10_blk5": "10+ AST & 5+ BLK", "ast10_stl3": "10+ AST & 3+ STL", "ast10_stl5": "10+ AST & 5+ STL", "reb15_blk3": "15+ REB & 3+ BLK", "reb15_blk5": "15+ REB & 5+ BLK", "reb10_blk5": "10+ REB & 5+ BLK", "reb15_stl3": "15+ REB & 3+ STL", "stl3_blk3": "3+ STL & 3+ BLK", "stl5_blk3": "5+ STL & 3+ BLK", "pts20_reb10_ast10": "20-10-10", "pts25_reb10_ast10": "25-10-10", "pts30_reb10_ast10": "30-10-10", "pts30_reb10_ast5": "30+ PTS, 10+ REB & 5+ AST", "pts20_reb10_blk3": "20+ PTS, 10+ REB & 3+ BLK", "pts20_ast10_stl3": "20+ PTS, 10+ AST & 3+ STL", "pts20_reb5_ast5_stl3": "20+ PTS, 5+ REB, 5+ AST & 3+ STL", "pts20_reb5_ast5_blk3": "20+ PTS, 5+ REB, 5+ AST & 3+ BLK", "pts50": "50+ PTS", "pts60": "60+ PTS", "reb20": "20+ REB", "ast15": "15+ AST", "ast20": "20+ AST", "stl5": "5+ STL", "stl7": "7+ STL", "blk5": "5+ BLK", "blk7": "7+ BLK", "tpm8": "8+ 3PM", "tpm10": "10+ 3PM", "5x5": "5x5", "tpm5_ast10": "5+ 3PM & 10+ AST", "tpm5_reb10": "5+ 3PM & 10+ REB", "tpm5_stl3": "5+ 3PM & 3+ STL", "tpm5_blk3": "5+ 3PM & 3+ BLK", "tpm8_ast5": "8+ 3PM & 5+ AST", "tpm8_reb5": "8+ 3PM & 5+ REB", "tpm3_ast10": "3+ 3PM & 10+ AST", "tpm3_stl3": "3+ 3PM & 3+ STL", "tpm3_blk3": "3+ 3PM & 3+ BLK", "pts45_reb10": "45+ PTS & 10+ REB", "pts45_ast10": "45+ PTS & 10+ AST", "pts45_tpm5": "45+ PTS & 5+ 3PM", "pts35_reb10": "35+ PTS & 10+ REB", "pts35_reb15": "35+ PTS & 15+ REB", "pts35_blk3": "35+ PTS & 3+ BLK", "pts35_stl3": "35+ PTS & 3+ STL", "pts35_tpm5": "35+ PTS & 5+ 3PM", "pts15_blk3": "15+ PTS & 3+ BLK", "pts15_blk5": "15+ PTS & 5+ BLK", "pts15_stl3": "15+ PTS & 3+ STL", "pts15_stl5": "15+ PTS & 5+ STL", "pts15_tpm5": "15+ PTS & 5+ 3PM", "ast5_blk3": "5+ AST & 3+ BLK", "ast5_blk5": "5+ AST & 5+ BLK", "ast5_stl3": "5+ AST & 3+ STL", "ast5_stl5": "5+ AST & 5+ STL", "ast10_blk2": "10+ AST & 2+ BLK", "ast10_stl2": "10+ AST & 2+ STL", "reb10_blk3": "10+ REB & 3+ BLK", "reb10_stl3": "10+ REB & 3+ STL", "reb10_ast5": "10+ REB & 5+ AST", "reb10_tpm3": "10+ REB & 3+ 3PM", "stl2_blk2": "2+ STL & 2+ BLK", "stl2_blk3": "2+ STL & 3+ BLK", "stl3_blk2": "3+ STL & 2+ BLK", "stl4_blk2": "4+ STL & 2+ BLK", "stl2_blk4": "2+ STL & 4+ BLK", "pts25_ast5_stl3": "25+ PTS, 5+ AST & 3+ STL", "pts25_ast5_blk3": "25+ PTS, 5+ AST & 3+ BLK", "pts30_ast5_stl3": "30+ PTS, 5+ AST & 3+ STL", "pts30_ast5_blk3": "30+ PTS, 5+ AST & 3+ BLK", "pts20_reb5_stl3": "20+ PTS, 5+ REB & 3+ STL", "pts20_reb5_blk3": "20+ PTS, 5+ REB & 3+ BLK", "pts15_reb10_blk3": "15+ PTS, 10+ REB & 3+ BLK", "pts15_reb10_ast5": "15+ PTS, 10+ REB & 5+ AST", "pts15_ast10_stl3": "15+ PTS, 10+ AST & 3+ STL", "reb10_ast5_blk3": "10+ REB, 5+ AST & 3+ BLK", "reb10_ast5_stl3": "10+ REB, 5+ AST & 3+ STL", "ast5_stl3_blk3": "5+ AST, 3+ STL & 3+ BLK", "pts20_reb10_ast5_stl2": "20+ PTS, 10+ REB, 5+ AST & 2+ STL", "pts20_reb10_ast5_blk2": "20+ PTS, 10+ REB, 5+ AST & 2+ BLK", "pts20_reb5_ast5_stl2_blk2": "20+ PTS, 5+ REB, 5+ AST, 2+ STL & 2+ BLK", "pts15_reb10_ast5_blk3": "15+ PTS, 10+ REB, 5+ AST & 3+ BLK", "pts15_reb5_ast5_stl3_blk3": "15+ PTS, 5+ REB, 5+ AST, 3+ STL & 3+ BLK"}

def _build_check(key):
    parts=key.split("_");conditions=[];i=0
    while i<len(parts):
        if parts[i]=="5x5": return lambda p,r,a,s,b,t:all(v>=5 for v in [p,r,a,s,b])
        stat=parts[i];val=int(parts[i+1]) if i+1<len(parts) and parts[i+1].isdigit() else None
        if val is None:
            for px in ["pts","reb","ast","stl","blk","tpm"]:
                if stat.startswith(px): val=int(stat[len(px):]); stat=px; break
            i+=1
        else: i+=2
        m={"pts":"p","reb":"r","ast":"a","stl":"s","blk":"b","tpm":"t"}
        if stat in m: conditions.append((m[stat],val))
    return lambda p,r,a,s,b,t,c=conditions:all({"p":p,"r":r,"a":a,"s":s,"b":b,"t":t}[x[0]]>=x[1] for x in c)

COMPOUND_CHECKS = {k: _build_check(k) for k in COMPOUND_LABELS}
AGE_FEATS = {
    "pts40":("40+ PTS",lambda p,r,a,s,b,t:p>=40),
    "pts50":("50+ PTS",lambda p,r,a,s,b,t:p>=50),
    "td":("triple-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=3),
    "dd":("double-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=2),
    "reb20":("20+ REB",lambda p,r,a,s,b,t:r>=20),
    "ast15":("15+ AST",lambda p,r,a,s,b,t:a>=15),
    "blk5":("5+ BLK",lambda p,r,a,s,b,t:b>=5),
    "stl5":("5+ STL",lambda p,r,a,s,b,t:s>=5),
    "5x5":("5x5",lambda p,r,a,s,b,t:all(v>=5 for v in [p,r,a,s,b])),
}


def filter_label(fk):
    if fk == "all": return ""
    cat, val = fk.split(":", 1)
    if cat == "country": return f"by a {val} player"
    if cat == "college": return f"by a {val} alum"
    if cat == "state": return f"by a player from {val}"
    if cat == "pos": return f"by a {val}"
    if cat == "team": return f"as a member of the {val}"
    return ""


def load_baseline():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BASELINE_FILE)
    with gzip.open(path, "rb") as f:
        data = json.loads(f.read())
    print(f"Baseline: {len(data['records'])} record groups")
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
    games = []; i = 0
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


def detect_alerts(bl, games):
    records = bl["records"]; streak_records = bl["streak_records"]
    streaks_cur = bl.get("streaks_current", {}); compound_hist = bl.get("compound_history", {})
    age_recs = bl.get("age_records", {}); bio = bl["bio"]
    valid_groups = set(bl.get("valid_groups", []))

    def get_fkeys(name, team=None):
        keys = ["all"]; b = bio.get(name, {})
        for cat, val in [("country", b.get("country")), ("college", b.get("college")),
                         ("state", b.get("state")), ("pos", b.get("pos"))]:
            if val:
                k = f"{cat}:{val}"
                if k in valid_groups: keys.append(k)
        if team:
            tn = NICK_TO_TEAM.get(team)
            if tn:
                k = f"team:{tn}"
                if k in valid_groups: keys.append(k)
        return keys

    alerts = {}; count = 0
    for date_str, g in games:
        dt = g["dt"]; iso = dt.strftime("%Y-%m-%d"); name = g["player"]
        pts, reb, ast, stl, blk, tpm = g["pts"], g["reb"], g["ast"], g["stl"], g["blk"], g["tpm"]
        team = g["team"]; opp = g.get("opp", "")
        fkeys = get_fkeys(name, team)
        line = f"{pts} PTS, {reb} REB, {ast} AST"
        if stl >= 3 or blk >= 3 or tpm >= 5: line += f", {stl} STL, {blk} BLK, {tpm} 3PM"
        bday = parse_bday(bio.get(name, {}).get("bday", ""))
        p_age = age_at_date(bday, dt)
        day = []

        # 1. Single-game records
        sv = {"game_pts":pts,"game_reb":reb,"game_ast":ast,"game_stl":stl,"game_blk":blk,"game_tpm":tpm}
        for fk in fkeys:
            if fk == "all": continue
            for stat, val in sv.items():
                if val < GAME_MINS.get(stat, 0): continue
                rec = records.get(fk, {}).get(stat, {})
                ov = rec.get("value", 0); op = rec.get("player", "")
                if val > ov and ov > 0:
                    fl = filter_label(fk); sl = GAME_STATS[stat]
                    if op == name:
                        text = f"New personal record: Most {sl} in a game {fl} ({val}), surpassing own record of {ov}"
                        pri = 2
                    else:
                        text = f"🏆 NEW RECORD: Most {sl} in a game {fl} ({val}), breaking {op}'s record of {ov} ({rec.get('date', '')})"
                        pri = 1
                    day.append({"type": "record", "player": name, "team": team, "opp": opp, "line": line, "alert": text, "_p": pri})
                    if fk not in records: records[fk] = {}
                    records[fk][stat] = {"value": val, "player": name, "date": iso, "season": 2026}

        # 2. Age records
        if p_age and 15 < p_age < 50:
            for afk, (al, ac) in AGE_FEATS.items():
                if not ac(pts, reb, ast, stl, blk, tpm): continue
                for fk in fkeys:
                    if fk not in age_recs: age_recs[fk] = {}
                    if afk not in age_recs[fk]:
                        age_recs[fk][afk] = {"youngest": {"age": 99, "player": "", "date": ""},
                                              "oldest": {"age": 0, "player": "", "date": ""}}
                    ar = age_recs[fk][afk]; fl = filter_label(fk) if fk != "all" else ""
                    if p_age < ar["youngest"]["age"]:
                        old = ar["youngest"]
                        if old["player"] and old["player"] != name:
                            text = f"👶 YOUNGEST: {al} {fl} at {age_str(p_age)}, younger than {old['player']} ({age_str(old['age'])})"
                            day.append({"type": "record", "player": name, "team": team, "opp": opp, "line": line, "alert": text, "_p": 1})
                        ar["youngest"] = {"age": p_age, "player": name, "date": iso}
                    if p_age > ar["oldest"]["age"]:
                        old = ar["oldest"]
                        if old["player"] and old["player"] != name:
                            text = f"🧓 OLDEST: {al} {fl} at {age_str(p_age)}, older than {old['player']} ({age_str(old['age'])})"
                            day.append({"type": "record", "player": name, "team": team, "opp": opp, "line": line, "alert": text, "_p": 1})
                        ar["oldest"] = {"age": p_age, "player": name, "date": iso}

        # 3. Streaks
        if name not in streaks_cur: streaks_cur[name] = {}
        for sk, (sl, cf) in STREAK_CHECKS.items():
            streaks_cur[name][sk] = streaks_cur[name].get(sk, 0) + 1 if cf(pts, reb, ast, stl, blk, tpm) else 0
            cur = streaks_cur[name][sk]
            if cur < 5: continue
            for fk in fkeys:
                if fk == "all": continue
                sr = streak_records.get(fk, {}).get(sk, {})
                ov = sr.get("value", 0); op = sr.get("player", "")
                if cur > ov:
                    if op != name:
                        fl = filter_label(fk)
                        text = f"🔥 STREAK RECORD: {cur} consecutive games with {sl} {fl}, breaking {op}'s record of {ov}"
                        day.append({"type": "streak_record", "player": name, "team": team, "opp": opp, "line": line, "alert": text, "_p": 1})
                    elif cur % 25 == 0:
                        fl = filter_label(fk)
                        text = f"🔥 STREAK: {cur} consecutive games with {sl} {fl} (extending own record)"
                        day.append({"type": "streak_extend", "player": name, "team": team, "opp": opp, "line": line, "alert": text, "_p": 3})
                    if fk not in streak_records: streak_records[fk] = {}
                    streak_records[fk][sk] = {"value": cur, "player": name, "date": iso}

        # 4. Compound first-ever
        for ck, cf in COMPOUND_CHECKS.items():
            if not cf(pts, reb, ast, stl, blk, tpm): continue
            for fk in fkeys:
                if fk == "all": continue
                ch = compound_hist.get(fk, {}).get(ck, {})
                if ch.get("count", 0) == 0:
                    fl = filter_label(fk); cl = COMPOUND_LABELS[ck]
                    text = f"⭐ FIRST EVER: {cl} game {fl}"
                    day.append({"type": "first_ever", "player": name, "team": team, "opp": opp, "line": line, "alert": text, "_p": 1})
                if fk not in compound_hist: compound_hist[fk] = {}
                if ck not in compound_hist[fk]: compound_hist[fk][ck] = {"count": 0, "last": None}
                compound_hist[fk][ck]["count"] += 1

        # Dedup
        if day:
            seen = set(); dd = []
            for a in sorted(day, key=lambda x: x.get("_p", 9)):
                k = (a["player"], a["alert"][:80])
                if k not in seen: seen.add(k); dd.append(a)
            for a in dd: a.pop("_p", None)
            if iso not in alerts: alerts[iso] = []
            alerts[iso].extend(dd); count += len(dd)

    print(f"  {count} alerts across {len(alerts)} dates")
    return alerts


def main():
    print("=" * 56)
    print("  NBA RECORD ALERTS — Update Script")
    print("=" * 56)
    bl = load_baseline()
    games = fetch_2526()
    alerts = detect_alerts(bl, games)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(path, "w") as f:
        json.dump(alerts, f, separators=(",", ":"))
    print(f"\nSaved {OUTPUT_FILE} ({os.path.getsize(path)/1024:.0f} KB)")
    for d in sorted(alerts.keys(), reverse=True)[:3]:
        print(f"\n  {d}:")
        for a in alerts[d][:3]:
            print(f"    {a['player']}: {a['alert'][:80]}")
    print("\nDone!")

if __name__ == "__main__":
    main()
