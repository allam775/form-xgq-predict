"""Same-provider independent 365Scores match-stat completeness checks.

Source A: the existing game/ detail chartEvents individual-shot xG.
Source B: the independently requested game/stats/ full-game statistics list.

The two sources must match BOTH teams' TOTAL SHOTS exactly and their
independent EXPECTED GOALS sums within a justified display-rounding bound.
Missing shots (including blocked attempts) are never inferred as zero xG.
This unit does no network requests and exposes no provider data publicly.
"""
from __future__ import annotations
import math
import re
from decimal import Decimal,InvalidOperation

from engine.xgq import normalized

MAX_STATS=500
EXACT_NAMES=("Total Shots","Expected Goals","Shots Blocked")
SOURCE="365Scores (opt-in; rights required)"


def _as_decimal(v,*,integer=False):
    if type(v) is not str:
        # 365Scores game/stats statistics.value is observed as a string.
        # Floats could hide precision; fail closed.
        raise ValueError("stat_value_is_not_string")
    t=v.strip()
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,4})?",t):
        raise ValueError("stat_not_an_unambiguous_nonnegative_number")
    if integer and "." in t:
        raise ValueError("shot_count_noninteger")
    try:
        n=Decimal(t)
    except InvalidOperation:
        raise ValueError("bad_decimal_stat") from None
    if not n.is_finite() or n<0 or n>300:
        raise ValueError("stat_out_of_range")
    return n,max(0,len(t.partition(".")[2]))


def stats_witness(payload,candidate):
    """Extract two-sided shot-count, blocked-shot and xG totals with identity.

    This extraction does not infer anything from aggregate results. The match
    must already have been verified by the game/ competition+score collector.
    """
    if not isinstance(payload,dict):
        raise ValueError("stats_payload_not_object")
    competitors=payload.get("competitors")
    items=payload.get("statistics")
    if not isinstance(competitors,list) or len(competitors)!=2:
        raise ValueError("stats_competitors_not_two")
    if not isinstance(items,list) or not 4<=len(items)<=MAX_STATS:
        raise ValueError("stats_array_unavailable")
    names={"home":normalized(candidate.get("home")),
           "away":normalized(candidate.get("away"))}
    if not names["home"] or not names["away"] or names["home"]==names["away"]:
        raise ValueError("candidate_teams_invalid")
    by_name={}
    ids=set()
    for team in competitors:
        if not isinstance(team,dict):
            raise ValueError("stat_competitor_not_object")
        name=normalized(team.get("name"))
        team_id=str(team.get("id") or "")
        if not team_id or name in by_name or team_id in ids:
            raise ValueError("stat_competitor_ambiguous")
        by_name[name]=team_id
        ids.add(team_id)
    if set(by_name)!=set(names.values()):
        raise ValueError("stat_competitor_names_differ")
    games=payload.get("games")
    if isinstance(games,list):
        ids_present={str(g.get("gameId") or g.get("id"))
                     for g in games if isinstance(g,dict) and
                     (g.get("gameId") or g.get("id"))}
        if ids_present and str(candidate.get("source_match_id")) not in ids_present:
            raise ValueError("stats_response_wrong_match")
    record={}
    for side in ("home","away"):
        cid=by_name[names[side]]
        own=[s for s in items if isinstance(s,dict) and str(s.get("competitorId"))==cid]
        record[side]={}
        for name in EXACT_NAMES:
            matches=[s for s in own if s.get("name")==name]
            if len(matches)!=1:
                raise ValueError("missing_or_duplicate_"+name.lower().replace(" ","_"))
            is_int=name!="Expected Goals"
            number,decimals=_as_decimal(matches[0].get("value"),integer=is_int)
            if name=="Expected Goals":
                record[side]["xg"]=float(number)
                record[side]["xg_display_decimals"]=decimals
            elif name=="Total Shots":
                record[side]["shots"]=int(number)
            elif name=="Shots Blocked":
                record[side]["blocked"]=int(number)
        if record[side]["shots"]>150 or record[side]["blocked"]>record[side]["shots"]:
            raise ValueError("stat_shot_count_out_of_range")
        if record[side]["xg"]>record[side]["shots"]:
            raise ValueError("stat_xg_exceeds_shots")
    return record


