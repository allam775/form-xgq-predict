"""Auditable chronological XGQ benchmarking, NOT a source of live forecasts.

Scientific design:
 - real completed matches only; one prediction per game before its kickoff date
 - per-league blocked, *date*-level 60/20/20 train/validation/test splits
 - choose model solely on validation; report results on untouched test
 - paired head-to-head versus the unchanged production XGQ baseline
 - abstain on small samples and report selection optimism explicitly
 - no arbitrary override of production probability gates

Does not ingest or infer 365Scores data; does not fabricate historical xG.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import date
import json
import math
from pathlib import Path
from .xgq import predict_xgq

# Production default is always included. Other combinations are research-only.
CANDIDATES = (
    (16, 90, 1.0),
    (12, 60, 1.0),
    (16, 180, 1.0),
    (24, 90, 1.0),
    (16, 90, 0.5),
    (16, 90, 2.0),
    (24, 180, 2.0),
)
OUTCOMES = ("home", "draw", "away")


def _outcome(game):
    if game["hg"] > game["ag"]:
        return "home"
    if game["hg"] < game["ag"]:
        return "away"
    return "draw"


def _valid_history(history):
    """Strictly accept the project's normalized per-shot historical metrics."""
    seen = set()
    result = []
    for row in history:
        if not isinstance(row, dict) or any(k not in row for k in (
            "id", "date", "league", "home", "away", "h", "a", "hg", "ag",
            "home_xgq", "away_xgq", "source", "source_match_id")):
            raise ValueError("Research history is missing required evidence")
        if row["id"] in seen:
            raise ValueError("Duplicate match in research history")
        seen.add(row["id"])
        date.fromisoformat(row["date"])
        if (not row["league"] or not row["h"] or not row["a"] or row["h"] == row["a"]
                or type(row["hg"]) is not int or type(row["ag"]) is not int
                or not 0 <= row["hg"] <= 30 or not 0 <= row["ag"] <= 30
                or any(type(row[k]) not in (int, float) or not math.isfinite(row[k])
                       or not 0 <= row[k] <= 1
                       for k in ("home_xgq", "away_xgq"))):
            raise ValueError("Invalid shot-derived historical row")
        if not row["source_match_id"] or "synthetic" in row["source"].lower():
            raise ValueError("A benchmark cannot use synthetic or unattributed matches")
        result.append(row)
    return sorted(result, key=lambda r: (r["date"], r["league"], r["id"]))


def _split(games):
    """Split separately by competition, never split same-date fixtures across folds."""
    by_league = defaultdict(list)
    for row in games:
        by_league[row["league"]].append(row)
    partitions = {"train": [], "validation": [], "test": []}
    split_meta = {}
    for league, rows in by_league.items():
        days = sorted({r["date"] for r in rows})
        if len(days) < 10:
            split_meta[league] = {"status": "not_enough_match_days", "days": len(days)}
            continue
        n1 = max(1, int(len(days) * .6))
        n2 = max(n1 + 1, int(len(days) * .8))
        if n2 >= len(days):
            split_meta[league] = {"status": "no_test_days", "days": len(days)}
            continue
        pivot_val, pivot_test = days[n1], days[n2]
        for row in rows:
            group = "train" if row["date"] < pivot_val else "validation" if row["date"] < pivot_test else "test"
            partitions[group].append(row)
        split_meta[league] = {"status": "split", "training_end_exclusive": pivot_val,
                              "test_start": pivot_test, "days": len(days), "matches": len(rows)}
    return partitions, split_meta


def _replay(history, fixtures, candidate, *, max_stale_days=120):
    results = {}
    for game in fixtures:
        fixture = {"date": game["date"], "league": game["league"],
                   "home_team": game["home"], "away_team": game["away"]}
        forecast, why = predict_xgq(fixture, history, game["date"],
                                    max_stale_days=max_stale_days,
                                    lookback=candidate[0], half_life=candidate[1],
                                    prior_strength=candidate[2])
        if forecast:
            probs = forecast["probabilities"]
            if not set(OUTCOMES).issubset(probs):
                raise ValueError("Prediction does not contain 1X2 probabilities")
            results[game["id"]] = (probs, _outcome(game))
    return results


def _score(paired):
    if not paired:
        return {"tested": 0}
    loss = 0.0
    brier = 0.0
    correct = 0
    for probabilities, outcome in paired:
        loss += -math.log(max(1e-9, probabilities[outcome]))
        brier += sum((probabilities[k] - int(k == outcome))**2 for k in OUTCOMES)
        correct += max(OUTCOMES, key=lambda k: probabilities[k]) == outcome
    n = len(paired)
    return {"tested": n, "log_loss": round(loss / n, 6),
            "brier": round(brier / n, 6),
            "top_choice_accuracy": round(correct / n, 6)}


