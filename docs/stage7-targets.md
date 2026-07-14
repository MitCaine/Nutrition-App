# Stage 7A: nutrition targets and FDA Daily Value foundation

Stage 7A adds comparison metadata only. Targets never enter or rewrite Daily Log nutrient snapshots. The existing daily-summary service remains the sole source of consumed totals.

## Existing summary and canonical units

Daily summary totals contain only nutrients represented by at least one historical snapshot. Each total separates known and estimated amounts and reports unknown-contributor metadata. Missing nutrients are absent, not implicit zero. Calories are the canonical `calories` nutrient in `kcal`, not a separate summary field.

The canonical catalog contains calories (`kcal`); total, saturated, and trans fat (`g`); cholesterol (`mg`); sodium (`mg`); total carbohydrate, dietary fiber, total sugars, added sugars, and protein (`g`); vitamin D (`mcg`); and calcium, iron, potassium, and magnesium (`mg`). Before Stage 7A, no production UI hard-coded nutrition targets.

## FDA Daily Values

Catalog version `fda_daily_values_2016_v1` implements the current Nutrition Facts standard for adults and children 4 years and older. The FDA final rule was published May 27, 2016, became effective July 26, 2016, and its extended compliance dates were January 1, 2020 and January 1, 2021 depending on manufacturer size.

Only canonical app nutrients are included. Available values are total fat 78 g, saturated fat 20 g, cholesterol 300 mg, sodium 2,300 mg, total carbohydrate 275 g, dietary fiber 28 g, added sugars 50 g, protein 50 g, vitamin D 20 mcg, calcium 1,300 mg, iron 18 mg, potassium 4,700 mg, and magnesium 420 mg. Protein carries a note because percent-DV declaration is generally not required on adult labels unless specific labeling conditions apply. Calories, trans fat, and total sugars are explicitly unavailable rather than zero.

Primary sources:

- [FDA Daily Value reference guide](https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels)
- [FDA explanation of nutrients without an established or ordinarily displayed %DV](https://www.fda.gov/food/nutrition-facts-label/how-understand-and-use-nutrition-facts-label)
- [2016 Nutrition Facts final rule, 81 FR 33742](https://www.federalregister.gov/citation/81-FR-33880)
- [FDA compliance-date guidance](https://www.fda.gov/media/134505/download?attachment=)

The catalog is checked into the backend; runtime network access and scraping are not used.

## Personal estimate policy

The optional energy estimate uses the 1990 Mifflin–St Jeor resting-energy equation:

- male equation: `10 × kg + 6.25 × cm − 5 × age + 5`
- female equation: `10 × kg + 6.25 × cm − 5 × age − 161`

The source population was healthy adults ages 19–78, which is the product's supported estimate range. Metric inputs are stored; API inputs may use exact `cm`/`kg` or `in`/`lb` conversion factors. The resting estimate is multiplied by the explicitly selected physical-activity factor and rounded once to the nearest whole kcal using Decimal `ROUND_HALF_UP`.

Activity choices are a bounded product policy within the NIH Body Weight Planner's published typical physical-activity-level range: sedentary 1.4, lightly active 1.6, active 1.8, and very active 2.0. These labels are estimates, not measured activity. No exercise adjustment or weight-change deficit is added.

Example: a 30-year-old equation-male profile at 70 kg and 175 cm has resting energy `1,648.75 kcal`; sedentary multiplication is `1,648.75 × 1.4 = 2,308.25`, returned as `2,308 kcal/day`.

Primary sources:

- [Mifflin et al., 1990, PubMed PMID 2305711](https://pubmed.ncbi.nlm.nih.gov/2305711/)
- [NIH/NIDDK Body Weight Planner activity-level and adult-use guidance](https://www.niddk.nih.gov/bwp.)

Incomplete profiles return `target_profile_incomplete`. Ages outside 19–78 return `target_estimate_unsupported_age`. Pregnancy, lactation, and specialized-medical contexts return `target_estimate_unsupported_context`. The app does not estimate for those cases and describes estimates as general information, not medical advice.

## Persistence, macros, and authority

The existing one-to-one `user_profiles` table stores only birth date, equation sex, normalized height/weight, activity, and estimation context. Existing `nutrition_targets` rows store optional manual overrides for calories, protein, total carbohydrate, and total fat. Calculated estimates are not persisted. Stage 7A does not support percentage-based macro allocation; personal macro targets are manual only.

Authority is deterministic: manual override, calculated calorie estimate, FDA Daily Value fallback, then unavailable. Profile changes never overwrite manual rows. `DELETE /api/v1/targets/overrides/{nutrient_id}` explicitly resets one override.

## Comparison and API

- `GET /api/v1/targets` returns profile configuration, calculated availability, manual overrides, effective targets, catalog version, limitations, and informational notice.
- `PUT /api/v1/targets` replaces the bounded profile and override configuration.
- `DELETE /api/v1/targets/overrides/{nutrient_id}` resets one override.
- `GET /api/v1/targets/daily-comparison?date=YYYY-MM-DD` compares the existing snapshot summary with effective targets.

Comparison uses Decimal arithmetic and returns consumed amount, target amount, canonical unit, uncapped percentage, authority, unknown-contributor metadata, and `available`, `target_unavailable`, or `consumed_unavailable`. An explicit snapshot zero produces 0%; an absent nutrient remains unavailable. Display rounding is a later UI boundary; the API preserves four decimal percentage places.

Settings → Nutrition targets is optional and uses neutral terms: **Estimated maintenance calories**, **Personal target**, and **FDA Daily Value**. The feature adds no analytics and does not send profile or target fields outside the existing backend account model.
