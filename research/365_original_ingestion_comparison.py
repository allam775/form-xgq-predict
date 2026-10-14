"""Compare original XGQ website 365Scores ingestion with eight unresolved fixtures.

Legacy source: allam775/xgq-project-365/server.py, fetch_365_game_bundle
and normalize_365_shot. Compare gameId-only to gameId+matchupId, and the
original per-shot xG precedence, against private independently fetched stats.

NO browser impersonation, guessed fixtures, broad endpoint discovery, raw
event storage, aggregate-to-XGQ approximation or production modifications.
Private D1 stores comparison outcomes; public artifact only counts.
"""
from __future__ import annotations
import importlib,json,math,time
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError,URLError
from engine import provider365 as p
from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized
from engine.competition365 import resolve

base=importlib.import_module("research.365_stats_completeness_batch")
OUT=Path("research/reports/365_original_ingestion_comparison.json")
KEYS=("xg","xG","expectedGoals","expectedGoal","expected_goals","expectedGoalsValue","xGValue")

def legacy_xg(event):
    """Old server.py order: ALL top-level names before nested shot aliases."""
    shot=event.get("shot") if isinstance(event.get("shot"),dict) else {}
    for obj in (event,shot):
        for k in KEYS:
            v=obj.get(k)
            if v is None or v=="":continue
            if isinstance(v,bool):return None
            if isinstance(v,str):v=v.strip().replace(",",".")
            try:n=float(v)
            except (TypeError,ValueError):return None
            return n if math.isfinite(n) and 0<=n<=1 else None
    return None

def group_legacy(game):
    """Reimplement only the old safe shot normalization, NOT its approximations."""
    home=p._side(game,"home");away=p._side(game,"away")
    hid=str(home.get("id") or home.get("competitorId") or "")
    aid=str(away.get("id") or away.get("competitorId") or "")
    if not hid or not aid or hid==aid:raise ValueError("bad_competitor_id")
    ev=game.get("chartEvents") or game.get("chart_events")
    if isinstance(ev,dict):ev=ev.get("events") or ev.get("chartEvents") or ev.get("items")
    if not isinstance(ev,list) or not ev or len(ev)>500:
        raise ValueError("bad_chart")
    # The legacy site enriches player-only events from both team lineups.
    members={}
    def walk(node,side,depth=0):
        if depth>7:return
        if isinstance(node,list):
            for v in node[:40]:walk(v,side,depth+1)
        elif isinstance(node,dict):
            m=node.get("player") if isinstance(node.get("player"),dict) else node
            mid=m.get("id") or m.get("memberId") or m.get("playerId")
            if mid is not None:
                key=str(mid);old=members.get(key)
                members[key]=side if old in (None,side) else "ambiguous"
            for v in node.values():
                if isinstance(v,(dict,list)):walk(v,side,depth+1)
    walk(home.get("lineups"),"home")
    walk(away.get("lineups"),"away")
    groups={"home":[],"away":[]}
    diff=0;inferred=0;unreadable=0
    for e in ev:
        if not isinstance(e,dict) or not p._is_shot(e):continue
        v=legacy_xg(e)
        new=p._xg(e)
        if v is None or new is None:
            unreadable+=1
            continue
        if abs(v-new)>1e-9:diff+=1
        obj=e.get("competitor") if isinstance(e.get("competitor"),dict) else {}
        team=e.get("team") if isinstance(e.get("team"),dict) else {}
        direct=str(e.get("competitorId") or e.get("competitorID")
              or e.get("teamId") or e.get("team_id") or e.get("participantId")
              or obj.get("id") or team.get("id") or "")
        if direct==hid:side="home"
        elif direct==aid:side="away"
        elif e.get("competitorNum") in (1,2):
            side="home" if e["competitorNum"]==1 else "away"
        elif type(e.get("isHome")) is bool:
            side="home" if e["isHome"] else "away"
        else:
            player=e.get("playerId") or e.get("memberId") or e.get("athleteId")
            side=members.get(str(player))
            if side not in groups:
                unreadable+=1
                continue
            inferred+=1
        groups[side].append(v)
    return groups,{"different_per_shot_xg":diff,"lineup_side_inferences":inferred,
                   "skipped_ambiguous_events":unreadable}

def compare_detail(payload,row,stats):
    g=payload.get("game",payload) if isinstance(payload,dict) else None
    if not isinstance(g,dict) or p._game_id(g)!=row["source_match_id"] or not p._final(g):
        raise ValueError("detail_does_not_match_requested_finished_game")
    c=resolve(payload)
    if not c["ok"] or c["league"]!=row["league"] or c["provider_competition_id"]!=row["competition_id"]:
        raise ValueError("detail_competition_disagreement")
    if p._date(g)!=row["date"]:raise ValueError("date_changed")
    h=p._side(g,"home");a=p._side(g,"away")
    if any((
        normalized(h.get("name"))!=normalized(row["home"]),
        normalized(a.get("name"))!=normalized(row["away"]),
        p._score(g,"home",h)!=row["hg"],
        p._score(g,"away",a)!=row["ag"]
    )):
        raise ValueError("detail_score_or_team_disagreement")
    samples,flags=group_legacy(g)
    sides={}
    for side in ("home","away"):
        xs=samples[side]
        if not xs:raise ValueError("empty_shot_side")
        n=stats[side]["shots"];v=stats[side]["xg"]
        prec=stats[side]["xg_display_decimals"]
        tolerance=.005*len(xs)+.5*10**(-prec)+1e-9
        sides[side]={"count_delta":len(xs)-n,"total_xg_agrees":abs(sum(xs)-v)<=tolerance,
                    "xg_sum":round(sum(xs),6),"shots":len(xs)}
    return {"ok":all(z["count_delta"]==0 and z["total_xg_agrees"] for z in sides.values()),
            "sides":sides,**flags}

