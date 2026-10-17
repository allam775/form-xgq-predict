"""Penniless Draw Lab: no forced draws, chronological binary draw calibration.

Train: Aug 2025–Jan 2026 (historical replay).
Select among fixed regularization/feature policies: Feb–Mar 2026 ONLY.
Score: Apr–May 2026 and 2026/27 season WITHOUT parameter retuning.
All training features were computed from matches strictly before each fixture.
Output is aggregate private D1 research, no reclassification of frozen forecasts.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import json
import math
from .comprehensive import _dated_replay, ensemble, APPROVED_PARAMS, OUTCOMES
from .understat_quality import score
from .understat_d1 import D1

REPORT_KEY = "penniless_draw_lab_20261017"
# Selected using 2025-08..2026-01 training and 2026-02..03 validation.
# No current-season outcomes were used to fit or choose these coefficients.
FROZEN_DRAW_WEIGHTS = (-0.143539829,0.244601568,-0.107317616,0.,0.)
DRAW_VERSION = "penniless-comprehensive-draw-v2-20261017"
TRAIN_START, TRAIN_END = "2025-08-01", "2026-01-31"
VAL_START, VAL_END = "2026-02-01", "2026-03-31"
TEST_START, TEST_END = "2026-04-01", "2026-05-31"
SEASON_START = "2026-08-01"

def clip(x,lo,hi):
    return max(lo,min(hi,x))

def logit(x):
    p=clip(x,1e-6,1-1e-6)
    return math.log(p/(1-p))

def logistic(v):
    if v>=0: return 1/(1+math.exp(-v))
    e=math.exp(v)
    return e/(1+e)

def draw_features_for_fixture(prior, fixture):
    """Pre-match feature input identical to the chronological replay protocol.

    Receives only rows strictly before the target fixture date. Defensive
    filtering prevents current/same-date results influencing live inference.
    """
    from datetime import date, timedelta
    day=fixture["date"]
    minimum=(date.fromisoformat(day)-timedelta(days=900)).isoformat()
    recent=[r for r in prior if r["date"]<day and
            r["date"]>=minimum and r["league"]==fixture["league"]]
    if len(recent)<40:
        return None
    base_rate=sum(r["hg"]==r["ag"] for r in recent)/len(recent)
    def team_profile(team):
        matches=[r for r in recent if team in (r["h"],r["a"])][-20:]
        if len(matches)<5:
            return None
        draw_count=sum(r["hg"]==r["ag"] for r in matches)
        avg_total=sum(r["hg"]+r["ag"] for r in matches)/len(matches)
        return (draw_count+6*base_rate)/(len(matches)+6),avg_total
    h=team_profile(fixture["h"])
    a=team_profile(fixture["a"])
    if not h or not a:
        return None
    return {"league_draw_rate":base_rate,
            "recent_team_draw_rate":(h[0]+a[0])/2,
            "recent_total_goals":(h[1]+a[1])/2}


def feature_vector(r):
    """All feature values from pre-match model and recent verified completed games."""
    m=r["models"]
    f=r["draw_features"]
    original=ensemble(m,APPROVED_PARAMS)
    # Balance 1 is a finely balanced pair; 0 is one-sided.
    strength_balance=1-abs(m["elo"]["home"]-m["elo"]["away"])/(
        max(1e-8,m["elo"]["home"]+m["elo"]["away"]))
    tempo=clip((2.7-f["recent_total_goals"])/1.2,-1,1)
    propensity=clip(4*(f["recent_team_draw_rate"]-f["league_draw_rate"]),-1,1)
    dc_signal=clip(4*(m["dc"]["draw"]-original["draw"]),-1,1)
    return (1., 2*strength_balance-1, tempo, propensity, dc_signal)

def apply_draw_calibration(original, features, weights):
    if len(weights)!=len(features):
        raise ValueError("Calibration feature mismatch")
    if not any(weights):
        return dict(original)
    z=logit(original["draw"])+sum(w*x for w,x in zip(weights,features))
    p_draw=clip(logistic(z),.03,.70)
    remain=(1-p_draw)/max(1e-10,1-original["draw"])
    probs={"home":original["home"]*remain,
           "draw":p_draw, "away":original["away"]*remain}
    if abs(sum(probs.values())-1)>1e-8:
        raise ValueError("Draw calibration normalization failure")
    return probs

def fit(train, *, regularization=.02, feature_mask=(1,1,1,1,1), iterations=500):
    """Penalized binomial likelihood with base logit as offset; no external ML libs."""
    if len(train)<80:
        raise ValueError("Insufficient historical draw training")
    if regularization<0 or len(feature_mask)!=5 or not 100<=iterations<=3000:
        raise ValueError("Invalid draw training")
    w=[0.]*5
    # Stable batch gradient descent. Penalty constrains sparse draw signals.
    for _ in range(iterations):
        gradient=[0.]*5
        for row in train:
            f=row["features"]
            q=logistic(logit(row["original"]["draw"])+sum(a*b for a,b in zip(w,f)))
            error=q-int(row["actual"]=="draw")
            for j in range(5):
                gradient[j]+=error*f[j]*feature_mask[j]
        for j in range(5):
            gradient[j]=gradient[j]/len(train)+2*regularization*w[j]
            w[j]=clip(w[j]-.35*gradient[j],-2,2)*feature_mask[j]
    return tuple(round(x,9) for x in w)

def metrics(rows,key):
    if not rows:
        return {"n":0}
    probs=[(r[key],r["actual"]) for r in rows]
    s=score(probs)
    s["correct"]=sum(max(OUTCOMES,key=lambda k:r[key][k])==r["actual"] for r in rows)
    s["draw_picks"]=sum(max(OUTCOMES,key=lambda k:r[key][k])=="draw" for r in rows)
    s["actual_draws"]=sum(r["actual"]=="draw" for r in rows)
    s["correct_draw_picks"]=sum(max(OUTCOMES,key=lambda k:r[key][k])=="draw" and
                                r["actual"]=="draw" for r in rows)
    s["mean_draw_probability"]=round(sum(r[key]["draw"] for r in rows)/len(rows),6)
    s["draw_log_loss"]=round(-sum(math.log(max(1e-12, r[key]["draw"] if
        r["actual"]=="draw" else 1-r[key]["draw"])) for r in rows)/len(rows),6)
    return s

def _risk_signal(row, *, min_probability, min_relative):
    p=row["calibrated"]
    return (p["draw"]>=min_probability and
            p["draw"] >= min_relative*max(p["home"],p["away"]))

def draw_watch_selection(validation):
    """Separate draw-risk alert, not dishonest replacement of argmax labels."""
    if not validation:
        return {"status":"insufficient"}
    actual_rate=sum(r["actual"]=="draw" for r in validation)/len(validation)
    best=None
    for min_p in (.25,.27,.29,.31,.33,.35):
        for ratio in (.65,.75,.85,.95,1.00):
            selected=[r for r in validation if _risk_signal(
                r,min_probability=min_p,min_relative=ratio)]
            if len(selected)<max(8,int(.04*len(validation))) or len(selected)>int(.35*len(validation)):
                continue
            precision=sum(r["actual"]=="draw" for r in selected)/len(selected)
            recall=sum(r["actual"]=="draw" for r in selected)/max(1,
                sum(r["actual"]=="draw" for r in validation))
            f1=2*precision*recall/(precision+recall) if precision+recall else 0
            # No false promise of edge: need meaningful precision lift over base rate.
            if precision < actual_rate+.04:
                continue
            score_key=(f1,precision,len(selected),-min_p,-ratio)
            if best is None or score_key>best[0]:
                best=(score_key,(min_p,ratio),len(selected),precision,recall)
    if best is None:
        return {"status":"no_validated_draw_risk_rule",
                "baseline_draw_rate":round(actual_rate,6)}
    return {"status":"validation_candidate",
            "parameters":{"minimum_draw_probability":best[1][0],
                          "minimum_relative_to_best_win":best[1][1]},
            "validation_alerts":best[2],
            "validation_precision":round(best[3],6),
            "validation_recall":round(best[4],6),
            "baseline_draw_rate":round(actual_rate,6)}

def paired_day_bootstrap(rows, *, trials=1000, seed=20261017):
    """Paired improvement in log-loss; resample independent league/match-day blocks.

    Descriptive CI only. Prior research had inspected some overlapping seasons.
    """
    from random import Random
    groups=defaultdict(list)
    for r in rows:
        k=(r["league"],r["date"])
        label=r["actual"]
        gain=math.log(max(1e-12,r["calibrated"][label]))-math.log(
            max(1e-12,r["original"][label]))
        groups[k].append(gain)
    arr=list(groups.values())
    if len(arr)<10:
        return {"status":"insufficient_paired_days","days":len(arr)}
    rng=Random(seed)
    samples=[]
    for _ in range(trials):
        chosen=[arr[rng.randrange(len(arr))] for _ in arr]
        samples.append(sum(map(sum,chosen))/sum(map(len,chosen)))
    samples.sort()
    return {"status":"descriptive_historical","paired_days":len(arr),
            "games":len(rows),
            "mean_gain":round(sum(map(sum,arr))/len(rows),6),
            "logloss_gain_ci95":[round(samples[int((trials-1)*.025)],6),
                                  round(samples[int((trials-1)*.975)],6)],
            "ci_strictly_positive":samples[int((trials-1)*.025)]>0}


def draw_watch_metrics(rows,selection):
    if selection["status"]!="validation_candidate":
        return {"status":"disabled_not_validated"}
    t=selection["parameters"]
    selected=[r for r in rows if _risk_signal(r,
        min_probability=t["minimum_draw_probability"],
        min_relative=t["minimum_relative_to_best_win"])]
    n=len(selected)
    hits=sum(r["actual"]=="draw" for r in selected)
    original_correct=sum(
        max(OUTCOMES,key=lambda k:r["calibrated"][k])==r["actual"]
        for r in selected)
    # Counterfactual, evaluated only: does replacing 1X2 with draw help?
    delta_correct=hits-original_correct
    actual=sum(r["actual"]=="draw" for r in rows)
    return {"status":"research_only","flagged":n,"correct_draw_flags":hits,
            "correct_winning_picks_overridden":original_correct,
            "net_correct_change_if_forced_draw":delta_correct,
            "precision":round(hits/n,6) if n else None,
            "recall":round(hits/actual,6) if actual else None,
            "unflagged_draws":actual-hits,
            "baseline_draw_rate":round(actual/len(rows),6) if rows else None}

def report(history, *, as_of):
    rows,withheld,_,n_history=_dated_replay(history,as_of,eval_start=TRAIN_START)
    prepared=[]
    for r in rows:
        orig=ensemble(r["models"],APPROVED_PARAMS)
        prepared.append({**r,"original":orig,"features":feature_vector(r)})
    train=[r for r in prepared if TRAIN_START<=r["date"]<=TRAIN_END]
    val=[r for r in prepared if VAL_START<=r["date"]<=VAL_END]
    historical=[r for r in prepared if TEST_START<=r["date"]<=TEST_END]
    season=[r for r in prepared if SEASON_START<=r["date"]<=as_of]
    if len(train)<100 or len(val)<40:
        return {"status":"insufficient","train_games":len(train),
                "validation_games":len(val),"historical_games":len(historical),
                "season_games":len(season)}
    # Small preregistered search, including exact-identity baseline.
    candidates=[("identity",(0.,)*5)]
    for lam in (.005,.02,.08):
        for mask in ((1,0,0,0,0),(1,1,1,0,0),(1,1,1,1,1)):
            candidates.append((f"L2={lam},mask={mask}",fit(train,
                regularization=lam,feature_mask=mask)))
    best=None
    for name,weights in candidates:
        for r in val:
            r["calibrated"]=apply_draw_calibration(r["original"],r["features"],weights)
        measures=metrics(val,"calibrated")
        # Optimize full multiclass proper loss; tie-break to fewer coefficients.
        key=(measures["log_loss"],sum(abs(x) for x in weights),name)
        if best is None or key<best[0]:
            best=(key,name,weights,measures)
    selected_name,weights=best[1],best[2]
    for r in prepared:
        r["calibrated"]=apply_draw_calibration(r["original"],r["features"],weights)
    watch=draw_watch_selection(val)
    def summarize(bucket):
        b={"n":len(bucket),"unmodified":metrics(bucket,"original"),
           "draw_calibrated":metrics(bucket,"calibrated"),
           "draw_watch":draw_watch_metrics(bucket,watch),
           "paired_logloss_uncertainty":paired_day_bootstrap(bucket),
           "by_league":{league:{"n":sum(r["league"]==league for r in bucket),
                   "base":metrics([r for r in bucket if r["league"]==league],"original"),
                   "calibrated":metrics([r for r in bucket if r["league"]==league],"calibrated")}
                   for league in sorted({r["league"] for r in bucket})}}
        return b
    return {
        "status":"retrospective_draw_study",
        "trained_on":[TRAIN_START,TRAIN_END],
        "validated_on":[VAL_START,VAL_END],
        "historical_holdout":[TEST_START,TEST_END],
        "current_season_window":[SEASON_START,as_of],
        "history_records":n_history,
        "training_games":len(train),"validation_games":len(val),
        "regression_candidate_count":len(candidates),
        "selected_model":selected_name,"coefficients":weights,
        "validation":summarize(val),"historical":summarize(historical),
        "season":summarize(season),
        "draw_watch_rule":watch,
        "withheld":withheld,
        "notes":[
            "Every per-game predictor is derived solely from earlier match dates.",
            "Binary draw calibration selected on February-March 2026, never April-May or 2026/27.",
            "Previously examined history/component selection means these are NOT pristine blind tests.",
            "Draw-watch is separate from the 1X2 argmax and may be disabled if validation fails.",
            "No forced draws: probabilities may rationally favor home or away even with many observed draws.",
            "Production forecast revisions are PROHIBITED until prospective validation and explicit approval."
        ],
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
    }

def main():
    db=D1()
    asof=(datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat()
    data=report(db.history(),as_of=asof)
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES (?,?)",
             (REPORT_KEY,json.dumps(data,separators=(",",":"))))
    print(json.dumps({"status":data["status"],
        "training_games":data.get("training_games"),
        "validation_games":data.get("validation_games"),
        "selected":data.get("selected_model"),
        "coefs":data.get("coefficients"),
        "watch":data.get("draw_watch_rule"),
        "holdout":{name:{"base":data[name]["unmodified"],
                         "calibrated":data[name]["draw_calibrated"],
                         "watch":data[name]["draw_watch"]}
                   for name in ("historical","season")
                   if name in data}},sort_keys=True))
    return data

if __name__ == "__main__":
    main()