def reconcile(candidate,witness,*,shot_xg_decimals=2):
    """Validate original chart arrays against independent game/stat totals.

    Returns only metrics/flags. Does NOT return the actual match data.
    """
    if candidate.get("completeness")!="NOT_VERIFIED_INDEPENDENT_TOTALS":
        raise ValueError("candidate_not_provisional")
    if candidate.get("catalog_verified") is not True:
        raise ValueError("competition_catalog_not_confirmed")
    if candidate.get("eligible_for_forecast") is not False:
        raise ValueError("forecast_gate_not_closed")
    if type(shot_xg_decimals) is not int or not 1<=shot_xg_decimals<=5:
        raise ValueError("unknown_chart_xg_precision")
    result={"ok":False,"reason":None,"count_gap":{"home":None,"away":None},
            "blocked_shots_explain_gap":False,
            "xg_totals_match":False,
            "stats_total_shots_valid":True}
    differences={}
    for side in ("home","away"):
        try:
            count=candidate[side+"_chart_shots"]
            raw_sum=candidate[side+"_chart_xg_sum"]
            total=witness[side]["shots"]
            if (type(count) is not int or type(total) is not int
                or not 1<=count<=150 or not 1<=total<=150):
                raise ValueError("invalid_shot_counts")
            if type(raw_sum) not in (int,float) or not math.isfinite(raw_sum):
                raise ValueError("invalid_shot_xg_sum")
        except (KeyError,TypeError):
            raise ValueError("missing_side_data") from None
        differences[side]=total-count
        result["count_gap"][side]=differences[side]
    result["blocked_shots_explain_gap"]=all(
        differences[side]==witness[side]["blocked"] for side in ("home","away"))
    if differences["home"] or differences["away"]:
        result["reason"]="shot_count_mismatch"
        return result
    for side in ("home","away"):
        count=candidate[side+"_chart_shots"]
        p=witness[side]["xg_display_decimals"]
        if not 0<=p<=4:
            raise ValueError("unknown_provider_total_precision")
        tolerance=(0.5*10**(-shot_xg_decimals)*count+
                   0.5*10**(-p)+1e-9)
        if abs(candidate[side+"_chart_xg_sum"]-witness[side]["xg"])>tolerance:
            result["reason"]=side+"_xg_mismatch"
            return result
    result["xg_totals_match"]=True
    result["reason"]="all_individual_shot_xg_reconciled_to_game_stats"
    result["ok"]=True
    return result


def verified_research_row(candidate):
    """Only called after independent stats_witness + reconcile return OK.

    The caller must guard this invocation; the function itself cannot turn a
    mere provisional match into a verified one.
    """
    from engine.xgq import normalized
    c=candidate
    return {"id":f"{c['league']}|{c['date']}|{normalized(c['home'])}|{normalized(c['away'])}",
       "date":c["date"],"league":c["league"],
       "home":c["home"],"away":c["away"],
       "h":normalized(c["home"]),"a":normalized(c["away"]),
       "hg":c["hg"],"ag":c["ag"],
       "home_xgq":c["home_provisional_xgq"],
       "away_xgq":c["away_provisional_xgq"],
       "home_shots":c["home_chart_shots"],
       "away_shots":c["away_chart_shots"],
       "home_xg":c["home_chart_xg_sum"],
       "away_xg":c["away_chart_xg_sum"],
       "source":SOURCE,"source_match_id":c["source_match_id"],
       "independent_completeness":"both_teams_shot_count_and_xg_sum",
       "verified_stats_endpoint":True,
       "training_release":False}
