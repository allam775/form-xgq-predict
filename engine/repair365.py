"""Fail-closed repair of ONE conclusively extra 365Scores chart event.

Never infer or create a shot, never rescale xG, never relax the 365Scores
independent match-shot total. An excess shot may be discarded ONLY IF:
  - chartEvents has precisely one shot more than independently published
    official Total Shots, and all other team's shots match;
  - independent on-target/off-target/blocked statistics isolate exactly
    one overreported outcome CLASS;
  - removing one observed shot from THAT class yields official team shot
    count AND expected goals within the original rounding-derived bound;
  - every possible such exclusion yields the same individual shot xG value,
    hence the exact same XGQ result (no arbitrary choice of which shot);
  - other team still independently reconciles;
  - match ID, date, competition and team scores are confirmed.
The result is a PRIVATE research candidate; production/training remains off.
"""
from __future__ import annotations
import math
from engine import provider365 as p
from engine.competition365 import resolve


def _event_shots(payload):
    g=payload.get("game",payload)
    h=p._side(g,"home");a=p._side(g,"away")
    hid=str(h.get("id") or h.get("competitorId") or "")
    aid=str(a.get("id") or a.get("competitorId") or "")
    if not hid or not aid or hid==aid:
        raise ValueError("identity_ambiguity")
    events=g.get("chartEvents") or g.get("chart_events")
    if isinstance(events,dict):
        events=events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events,list) or not 1<=len(events)<=500:
        raise ValueError("missing_chart_events")
    rows={"home":[],"away":[]}
    for e in events:
        if not isinstance(e,dict):raise ValueError("malformed_event")
        if not p._is_shot(e):continue
        x=p._xg(e)
        if x is None:raise ValueError("shot_missing_valid_xg")
        obj=e.get("competitor") if isinstance(e.get("competitor"),dict) else {}
        who=str(e.get("competitorId") or e.get("teamId") or obj.get("id") or "")
        if who==hid:side="home"
        elif who==aid:side="away"
        elif isinstance(e.get("isHome"),bool):side="home" if e["isHome"] else "away"
        elif e.get("competitorNum") in (1,2):side="home" if e["competitorNum"]==1 else "away"
        else:raise ValueError("unknown_shot_team")
        out=e.get("outcome")
        if isinstance(out,dict):out=out.get("name")
        if not isinstance(out,str):
            raise ValueError("unknown_shot_outcome")
        out=out.casefold().strip()
        if out in ("goal","saved"):kind="on_target"
        elif out in ("missed","post"):kind="off_target"
        elif out=="blocked":kind="blocked"
        else:raise ValueError("unknown_shot_category")
        rows[side].append((x,kind,out))
    return rows


def _within(shot_xgs,statistics,*,shot_decimals=2):
    n=statistics["shots"]
    if len(shot_xgs)!=n or not 1<=n<=150:
        return False
    p=statistics["xg_display_decimals"]
    if type(p) is not int or not 0<=p<=4 or not 1<=shot_decimals<=5:
        raise ValueError("bad_provider_rounding_precision")
    tol=n*(0.5*10**(-shot_decimals)) + .5*10**(-p)+1e-9
    return abs(sum(shot_xgs)-statistics["xg"])<=tol


