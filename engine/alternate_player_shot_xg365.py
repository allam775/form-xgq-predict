"""Find an explicitly sourced ALTERNATE per-shot xG field for last rejected game.

A correction is valid only if the event itself carries another genuine xG
alias (not xGOT) which, when substituted for ONE observed shot, reconciles:
  * every player's official shots AND individual xG,
  * both teams' official Total Shots AND reported xG,
  * unchanged match identity, score, date and verified competition.
No xG is ever inferred by subtraction or fabricated; no bounds are relaxed.
"""
from __future__ import annotations
import math
from engine import provider365 as p
from engine.player_shot_witness365 import (
    compare_players,_chart_side,_shooter,_near)
from engine.xgq import normalized

ALIASES=("xg","xG","expectedGoals","expectedGoal","expected_goals",
         "expectedGoalsValue","xGValue")

def _variants(event):
    data=[]
    shot=event.get("shot") if isinstance(event.get("shot"),dict) else {}
    for source,obj in (("event",event),("nested_shot",shot)):
        for key in ALIASES:
            v=obj.get(key)
            if isinstance(v,bool) or v is None:continue
            if isinstance(v,str):
                v=v.strip()
                if not v or v.count(".")>1:continue
            try:num=float(v)
            except (ValueError,TypeError):continue
            if math.isfinite(num) and 0<=num<=1:
                data.append((source+"."+key,num))
    return data

def _official_near(value,stat,count):
    p=stat["xg_display_decimals"]
    if type(p) is not int or not 0<=p<=5:return False
    tol=.005*count+.5*10**(-p)+1e-9
    return abs(value-stat["xg"])<=tol

def repair(candidate,game,stats,original_audit):
    fail=lambda x:{"ok":False,"reason":x}
    if (original_audit.get("complete") is not False or
        original_audit.get("status") not in
        ("home_xg_mismatch","away_xg_mismatch")):
        return fail("not_an_original_xg_only_rejection")
    if candidate.get("catalog_verified") is not True:
        return fail("competition_not_reverified")
    proof=compare_players(game,stats)
    if proof["aggregate"]["unmapped_shots"] or any(
        proof["by_side"][s]["gaps"] or not proof["by_side"][s]["players_all_shots_match"]
        or proof["by_side"][s]["stat_shots_total"]!=stats[s]["shots"]
        for s in ("home","away")):
        return fail("player_shot_counts_or_attribution_disagree")
    bad=[]
    for side in ("home","away"):
        for pid,member in proof["by_side"][side]["members"].items():
            if member["stats_count"]==0:continue
            if member["stats_sum_xg"] is None:
                return fail("missing_player_expected_goals")
            if not _near(member["chart_sum_xg"],
                          {"xg":member["stats_sum_xg"],
                           "xg_precision":member["stats_xg_precision"]},
                          member["chart_count"]):
                bad.append((side,pid))
    if len(bad)!=1:
        return fail("not_one_isolated_player_xg_conflict")
    side,pid=bad[0]
    current=proof["by_side"][side]["members"][pid]
    h=p._side(game,"home");a=p._side(game,"away")
    hi=str(h.get("id") or h.get("competitorId") or "")
    ai=str(a.get("id") or a.get("competitorId") or "")
    chart=game.get("chartEvents") or game.get("chart_events")
    events=chart.get("events") or chart.get("items") if isinstance(chart,dict) else chart
    if not isinstance(events,list):return fail("invalid_event_chart")
    original_events=[]
    for e in events:
        if not isinstance(e,dict) or not p._is_shot(e):continue
        s=_chart_side(e,hi,ai)
        if s!=side:continue
        player=_shooter(e,{q:set(proof["by_side"][q]["members"])
                           for q in ("home","away")},side)
        if player==pid:original_events.append(e)
    if len(original_events)!=current["chart_count"]:
        return fail("live_player_events_changed_count")
    orig_sums={s:sum(v["chart_sum_xg"] for v in
                  proof["by_side"][s]["members"].values()) for s in ("home","away")}
    if any(abs(orig_sums[s]-candidate[s+"_chart_xg_sum"])>1e-6
           for s in ("home","away")):
        return fail("original_chart_xg_changed_since_capture")
    other="home" if side=="away" else "away"
    if not _official_near(orig_sums[other],stats[other],stats[other]["shots"]):
        return fail("other_team_xg_not_confirmed")
    options=[]
    for idx,e in enumerate(original_events):
        current_xg=p._xg(e)
        for field,new_xg in _variants(e):
            if abs(new_xg-current_xg)<1e-9:continue
            # Exclude xGOT fields by allowlist, no mathematical inferred values.
            player_sum=current["chart_sum_xg"]-current_xg+new_xg
            team_sum=orig_sums[side]-current_xg+new_xg
            if not _near(player_sum,
                         {"xg":current["stats_sum_xg"],
                          "xg_precision":current["stats_xg_precision"]},
                         current["stats_count"]):continue
            if not _official_near(team_sum,stats[side],stats[side]["shots"]):
                continue
            options.append((idx,current_xg,new_xg,field))
    if not options:
        return fail("no_alternate_observed_shot_xg_reconciles_player_and_team")
    # All allowable choices must produce the SAME XGQ. Otherwise ambiguous.
    original_squares=sum(v["xg"]**2 for member in proof["by_side"][side]["members"].values()
                         for v in member["shot_events"])
    qset={round((original_squares-old**2+new**2)/stats[side]["shots"],8)
          for _,old,new,_ in options}
    if len(qset)!=1:
        return fail("multiple_alternate_xg_replacements_yield_different_xgq")
    _,old,new,field=options[0]
    output={"league":candidate["league"],"date":candidate["date"],
         "home":candidate["home"],"away":candidate["away"],
         "hg":candidate["hg"],"ag":candidate["ag"],
         "source_match_id":candidate["source_match_id"],
         "source":"365Scores (opt-in; rights required)",
         "home_shots":stats["home"]["shots"],
         "away_shots":stats["away"]["shots"],
         "home_xg":round(orig_sums["home"]+(new-old if side=="home" else 0),6),
         "away_xg":round(orig_sums["away"]+(new-old if side=="away" else 0),6),
         "home_xgq":round(qset.pop(),8) if side=="home" else
                   round(sum(v["xg"]**2 for m in proof["by_side"]["home"]["members"].values()
                             for v in m["shot_events"])/stats["home"]["shots"],8),
         "away_xgq":round(qset.pop(),8) if side=="away" else
                   round(sum(v["xg"]**2 for m in proof["by_side"]["away"]["members"].values()
                             for v in m["shot_events"])/stats["away"]["shots"],8),
         "proof_tier":"OBSERVED_ALTERNATE_INDIVIDUAL_XG_PLAYER_AND_TEAM_MATCH",
         "alternate_provider_field":field,
         "individual_player_xg_reconciled":True,
         "official_team_xg_reconciled":True,
         "training_release":False}
    return {"ok":True,"reason":"alternate_source_xg_verified_without_inference",
            "private_row":output,"equivalent_replacements":len(options)}
