# How prices are calculated

```
price per part = material
               + machining  (cycle time × machine rate)
               + inspection (in-process minutes × inspection rate)
               + outside processes (per part, plus lot charges ÷ quantity)
               + purchased components
               + (setup + programming + first article) ÷ quantity
then: − volume discount (machining, setup, programming only)
      + contingency (always)
      + margin
      → at least minimum order charge ÷ quantity, rounded UP ($0.05 under $100, $1 above)
```

## Inputs (all overridable on the estimate screen)

| Input | Where it comes from |
|---|---|
| Part envelope, volume, area | STEP model (exact B-rep). Drawing-only parts stay **unpriced** until the estimator types the envelope. |
| Stock | Envelope + allowance per side (milling) or round bar Ø + allowances (turned parts), + scrap %. |
| Material & price/kg | Detected from title block → drawing notes → email. Shop price if set, else reference price (marked as such, with a staleness warning). Unknown material → priced as stainless 316. |
| Complexity 1-10 | Setups, tightest tolerance band, GD&T count, surface finish, deep holes, deep pockets vs. corner radius, thin walls, small radii, undercuts, internal grooves, freeform faces, angled faces, feature count, threads, difficult material. Each driver is listed. Multiplies cutting time by `1 + 0.08 × (score − 1)`. |
| Cycle time | Roughing (removed volume ÷ removal rate × machinability) + finishing (area, Ra) + per-feature time (holes by depth and L/D, counterbores, countersinks, pockets, grooves, undercuts, threads, tight tolerances, fits) × complexity + handling per setup, + **uncertainty** % for each low-confidence or missing input, × calibration factor. |
| Setup, programming, first article | Per setup, per feature, scaled by complexity; 5-axis programming × 1.5; FAI adds time when AS9102 or GD&T is present. |
| Outside processes | Matched from drawing notes / email to your supplier list (anodize, hard coat, black oxide, passivation, plating, heat treat, certs, FAI…). Process words with no supplier entry get a conservative placeholder and a warning. |
| Machine type | Reference only: lathe / mill-turn for rotational parts, 5-axis for undercuts, freeform or angled faces, 4-axis for multi-side prismatic parts, else 3-axis; checked against your machines' travel. |

## Margin protection (bias toward slightly high)

- Unknown material → most expensive common grade.
- Missing drawing, low-confidence values, undercuts → extra uncertainty time (capped, configurable).
- Drawing-only parts are never priced from zero geometry.
- Unlisted outside processes → placeholder lot charge.
- All times are rounded up; prices are rounded up.
- Every adjustment is shown to the estimator with its reason.

## Calibrating with JobBOSS² data

1. Export jobs from JobBOSS² to CSV with part number, revision, customer, quantity, unit price,
   estimated hours, actual hours, material, date and status (column names are matched
   automatically; add Length/Width/Height in mm if available). Import under **Job history**.
2. Imported jobs immediately power the *Similar past jobs* panel.
3. To calibrate the time model, quote 20–50 past parts that have actual hours (upload their STEP +
   PDF as RFQs). The calibration panel compares engine hours with actual hours and suggests a
   **time calibration factor** (75th percentile of actual ÷ engine, so most jobs are covered).
   Enter it under Shop settings › Pricing policy.

Engine coefficients (removal rates, per-feature minutes) live in
`backend/app/services/costing/defaults.py` and `engine.py`; per-shop policy values are editable in
Shop settings.