def benchmark(history, *, min_validation=25, min_test=25, max_stale_days=120):
    """Select using historical validation; measure held-out baseline and challenger on identical games."""
    games = _valid_history(history)
    groups, split_info = _split(games)
    report = {"status": "insufficient", "method": "league-stratified blocked rolling-origin v1",
              "model": "XGQ-derived pre-match Poisson", "training": len(groups["train"]),
              "validation_matches": len(groups["validation"]),
              "test_matches": len(groups["test"]), "history": len(games),
              "max_stale_days": max_stale_days,
              "splits": split_info,
              "disclaimer": "Research-only. Not live accuracy or proof of predictive improvement."}
    if not groups["validation"] or not groups["test"]:
        report["reason"] = "insufficient_blocked_dates"
        return report
    # Historical rows are all accessible here, but predict_xgq uses ONLY dates < game day.
    # Validation never informs test labels or training features.
    baseline_val = _replay(games, groups["validation"], CANDIDATES[0], max_stale_days=max_stale_days)
    if len(baseline_val) < min_validation:
        report.update(reason="insufficient_eligible_validation", validation_eligible=len(baseline_val))
        return report
    viable = []
    for params in CANDIDATES:
        predicted = _replay(games, groups["validation"], params, max_stale_days=max_stale_days)
        common = set(baseline_val) & set(predicted)
        if len(common) < min_validation:
            continue
        stats = _score([predicted[x] for x in sorted(common)])
        viable.append((params, stats["log_loss"], stats, len(common)))
    if not viable:
        report["reason"] = "no_candidate_with_sufficient_validation"
        return report
    winner = min(viable, key=lambda t: (t[1], t[0] != CANDIDATES[0], t[0]))
    champion = winner[0]
    # Report the comparison on exactly the same untouched test fixtures.
    baseline_test = _replay(games, groups["test"], CANDIDATES[0], max_stale_days=max_stale_days)
    champion_test = _replay(games, groups["test"], champion, max_stale_days=max_stale_days)
    matched = sorted(set(baseline_test) & set(champion_test))
    if len(matched) < min_test:
        report.update(reason="insufficient_eligible_test", validation_eligible=len(baseline_val),
                      test_eligible=len(matched), selected_parameters=_describe(champion))
        return report
    incumbent_score = _score([baseline_test[k] for k in matched])
    challenger_score = _score([champion_test[k] for k in matched])
    improvement = incumbent_score["log_loss"] - challenger_score["log_loss"]
    report.update(status="retrospective", selection="validation_only",
                  validation_eligible=len(baseline_val), test_eligible=len(matched),
                  selected_parameters=_describe(champion),
                  baseline_parameters=_describe(CANDIDATES[0]),
                  baseline_test=incumbent_score, selected_test=challenger_score,
                  log_loss_improvement=round(improvement, 6),
                  selected_beats_baseline=improvement > 0,
                  candidate_count=len(viable),
                  production_model_unchanged=True)
    return report


def _describe(params):
    return {"lookback": params[0], "half_life_days": params[1],
            "prior_strength": params[2]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline chronological research; never auto-deploy tuned probabilities")
    parser.add_argument("--input", default="data/shot_history.json")
    parser.add_argument("--output", default="generated/research_report.json")
    parser.add_argument("--min-validation", type=int, default=25)
    parser.add_argument("--min-test", type=int, default=25)
    options = parser.parse_args(argv)
    if not 1 <= options.min_validation <= 10000 or not 1 <= options.min_test <= 10000:
        parser.error("minimum sample count must be positive")
    archive = json.loads(Path(options.input).read_text(encoding="utf8"))
    if not isinstance(archive, list):
        raise ValueError("History must be a JSON array")
    result = benchmark(archive, min_validation=options.min_validation,
                       min_test=options.min_test)
    out = Path(options.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(f"Historical research: {result['status']} — {result.get('reason', 'completed')}"
          f"; train/validation/test={result['training']}/{result['validation_matches']}/{result['test_matches']}")
    if result["status"] == "retrospective":
        print(f"Paired held-out games: {result['test_eligible']}; old log loss={result['baseline_test']['log_loss']}; "
              f"candidate log loss={result['selected_test']['log_loss']}")
    return result


if __name__ == "__main__":
    main()