def repair(candidate,detail,verified_stats,breakdown):
    """Return a private research row + proof only for unique xG deletion.

    Otherwise return reason and zero data; preserving zero guessing.
    """
    fail=lambda reason:{"ok":False,"reason":reason}
    if (candidate.get("eligible_for_forecast") is not False
        or candidate.get("completeness")!="NOT_VERIFIED_INDEPENDENT_TOTALS"
        or candidate.get("catalog_verified") is not True):
        return fail("not_original_private_candidate")
    g=detail.get("game",detail) if isinstance(detail,dict) else None
    if not isinstance(g,dict) or p._game_id(g)!=candidate["source_match_id"] or not p._final(g):
        return fail("match_identity_not_final")
    identity=resolve(detail)
    if (not identity["ok"] or identity["league"]!=candidate["league"]
        or identity["provider_competition_id"]!=candidate["competition_id"]
        or p._date(g)!=candidate["date"]):
        return fail("competition_or_date_disagrees")
    home=p._side(g,"home");away=p._side(g,"away")
    if not (home.get("name")==candidate["home"]
        and away.get("name")==candidate["away"]
        and p._score(g,"home",home)==candidate["hg"]
        and p._score(g,"away",away)==candidate["ag"]):
        return fail("score_or_team_disagrees")
    try:events=_event_shots(detail)
    except (ValueError,KeyError,TypeError) as exc:
        return fail(str(exc))
    for side in ("home","away"):
        samples=events[side]
        if len(samples)!=candidate[side+"_chart_shots"]:
            return fail("chart_count_changed")
        if abs(sum(x for x,_,_ in samples)-candidate[side+"_chart_xg_sum"])>0.000001:
            return fail("chart_xg_changed")
        if side not in verified_stats or side not in breakdown:
            return fail("independent_evidence_missing")
    extra=[side for side in ("home","away")
           if len(events[side])-verified_stats[side]["shots"]==1]
    if len(extra)!=1:
        return fail("not_exactly_one_extra_side")
    side=extra[0];other="away" if side=="home" else "home"
    if not _within([v for v,_,_ in events[other]],verified_stats[other]):
        return fail("other_team_not_reconciled")
    diff=breakdown[side]["differences"]
    affected=[key for key in ("on_target","off_target","blocked") if diff.get(key)==-1]
    if len(affected)!=1:
        return fail("extra_outcome_class_not_unique")
    k=affected[0]
    if (diff.get("total")!=-1
        or any(diff.get(other_key)!=0 for other_key in
               ("on_target","off_target","blocked") if other_key!=k)):
        return fail("category_counts_cannot_be_reconciled")
    samples=events[side]
    # A disallowed GOAL cannot be repaired by removing an unrelated saved shot
    # even when its xG would accidentally match the rounded aggregate.
    count_goals=sum(outcome=="goal" for _,_,outcome in samples)
    official_goals=candidate["hg" if side=="home" else "ag"]
    if k=="on_target":
        if count_goals==official_goals+1:
            allowed_outcomes={"goal"}
        elif count_goals==official_goals:
            allowed_outcomes={"saved"}
        else:
            return fail("goal_event_count_conflicts_with_final_score")
    elif k=="off_target":
        allowed_outcomes={"missed","post"}
    else:
        allowed_outcomes={"blocked"}
    choices=[]
    for index,(v,kind,outcome) in enumerate(samples):
        if kind!=k or outcome not in allowed_outcomes:continue
        rem=[x for i,(x,_,_) in enumerate(samples) if i!=index]
        if _within(rem,verified_stats[side]):
            choices.append((v,rem))
    if not choices:
        return fail("no_observed_shot_reconciles_to_independent_xg")
    # Multiple indistinguishable repeated values may represent one ambiguous
    # identity, but their XGQ is mathematically identical; no shot guessed.
    if len({v for v,_ in choices})!=1:
        return fail("multiple_distinct_shots_would_match")
    xg_remove,remain=choices[0]
    if not _within(remain,verified_stats[side]):
        return fail("reconciliation_lost")
    new={"home":events["home"],"away":events["away"]}
    output={
      "league":candidate["league"],
      "date":candidate["date"],
      "home":candidate["home"],"away":candidate["away"],
      "hg":candidate["hg"],"ag":candidate["ag"],
      "source_match_id":candidate["source_match_id"],
      "source":"365Scores (opt-in; rights required)",
      "home_shots":verified_stats["home"]["shots"],
      "away_shots":verified_stats["away"]["shots"],
      "correction_proof":"one_unique_observed_overcounted_outcome_with_independent_stats",
      "corrected_side":side,
      "corrected_outcome_class":k,
      "disallowed_event_outcome":next(o for v,_,o in samples if v==xg_remove and o in allowed_outcomes),
      "shot_xg_model":"chartEvents.xg",
      "training_release":False,
      "number_of_equivalent_removals":len(choices)
    }
    for s in ("home","away"):
        xgs=remain if s==side else [x for x,_,_ in events[s]]
        output[s+"_xg"]=round(sum(xgs),6)
        output[s+"_xgq"]=round(sum(x*x for x in xgs)/len(xgs),8)
    return {"ok":True,"reason":"uniquely_reconciled_overcounted_chart_shot",
            "private_row":output}

