#!/usr/bin/env python3
"""
NBA Record Alerts — Nightly Update v6
Detects: records, age records, streaks, compound first-evers,
         career highs, first-since feats, NBA debuts.
"""
import csv, gzip, io, json, os, sys
from datetime import datetime, timedelta
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

def age_at_date(bday, gd):
    if not bday or not gd: return None
    return round((gd - bday).days / 365.25, 2)

def age_str(a):
    yrs = int(a); days = int((a - yrs) * 365.25)
    return f"{yrs} years, {days} days"

def excel_to_date(serial):
    try:
        s = int(float(serial))
        if s < 1 or s > 100000: return None
        return datetime(1899, 12, 30) + timedelta(days=s)
    except: return None

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

AGE_FEATS = {
    "pts40":("40+ PTS",lambda p,r,a,s,b,t:p>=40),"pts50":("50+ PTS",lambda p,r,a,s,b,t:p>=50),
    "td":("triple-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=3),
    "dd":("double-double",lambda p,r,a,s,b,t:sum(1 for v in [p,r,a,s,b] if v>=10)>=2),
    "reb20":("20+ REB",lambda p,r,a,s,b,t:r>=20),"ast15":("15+ AST",lambda p,r,a,s,b,t:a>=15),
    "blk5":("5+ BLK",lambda p,r,a,s,b,t:b>=5),"stl5":("5+ STL",lambda p,r,a,s,b,t:s>=5),
    "5x5":("5x5",lambda p,r,a,s,b,t:all(v>=5 for v in [p,r,a,s,b])),
}

FIRST_SINCE_FEATS = {
    "pts50":("50+ PTS",lambda p,r,a,s,b,t:p>=50),"pts60":("60+ PTS",lambda p,r,a,s,b,t:p>=60),
    "reb20":("20+ REB",lambda p,r,a,s,b,t:r>=20),"ast20":("20+ AST",lambda p,r,a,s,b,t:a>=20),
    "stl7":("7+ STL",lambda p,r,a,s,b,t:s>=7),"blk7":("7+ BLK",lambda p,r,a,s,b,t:b>=7),
    "tpm10":("10+ 3PM",lambda p,r,a,s,b,t:t>=10),
    "5x5":("5x5",lambda p,r,a,s,b,t:all(v>=5 for v in [p,r,a,s,b])),
    "pts40_reb15":("40+ PTS & 15+ REB",lambda p,r,a,s,b,t:p>=40 and r>=15),
    "pts40_ast10":("40+ PTS & 10+ AST",lambda p,r,a,s,b,t:p>=40 and a>=10),
    "pts30_reb10_ast10":("30-10-10",lambda p,r,a,s,b,t:p>=30 and r>=10 and a>=10),
}

CH_LABELS = {"pts":"points","reb":"rebounds","ast":"assists","stl":"steals","blk":"blocks","tpm":"3-pointers"}
CH_MINS = {"pts":30,"reb":15,"ast":12,"stl":5,"blk":5,"tpm":6}

# Compound checks: built dynamically from labels
COMPOUND_LABELS = {"pts25_reb10":"25+ PTS & 10+ REB","pts30_reb10":"30+ PTS & 10+ REB","pts30_reb15":"30+ PTS & 15+ REB","pts40_reb10":"40+ PTS & 10+ REB","pts40_reb15":"40+ PTS & 15+ REB","pts25_ast10":"25+ PTS & 10+ AST","pts30_ast10":"30+ PTS & 10+ AST","pts30_ast15":"30+ PTS & 15+ AST","pts35_ast10":"35+ PTS & 10+ AST","pts40_ast10":"40+ PTS & 10+ AST","pts20_blk5":"20+ PTS & 5+ BLK","pts25_blk5":"25+ PTS & 5+ BLK","pts30_blk5":"30+ PTS & 5+ BLK","pts20_stl5":"20+ PTS & 5+ STL","pts25_stl5":"25+ PTS & 5+ STL","pts30_stl5":"30+ PTS & 5+ STL","pts30_tpm5":"30+ PTS & 5+ 3PM","pts30_tpm8":"30+ PTS & 8+ 3PM","pts40_tpm5":"40+ PTS & 5+ 3PM","ast10_reb10":"10+ AST & 10+ REB","ast15_reb10":"15+ AST & 10+ REB","ast10_blk3":"10+ AST & 3+ BLK","ast10_blk5":"10+ AST & 5+ BLK","ast10_stl3":"10+ AST & 3+ STL","ast10_stl5":"10+ AST & 5+ STL","reb15_blk3":"15+ REB & 3+ BLK","reb15_blk5":"15+ REB & 5+ BLK","reb10_blk5":"10+ REB & 5+ BLK","reb15_stl3":"15+ REB & 3+ STL","stl3_blk3":"3+ STL & 3+ BLK","stl5_blk3":"5+ STL & 3+ BLK","pts20_reb10_ast10":"20-10-10","pts25_reb10_ast10":"25-10-10","pts30_reb10_ast10":"30-10-10","pts30_reb10_ast5":"30+ PTS, 10+ REB & 5+ AST","pts20_reb10_blk3":"20+ PTS, 10+ REB & 3+ BLK","pts20_ast10_stl3":"20+ PTS, 10+ AST & 3+ STL","pts20_reb5_ast5_stl3":"20+ PTS, 5+ REB, 5+ AST & 3+ STL","pts20_reb5_ast5_blk3":"20+ PTS, 5+ REB, 5+ AST & 3+ BLK","pts50":"50+ PTS","pts60":"60+ PTS","reb20":"20+ REB","ast15":"15+ AST","ast20":"20+ AST","stl5":"5+ STL","stl7":"7+ STL","blk5":"5+ BLK","blk7":"7+ BLK","tpm8":"8+ 3PM","tpm10":"10+ 3PM","5x5":"5x5","tpm5_ast10":"5+ 3PM & 10+ AST","tpm5_reb10":"5+ 3PM & 10+ REB","tpm5_stl3":"5+ 3PM & 3+ STL","tpm5_blk3":"5+ 3PM & 3+ BLK","tpm8_ast5":"8+ 3PM & 5+ AST","tpm8_reb5":"8+ 3PM & 5+ REB","tpm3_ast10":"3+ 3PM & 10+ AST","tpm3_stl3":"3+ 3PM & 3+ STL","tpm3_blk3":"3+ 3PM & 3+ BLK","pts45_reb10":"45+ PTS & 10+ REB","pts45_ast10":"45+ PTS & 10+ AST","pts45_tpm5":"45+ PTS & 5+ 3PM","pts35_reb10":"35+ PTS & 10+ REB","pts35_reb15":"35+ PTS & 15+ REB","pts35_blk3":"35+ PTS & 3+ BLK","pts35_stl3":"35+ PTS & 3+ STL","pts35_tpm5":"35+ PTS & 5+ 3PM","pts15_blk3":"15+ PTS & 3+ BLK","pts15_blk5":"15+ PTS & 5+ BLK","pts15_stl3":"15+ PTS & 3+ STL","pts15_stl5":"15+ PTS & 5+ STL","pts15_tpm5":"15+ PTS & 5+ 3PM","ast5_blk3":"5+ AST & 3+ BLK","ast5_blk5":"5+ AST & 5+ BLK","ast5_stl3":"5+ AST & 3+ STL","ast5_stl5":"5+ AST & 5+ STL","ast10_blk2":"10+ AST & 2+ BLK","ast10_stl2":"10+ AST & 2+ STL","reb10_blk3":"10+ REB & 3+ BLK","reb10_stl3":"10+ REB & 3+ STL","reb10_ast5":"10+ REB & 5+ AST","reb10_tpm3":"10+ REB & 3+ 3PM","stl2_blk2":"2+ STL & 2+ BLK","stl2_blk3":"2+ STL & 3+ BLK","stl3_blk2":"3+ STL & 2+ BLK","stl4_blk2":"4+ STL & 2+ BLK","stl2_blk4":"2+ STL & 4+ BLK","pts25_ast5_stl3":"25+ PTS, 5+ AST & 3+ STL","pts25_ast5_blk3":"25+ PTS, 5+ AST & 3+ BLK","pts30_ast5_stl3":"30+ PTS, 5+ AST & 3+ STL","pts30_ast5_blk3":"30+ PTS, 5+ AST & 3+ BLK","pts20_reb5_stl3":"20+ PTS, 5+ REB & 3+ STL","pts20_reb5_blk3":"20+ PTS, 5+ REB & 3+ BLK","pts15_reb10_blk3":"15+ PTS, 10+ REB & 3+ BLK","pts15_reb10_ast5":"15+ PTS, 10+ REB & 5+ AST","pts15_ast10_stl3":"15+ PTS, 10+ AST & 3+ STL","reb10_ast5_blk3":"10+ REB, 5+ AST & 3+ BLK","reb10_ast5_stl3":"10+ REB, 5+ AST & 3+ STL","ast5_stl3_blk3":"5+ AST, 3+ STL & 3+ BLK","pts20_reb10_ast5_stl2":"20+ PTS, 10+ REB, 5+ AST & 2+ STL","pts20_reb10_ast5_blk2":"20+ PTS, 10+ REB, 5+ AST & 2+ BLK","pts20_reb5_ast5_stl2_blk2":"20+ PTS, 5+ REB, 5+ AST, 2+ STL & 2+ BLK","pts15_reb10_ast5_blk3":"15+ PTS, 10+ REB, 5+ AST & 3+ BLK","pts15_reb5_ast5_stl3_blk3":"15+ PTS, 5+ REB, 5+ AST, 3+ STL & 3+ BLK"}

def _build_check(key):
    if key == "5x5": return lambda p,r,a,s,b,t: all(v>=5 for v in [p,r,a,s,b])
    parts = key.split("_"); conds = []; i = 0
    while i < len(parts):
        stat = parts[i]
        val = int(parts[i+1]) if i+1 < len(parts) and parts[i+1].isdigit() else None
        if val is None:
            for px in ["pts","reb","ast","stl","blk","tpm"]:
                if stat.startswith(px): val = int(stat[len(px):]); stat = px; break
            i += 1
        else: i += 2
        m = {"pts":"p","reb":"r","ast":"a","stl":"s","blk":"b","tpm":"t"}
        if stat in m: conds.append((m[stat], val))
    return lambda p,r,a,s,b,t,c=conds: all({"p":p,"r":r,"a":a,"s":s,"b":b,"t":t}[x[0]] >= x[1] for x in c)

COMPOUND_CHECKS = {k: _build_check(k) for k in COMPOUND_LABELS}


def filter_label(fk):
    if fk == "all": return ""
    cat, val = fk.split(":", 1)
    return {"country": f"by a player from {val}", "birth_country": f"by a player born in {val}",
            "college": f"by a {val} alum",
            "state": f"by a player from {val}", "pos": f"by a {val}",
            "team": f"as a member of the {val}"}.get(cat, "")


def load_baseline():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BASELINE_FILE)
    with gzip.open(path, "rb") as f:
        data = json.loads(f.read())
    print(f"Baseline: {len(data['records'])} groups, {len(data.get('players_ever',[]))} historical players")
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
    players_ever = set(bl.get("players_ever", []))
    career_highs = bl.get("career_highs", {})

    # Build historical-only career highs and first-since tracking
    # (career_highs in baseline includes 2025-26 — we need pre-season values)
    # We use compound_history's "last" field for first-since from the baseline
    # which was built from ALL data. For proper first-since we need the last
    # occurrence tracking to start from the baseline state.
    season_compound_last = {}
    # Initialize from compound_history's last occurrences
    for fk in compound_hist:
        for ck in compound_hist[fk]:
            last = compound_hist[fk][ck].get("last")
            if last:
                # Map compound keys to first_since keys where applicable
                for fsk in FIRST_SINCE_FEATS:
                    if fsk == ck or (fsk in COMPOUND_LABELS and fsk == ck):
                        if fk not in season_compound_last: season_compound_last[fk] = {}
                        season_compound_last[fk][fsk] = {"player": last.get("player",""), "date": last.get("date","")}

    # For career highs: use the baseline values (includes 2025-26)
    # But for detection, we need pre-season values. Since we process games in order,
    # we track running career highs starting from 0 for new players.
    season_ch = {}
    for name, ch in career_highs.items():
        season_ch[name] = dict(ch)

    def get_fkeys(name, team=None):
        keys = ["all"]; b = bio.get(name, {})
        for cat, val in [("country", b.get("country")), ("birth_country", b.get("birth_country")),
                         ("college", b.get("college")),
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

    alerts = {}; count = 0; seen_season = set()

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

        # 0. DEBUT
        if name not in seen_season:
            seen_season.add(name)
            if name not in players_ever:
                b = bio.get(name, {}); bi = []
                if b.get("country") and b["country"] != "United States": bi.append(f"from {b['country']}")
                if b.get("birth_country"): bi.append(f"born in {b['birth_country']}")
                if b.get("college"): bi.append(b["college"])
                if b.get("state"): bi.append(b["state"])
                bs = " · ".join(bi) if bi else ""
                tn = NICK_TO_TEAM.get(team, team)
                ai = f" ({age_str(p_age)})" if p_age else ""
                day.append({"type": "first_ever", "player": name, "team": team, "opp": opp, "line": line,
                    "alert": f"🌟 NBA DEBUT: {name} makes NBA debut for the {tn}{ai}" + (f" [{bs}]" if bs else ""), "_p": 0})

        # 1. CAREER HIGHS
        if name not in season_ch:
            season_ch[name] = {"pts":0,"reb":0,"ast":0,"stl":0,"blk":0,"tpm":0}
        ch = season_ch[name]
        for stat, val in [("pts",pts),("reb",reb),("ast",ast),("stl",stl),("blk",blk),("tpm",tpm)]:
            if val > ch[stat] and val >= CH_MINS.get(stat, 0):
                old = ch[stat]
                if old > 0:
                    day.append({"type": "record", "player": name, "team": team, "opp": opp, "line": line,
                        "alert": f"🎯 CAREER HIGH: {val} {CH_LABELS[stat]} (previous: {old})", "_p": 1})
                ch[stat] = val

        # 2. FIRST SINCE
        for fsk, (fsl, fsc) in FIRST_SINCE_FEATS.items():
            if not fsc(pts, reb, ast, stl, blk, tpm): continue
            for fk in fkeys:
                last = season_compound_last.get(fk, {}).get(fsk)
                fl = filter_label(fk) if fk != "all" else ""
                if last and last.get("player") and last["player"] != name:
                    try:
                        days_since = (dt - datetime.strptime(last["date"], "%Y-%m-%d")).days
                    except: days_since = 999
                    if days_since > 30:
                        day.append({"type": "first_ever", "player": name, "team": team, "opp": opp, "line": line,
                            "alert": f"📅 FIRST SINCE: {fsl} game {fl} — first since {last['player']} ({last['date']})", "_p": 2})
                if fk not in season_compound_last: season_compound_last[fk] = {}
                season_compound_last[fk][fsk] = {"player": name, "date": iso}

        # 3. SINGLE-GAME RECORDS
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
                        txt = f"New personal record: Most {sl} in a game {fl} ({val}), surpassing own record of {ov}"; pri = 2
                    else:
                        txt = f"🏆 NEW RECORD: Most {sl} in a game {fl} ({val}), breaking {op}'s record of {ov} ({rec.get('date', '')})"; pri = 1
                    day.append({"type": "record", "player": name, "team": team, "opp": opp, "line": line, "alert": txt, "_p": pri})
                    if fk not in records: records[fk] = {}
                    records[fk][stat] = {"value": val, "player": name, "date": iso}

        # 4. AGE RECORDS
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
                            day.append({"type": "record", "player": name, "team": team, "opp": opp, "line": line,
                                "alert": f"👶 YOUNGEST: {al} {fl} at {age_str(p_age)}, younger than {old['player']} ({age_str(old['age'])})", "_p": 1})
                        ar["youngest"] = {"age": p_age, "player": name, "date": iso}
                    if p_age > ar["oldest"]["age"]:
                        old = ar["oldest"]
                        if old["player"] and old["player"] != name:
                            day.append({"type": "record", "player": name, "team": team, "opp": opp, "line": line,
                                "alert": f"🧓 OLDEST: {al} {fl} at {age_str(p_age)}, older than {old['player']} ({age_str(old['age'])})", "_p": 1})
                        ar["oldest"] = {"age": p_age, "player": name, "date": iso}

        # 5. STREAKS
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
                        day.append({"type": "streak_record", "player": name, "team": team, "opp": opp, "line": line,
                            "alert": f"🔥 STREAK RECORD: {cur} consecutive games with {sl} {filter_label(fk)}, breaking {op}'s record of {ov}", "_p": 1})
                    elif cur % 25 == 0:
                        day.append({"type": "streak_extend", "player": name, "team": team, "opp": opp, "line": line,
                            "alert": f"🔥 STREAK: {cur} consecutive games with {sl} {filter_label(fk)} (extending own record)", "_p": 3})
                    if fk not in streak_records: streak_records[fk] = {}
                    streak_records[fk][sk] = {"value": cur, "player": name, "date": iso}

        # 6. COMPOUND FIRST-EVER
        for ck, cf in COMPOUND_CHECKS.items():
            if not cf(pts, reb, ast, stl, blk, tpm): continue
            for fk in fkeys:
                if fk == "all": continue
                ch2 = compound_hist.get(fk, {}).get(ck, {})
                if ch2.get("count", 0) == 0:
                    fl = filter_label(fk); cl = COMPOUND_LABELS[ck]
                    day.append({"type": "first_ever", "player": name, "team": team, "opp": opp, "line": line,
                        "alert": f"⭐ FIRST EVER: {cl} game {fl}", "_p": 1})
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
    print("  NBA RECORD ALERTS v6 — Update Script")
    print("=" * 56)
    bl = load_baseline()
    games = fetch_2526()
    alerts = detect_alerts(bl, games)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(path, "w") as f:
        json.dump(alerts, f, separators=(",", ":"))
    size = os.path.getsize(path) / 1024
    total = sum(len(v) for v in alerts.values())
    print(f"\nSaved {OUTPUT_FILE} ({size:.0f} KB, {total} alerts)")
    for d in sorted(alerts.keys(), reverse=True)[:3]:
        print(f"\n  {d}:")
        for a in alerts[d][:3]:
            print(f"    {a['player']}: {a['alert'][:90]}")
    print("\nDone! ✓")


if __name__ == "__main__":
    main()
