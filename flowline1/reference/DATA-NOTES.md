# Location data for the expansion scene (checked 2026-11-08/09)

## PRIMARY (global judges): US Census, ZIP level — use this on stage
- Data (no API key; bulk files): ZIP Code Business Patterns detail + totals 2014/2017/2020/2023
  `https://www2.census.gov/programs-surveys/cbp/datasets/{YYYY}/zbp{YY}detail.zip` (and `zbp{YY}totals.zip`);
  County Business Patterns `cbp{YY}co.zip`; ACS 2015–19 5-yr by ZCTA (summary file seqs 0001/0027/0042/0058/0078);
  2020 Gazetteer ZCTA; county pop estimates. api.census.gov now needs a key (302) — bulk files don't.
- Outcome: net new establishments 2020→2023 per ZIP × NAICS (unit size not available at ZIP level).
- Features (2020 conditions only): ~35-industry local mix, jobs, payroll, business growth 2017→20, competitors in
  ZIP and within 5–10 km, population, density, income, age, education, commuting. Gradient boosting.
- Honesty: trained on 2017→2020, scored on 2020→2023; each ZIP scored by a model that never saw its 3-digit region.
- Cold start (ZIPs with <3 units in 2020 → did they reach 3+ by 2023?), lift = top-10% hit rate ÷ average:
  - **Fitness 713940: 7.4× (95% CI 7.1–7.7), 29% vs 4%, AUC 0.93; population alone 5.7×** (paired diff +1.7)
  - Coffee/snack 722515: 6.0× vs 5.1× · Physicians 621111: 5.4× vs 5.5× (TIE — say so) · Pooled 6.3× vs 5.2×
- Do NOT claim unit economics: county-level payroll/employees per establishment ties persistence.
- Austin TX demo (85 ZIPs, out-of-fold): 78704 pred +3.4 / actual +5 · 78738 +2.9 / +6 · 78660 +2.8 / +2 ·
  78701 +2.6 / +4 · 78613 +2.6 / +2 (metro mean +1.1, median 0). Spearman 0.55 vs 0.39 population.
  Top-5-by-population averaged +3.4 vs model +3.8 — the edge at top-5 is small; the national lift is the claim.
- Caveats: "<3" is the Census disclosure floor; NAICS 713940 also includes yoga studios/pools/rinks; 2020 ZBP is
  March 2020 so the test spans COVID.
- Stage line (true): "We froze the clock at 2020 and hid whole regions of the US from our model. Among ZIP codes
  with fewer than three fitness centers, the 10% it ranked highest were 7.4× as likely to have three or more by
  2023 — 29% versus 4% — while picking by population gets you 5.7×."
- Scripts/results (reference only, don't commit): this session's scratchpad `us-backtest/`.

## SECONDARY (Korea-only, keep for Q&A): Seoul 상권분석서비스

Bottom line: Seoul 상권분석서비스 추정매출 + 점포, 2021–2025, no login. Frame the demo as RANKING candidate
sites (measurable lift), not a precise sales forecast.

## Datasets
- 추정매출-상권 OA-15572 — https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do
- 점포-상권 OA-15577 — https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do
  - Publisher 서울신용보증재단 / 서울시. License 공공누리 1유형 (commercial OK with attribution).
  - Yearly ZIP download without login: POST https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do
    `infId=OA-15572&seq=47..51&infSeq=3` (sales, 2021–2025) · `infId=OA-15577&seq=16..20` (stores).
  - Quarterly, ~1,580 상권 (골목/발달/전통시장/관광특구). Files 2021Q1–2025Q4; API to 2026Q2 (needs free key).
  - Sales covers 62–63 industries, stores 100. CP949 encoding; 2025 store file uses English headers.
  - Codes: 스포츠클럽 CS200024 · 스포츠 강습 CS200005 · 골프연습장 CS200017 · 일반의원 CS200006 ·
    치과의원 CS200007 · 한의원 CS200008 · 커피-음료 CS100010 · 미용실 CS200028 (헬스장/필라테스 code unverified).
  - Pitfalls: 추정매출 is itself a model (신한카드 ÷ correction). No store-level sales → target = area×industry
    sales ÷ 유사업종 점포수. `당월_매출_금액` holds the quarter total.
- Same-code joins: 길단위인구 OA-15568 · 상주인구 OA-15584 · 직장인구 OA-15569 · 집객시설 OA-15580 · 영역 OA-15560.
- Exact open/close events: Seoul API LOCALDATA_104201 (체력단련장업, 7,364) · LOCALDATA_010102 (의원, 37,773);
  fields APVPERMYMD, DCBYMD, TRDSTATENM, SITEAREA, X/Y (EPSG:5174). National file: data.go.kr 15045048 / 15045024
  (captcha — download by hand).
- Avoid: 생활인구 OA-14991 (ended 2026-07-31). Advan/SafeGraph (paid). Yelp only as non-Korean fallback.

## Backtest already run tonight (reference only — rewrite from scratch at the event)
- Target log per-store quarterly sales; features from t-4 only (surrounding industry mix, store counts, openings,
  closings, franchises, weekend share, 상권 type); HistGradientBoosting; train 2022–2024, test 2025 on 20% held-out 상권.
- Cold start (no own-industry sales in that area), n=16,571:
  - **Top-10% recommended 상권 earned 2.47× the median 상권's actual 2025 per-store sales** (pooled).
  - 커피 3.8× · 미용실 2.75× · 일반의원 1.74× · 스포츠클럽 1.33× · 치과/한의원 ≈1.0× (weak — say so).
  - Spearman within industry 0.41; median abs log error 0.58 vs 0.65 baseline.
- Warm (own last-year sales known): repeating last year beats the model (0.20 vs 0.23). Honest line:
  "where competitors already exist, last year's local category sales ARE the forecast; the model earns its keep
  ranking new areas."
- Don't headline MAPE (blows up on tiny denominators). Use top-10% lift.
- Prototype script + downloaded CSVs are in this session's scratchpad (not in this folder) — reference only,
  do not commit them; the event rule bans pre-build commits.
