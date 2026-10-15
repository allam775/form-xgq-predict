"""Player-guided strict correction for two formerly ambiguous 365Scores charts.

Only apply when:
* original independent provider TEAM xG, Total Shots and outcome classes match
  after removing precisely one OBSERVED chart shot, never a fabricated one;
* independent official player Total Shots isolates exactly one extra shooter;
* player's independently reported xG isolates exactly one removed xG VALUE;
* every remaining player's individual shot counts and xG still reconcile;
* counterpart team and competition/match/score/date are unchanged.

If any plausible deleted shot would yield a different XGQ, fail closed.
No training change, no raw event storage, no public player details.
"""
from __future__ import annotations
from engine.repair365 import repair as original_repair, _within
from engine.player_shot_witness365 import compare_players, _near
from engine import provider365 as p

def repair(candidate,detail,independent,breakdown):
    fail=lambda why:{"ok":False,"reason":why}
    old=original_repair(candidate,detail,independent,breakdown)
    if old.get("ok"):
        return fail("original_already_uniquely_repairable")
    if old.get("reason")!="multiple_distinct_shots_would_match":
        return fail("original_repair_other_reason_"+str(old.get("reason"))[:60])
    obj=detail.get("game",detail)
    players=compare_players(obj,independent)
    if players["aggregate"]["unmapped_shots"]:
        return fail("chart_shooters_not_all_identified")
    gap_sides=[s for s in ("home","away") if players["by_side"][s]["gaps"]]
    if len(gap_sides)!=1:
        return fail("multiple_player_gap_sides")
    side=gap_sides[0];other="away" if side=="home" else "home"
    own=players["by_side"][side]
    if len(own["gaps"])!=1 or own["gaps"][0][1]!=1:
        return fail("extra_shot_not_isolated_to_one_player")
    shooter=own["gaps"][0][0]
    if any(players["by_side"][s]["stat_shots_total"]!=independent[s]["shots"]
           for s in ("home","away")):
        return fail("published_player_shot_counts_not_team_shots")
    if players["by_side"][other]["gaps"]:
        return fail("opponent_player_shots_mismatch")
    impacted=own["members"][shooter]
    if impacted["stats_sum_xg"] is None:
        return fail("suspect_player_lacks_independent_xg")
    gap=breakdown[side]["differences"]
    kinds=[k for k in ("on_target","off_target","blocked") if gap.get(k)==-1]
    if len(kinds)!=1 or gap.get("total")!=-1:
        return fail("official_shot_category_not_unique")
    kind=kinds[0]
    if any(gap.get(k)!=0 for k in ("on_target","off_target","blocked") if k!=kind):
        return fail("independent_category_gaps_conflict")
    types={"on_target":{"goal","saved"},"off_target":{"missed","post"},
           "blocked":{"blocked"}}
    choices=[]
    shots=impacted["shot_events"]
    fullsum=sum(v["xg"] for v in shots)
    team_sum=sum(v["chart_sum_xg"] for v in own["members"].values())
    if abs(team_sum-candidate[side+"_chart_xg_sum"])>1e-6:
        return fail("original_shot_sum_changed")
    for index,removed in enumerate(shots):
        if removed["outcome"] not in types[kind]:
            continue
        # The legacy strict repair's special scored-goal guard.
        num_goal=sum(v["outcome"]=="goal" for m in own["members"].values()
                     for v in m["shot_events"])
        actual_goals=candidate["hg" if side=="home" else "ag"]
        if kind=="on_target":
            admissible=("goal" if num_goal==actual_goals+1 else
                        "saved" if num_goal==actual_goals else None)
            if removed["outcome"]!=admissible:continue
        remainder=[v for j,v in enumerate(shots) if j!=index]
        player_after=sum(v["xg"] for v in remainder)
        if len(remainder)!=impacted["stats_count"]:
            continue
        if not _near(player_after,
                     {"xg":impacted["stats_sum_xg"],
                      "xg_precision":impacted["stats_xg_precision"]},
                     len(remainder)):
            continue
        official=independent[side]
        total_xg_after=team_sum-removed["xg"]
        pdec=official["xg_display_decimals"]
        tol=official["shots"]*.005+.5*10**(-pdec)+1e-9
        if abs(total_xg_after-official["xg"])>tol:
            continue
        choices.append((removed["xg"],removed["outcome"],remainder))
    if not choices:return fail("no_removed_shot_matches_both_player_and_team_xg")
    values={round(x,9) for x,_,_ in choices}
    if len(values)!=1:
        return fail("distinct_shot_xg_removals_remain_ambiguous")
    chosen=choices[0]
    # Every OTHER player must be independently correct in count and xG,
    # and the other team's full chart must already reconcile.
    for s in ("home","away"):
        for pid,m in players["by_side"][s]["members"].items():
            xs=chosen[2] if s==side and pid==shooter else m["shot_events"]
            if len(xs)!=m["stats_count"]:
                return fail("unreconciled_other_player_shot_counts")
            if m["stats_count"]>0:
                if m["stats_sum_xg"] is None:
                    return fail("independent_player_xg_missing")
                if not _near(sum(v["xg"] for v in xs),
                    {"xg":m["stats_sum_xg"],"xg_precision":m["stats_xg_precision"]},
                    len(xs)):
                    return fail("unreconciled_other_player_xg")
    by_side={}
    for s in ("home","away"):
        all_shots=[]
        for pid,m in players["by_side"][s]["members"].items():
            xs=chosen[2] if s==side and pid==shooter else m["shot_events"]
            all_shots.extend(v["xg"] for v in xs)
        if not _within(all_shots,independent[s]):
            return fail("final_team_stats_do_not_reconcile")
        by_side[s]={"shots":len(all_shots),
                    "xg":round(sum(all_shots),6),
                    "xgq":round(sum(x*x for x in all_shots)/len(all_shots),8)}
    out={
        "source":"365Scores (opt-in; rights required)",
        "source_match_id":candidate["source_match_id"],
        "league":candidate["league"],"date":candidate["date"],
        "home":candidate["home"],"away":candidate["away"],
        "hg":candidate["hg"],"ag":candidate["ag"],
        "home_shots":by_side["home"]["shots"],"away_shots":by_side["away"]["shots"],
        "home_xg":by_side["home"]["xg"],"away_xg":by_side["away"]["xg"],
        "home_xgq":by_side["home"]["xgq"],"away_xgq":by_side["away"]["xgq"],
        "proof_tier":"PLAYER_AND_TEAM_INDEPENDENT_UNIQUE_EXCLUSION",
        "single_suspect_player_verified":True,
        "single_removed_xg_value_verified":True,
        "original_audit_preserved":True,
        "training_release":False
    }
    return {"ok":True,"reason":"player_and_official_stats_uniquely_reconcile_extra_shot",
            "private_row":out,"equivalent_identical_xg_removals":len(choices)}