def unresolved(db):
    rows=base.candidates(db);old=base.prior_audits(db)
    repaired={str(r["id"]) for r in
              db.query("SELECT id FROM private_365_repair_acceptance LIMIT 50")}
    failed={mid:v for mid,v in rows.items()
            if mid in old and old[mid].get("complete") is False}
    rem={mid:v for mid,v in failed.items() if mid not in repaired}
    if len(failed)!=11 or len(repaired)!=3 or len(rem)!=8:
        raise ValueError("expected_original_eleven_minus_three")
    return rem

def run(db=None,transport=None,delay=1.5):
    d=db if db is not None else D1()
    work=unresolved(d)
    d.query("""CREATE TABLE IF NOT EXISTS private_365_original_bundle_diagnostic(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    fetcher=transport if transport is not None else p.fetch
    result={"original_source":"allam775/xgq-project-365/server.py",
        "cases":8,"calls":0,"compared":0,"alone_reconciled":0,
        "matchup_reconciled":0,"either_reconciled":0,
        "shot_count_different_by_bundle":0,"xg_sum_different_by_bundle":0,
        "legacy_parser_xg_disagreements":0,"legacy_lineup_side_fallbacks":0,
        "no_verified_change":True,"training_changed":False,
        "provider_payloads_published":False,"outcomes":{},"status":"complete"}
    reasons=Counter()
    for mid,old in sorted(work.items()):
        witness_rows=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
        if len(witness_rows)!=1:
            reasons["missing_private_independent_statistics"]+=1;continue
        independent=json.loads(witness_rows[0]["payload"])["source_stats"]
        try:
            regular=fetcher("game/",{"gameId":mid,"topBookmaker":"14"})
            result["calls"]+=1
            b=compare_detail(regular,old,independent)
            g=regular.get("game",regular);h=p._side(g,"home");a=p._side(g,"away")
            hid=h.get("id") or h.get("competitorId")
            aid=a.get("id") or a.get("competitorId")
            if not hid or not aid:raise ValueError("matchup_teams_missing")
            matchup=f"{hid}-{aid}-{old['competition_id']}"
            if transport is None:time.sleep(delay)
            alternate=fetcher("game/",{"gameId":mid,"matchupId":matchup,"topBookmaker":"14"})
            result["calls"]+=1
            alt=compare_detail(alternate,old,independent)
            result["compared"]+=1
            result["alone_reconciled"]+=int(b["ok"])
            result["matchup_reconciled"]+=int(alt["ok"])
            result["either_reconciled"]+=int(b["ok"] or alt["ok"])
            result["legacy_parser_xg_disagreements"]+=b["different_per_shot_xg"]
            result["legacy_lineup_side_fallbacks"]+=b["lineup_side_inferences"]
            for side in ("home","away"):
                if b["sides"][side]["shots"]!=alt["sides"][side]["shots"]:
                    result["shot_count_different_by_bundle"]+=1
                if abs(b["sides"][side]["xg_sum"]-alt["sides"][side]["xg_sum"])>1e-6:
                    result["xg_sum_different_by_bundle"]+=1
            # Match-level audit STAYS PRIVATE; no live raw provider shots stored.
            private={"regular_ok":b["ok"],"matchup_ok":alt["ok"],
                "regular_count_deltas":{s:b["sides"][s]["count_delta"] for s in ("home","away")},
                "matchup_count_deltas":{s:alt["sides"][s]["count_delta"] for s in ("home","away")},
                "regular_xg_agrees":{s:b["sides"][s]["total_xg_agrees"] for s in ("home","away")},
                "matchup_xg_agrees":{s:alt["sides"][s]["total_xg_agrees"] for s in ("home","away")}}
            d.query("INSERT OR REPLACE INTO private_365_original_bundle_diagnostic(id,payload) VALUES(?,?)",
                    (mid,json.dumps(private,separators=(",",":"))))
            if transport is None:time.sleep(delay)
        except p.AccessDenied:
            result["status"]="provider_denied_stopped";reasons["denied"]+=1;break
        except HTTPError as e:
            reasons[f"http_{e.code}"]+=1
            if e.code in (401,403,429):
                result["status"]="provider_denied_stopped";break
        except (URLError,TimeoutError,D1Error,ValueError,TypeError,KeyError) as e:
            reasons[(str(e)[:65] if isinstance(e,ValueError) else type(e).__name__)]+=1
    result["outcomes"]=dict(sorted(reasons.items()))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))
    return result

if __name__=="__main__":run()
