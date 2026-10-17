# Penniless model decision — 2026-10-17

## Owner-approved production change

For **newly frozen** fixtures, choose `stage1_volume_xgq` instead of the prior `xgq_production_formula`. The old prediction stays attached to each frozen match; never overwrite any already-frozen forecast. The old XGQ and goal/Elo/hybrid comparisons remain available for paired scoring.

Stage 1 uses real previously verified xG/xGA, shot volume, XGQ and a fixed-rho goal baseline. Reference parameters: (goal/shot blend=0.50, shot-volume power=0.25, XGQ power=0.30), previously chosen on historical validation rather than today's scoreline. Return **no forecast** if the required verified baseline is missing.

## Reproducible prior historical comparison

Latest archived Stage 3 study: **949 paired test fixtures** on the same blocked historical dates:
- XGQ: accuracy 0.465753, log loss 1.060379.
- Fixed DC: accuracy 0.507903, log loss 1.006704.
- Elo: accuracy 0.507903, log loss 1.017569.
- Stage 1: accuracy 0.520548, log loss 0.999835.
- Stage 3: accuracy 0.521602, log loss 1.000129.

Other Stage 1 study: **1051 historical test fixtures**; Stage 1 accuracy 0.514748, log loss 1.001574; production XGQ accuracy 0.462417, log loss 1.064758. Reports from private Cloudflare D1 metadata keys `understat_feature_stage3` and `understat_feature_stage1`.

## Limitations and gates

- Historical records have already been studied; these are **not pristine prospective experiments**, nor proof of 52% forward accuracy.
- Stage 3 has opponent-adjusted 5/10/20-game form and venue effects but only an essentially tied historical result with Stage 1; keep it in research until strictly forward-tested.
- Non-penalty xG, authentic xA/key passes and big chances require **sufficient prior chronological coverage**. Never invent them from aggregate shots: `private_understat_creativity` is still incomplete, and “big chances” currently only have a proxy definition.
- Fixed-rho Dixon-Coles is not genuinely fitted from outcomes. Do not claim draw calibration is solved. Validate classwise reliability separately.
- Compare old and new versions on the **same frozen fixture identities**, using Brier, log loss, 1/X/2 accuracy and draw calibration; isolate by league, match day, and home-vs-away.
- Historical re-evaluation is allowed to run using freshly imported authenticated D1 history, but must never rewrite previously published forecasts.
