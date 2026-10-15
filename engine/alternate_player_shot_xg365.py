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


def repair_two_players(candidate,game,stats,original_audit):
    """Try two independently published player xG discrepancies simultaneously.

    At most one existing explicit alternative xG field is substituted PER
    discrepant player. Every candidate is checked against player's published
    xG and the two published team xG totals. Distinct possible resulting XGQ
    values fail closed. Does NOT infer a probability from an aggregate.
    """
    from itertools import product
    fail=lambda why,counts=None:{"ok":False,"reason":why,
                                 "explicit_alternative_counts":counts or []}
    if (original_audit.get("complete") is not False or
        original_audit.get("status") not in ("home_xg_mismatch","away_xg_mismatch")
        or candidate.get("catalog_verified") is not True):
        return fail("not_eligible_original_xg_only_rejection")
    evidence=compare_players(game,stats)
    if evidence["aggregate"]["unmapped_shots"] or evidence["aggregate"]["players_with_shot_gap"]:
        return fail("incomplete_player_shot_identity")
    if any(evidence["by_side"][s]["chart_shots_total"]!=stats[s]["shots"] or
           evidence["by_side"][s]["stat_shots_total"]!=stats[s]["shots"]
           for s in ("home","away")):
        return fail("team_player_shot_counts_not_equal")
    bad=[]
    orig_sums={s:0.0 for s in ("home","away")}
    orig_sq={s:0.0 for s in ("home","away")}
    for side in ("home","away"):
        for pid,m in evidence["by_side"][side]["members"].items():
            xs=m["shot_events"]
            if len(xs)!=m["stats_count"]:
                return fail("individual_player_shots_disagree")
            v=sum(e["xg"] for e in xs)
            orig_sums[side]+=v
            orig_sq[side]+=sum(e["xg"]**2 for e in xs)
            if m["stats_count"] and m["stats_sum_xg"] is None:
                return fail("independent_player_xg_absent")
            if m["stats_count"] and not _near(v,
                {"xg":m["stats_sum_xg"],"xg_precision":m["stats_xg_precision"]},
                m["stats_count"]):
                bad.append((side,pid,m))
        if abs(orig_sums[side]-candidate[side+"_chart_xg_sum"])>1e-6:
            return fail("original_chart_not_stable")
    if len(bad)!=2:
        return fail("not_exactly_two_discrepant_players")
    h=p._side(game,"home");a=p._side(game,"away")
    hi=str(h.get("id") or h.get("competitorId") or "")
    ai=str(a.get("id") or a.get("competitorId") or "")
    chart=game.get("chartEvents") or game.get("chart_events")
    events=(chart.get("events") or chart.get("items")) if isinstance(chart,dict) else chart
    if not isinstance(events,list) or len(events)>500:
        return fail("no_bounded_chart_event_array")
    owners={s:set(evidence["by_side"][s]["members"]) for s in ("home","away")}
    badsets=[]
    for side,pid,m in bad:
        source=[]
        for e in events:
            if not isinstance(e,dict) or not p._is_shot(e):continue
            if _chart_side(e,hi,ai)!=side:continue
            if _shooter(e,owners,side)!=pid:continue
            source.append(e)
        if len(source)!=m["chart_count"]:
            return fail("bad_player_shot_event_count_changed")
        alternatives={}
        for index,e in enumerate(source):
            xg=p._xg(e)
            if xg is None:return fail("unrecognized_original_individual_xg")
            for alias,other in _variants(e):
                if abs(other-xg)<1e-9:continue
                revised=m["chart_sum_xg"]-xg+other
                if not _near(revised,
                     {"xg":m["stats_sum_xg"],"xg_precision":m["stats_xg_precision"]},
                     m["stats_count"]):
                    continue
                alternatives[(index,round(other,9))]=(side,xg,other,alias)
        if len(alternatives)>80:
            return fail("too_many_alternate_observed_xg_candidates")
        badsets.append(list(alternatives.values()))
    counts=[len(x) for x in badsets]
    if any(c==0 for c in counts):
        return fail("one_or_both_players_have_no_valid_observed_alternative_xg",counts)
    if counts[0]*counts[1]>4000:
        return fail("ambiguous_alternative_combination_limit",counts)
    possibilities={}
    for chosen in product(*badsets):
        new_sum=dict(orig_sums)
        new_sq=dict(orig_sq)
        for side,prev,sub,field in chosen:
            new_sum[side]+=sub-prev
            new_sq[side]+=sub**2-prev**2
        if any(not _official_near(new_sum[s],stats[s],stats[s]["shots"])
               for s in ("home","away")):
            continue
        xgq={s:round(new_sq[s]/stats[s]["shots"],8) for s in ("home","away")}
        # Different xG sums are distinct solutions even if rounded XGQ equals.
        key=tuple((round(new_sum[s],6),xgq[s]) for s in ("home","away"))
        possibilities[key]=(chosen,new_sum,xgq)
    if not possibilities:
        return fail("no_joint_player_and_team_xg_reconciliation",counts)
    if len(possibilities)!=1:
        return fail("multiple_distinct_complete_xgq_solutions",counts)
    chosen,totals,quality=next(iter(possibilities.values()))
    row={
        "league":candidate["league"],"date":candidate["date"],
        "home":candidate["home"],"away":candidate["away"],
        "hg":candidate["hg"],"ag":candidate["ag"],
        "source_match_id":candidate["source_match_id"],
        "source":"365Scores (opt-in; rights required)",
        "home_shots":stats["home"]["shots"],
        "away_shots":stats["away"]["shots"],
        "home_xg":round(totals["home"],6),
        "away_xg":round(totals["away"],6),
        "home_xgq":quality["home"],"away_xgq":quality["away"],
        "proof_tier":"TWO_PLAYERS_EXPLICIT_SHOT_XG_ALT_BOTH_TEAM_TOTALS",
        "observed_alternative_fields":sorted(set(z[3] for z in chosen)),
        "full_player_stats_confirmed":True,
        "both_team_stats_confirmed":True,
        "training_release":False
    }
    return {"ok":True,"reason":"two_player_explicit_source_fields_uniquely_reconcile",
            "explicit_alternative_counts":counts,"private_row":row}
