# #294 Minimal Few-Shot Producer

Owning issue: #294

## Problem / hypothesis

현재 production Prompt 1.0.62에 5개 최소 few-shot 예시를 추가하면 requested-fact producer semantic quality가 개선되는지 비교했다.

## Baseline / candidate

- Arm A: current production Prompt 1.0.62
- Arm B: 동일 Prompt + pre-registered five-shot suffix
- Product SHA: `2cc7b3aae22b81a06174ded393881001df2662b8`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Runtime: `LOCAL_GPU`, `/api/generate`
- Generation: temperature 0, seed 294, `num_ctx=16384`, timeout 180초
- Dataset: RU v2 focused 13
- Attempts/responses/complete raw pairs: 26/25/12
- `RU-A-003/A`: `TimeoutError`; response와 retry 없음, timeout envelope 보존

## Historical v1 evaluation

`INVALID_FOR_FINAL_COMPARISON`

12 complete pairs에서 strict semantic-valid A 2/12 → B 0/12, omission 4→7,
missing 6→10, extra 12→14, semantic-valid candidates 7/19→3/17로 기록됐다.
이 점수는 defective derived Gold/Grader/Validator를 사용했으므로 최종 Decision authority가 아니다.

## Corrected v2 evaluation

- Evaluator commit: `40fb5c23fc5bb5e9517b3d13a48acce99c5b6220`
- Strict denominator: 양 arm에 raw response가 있는 `SCORABLE` 8 cases
- Raw first-response를 v2 scorer로 직접 재채점
- Qwen/provider calls: 0

| Metric | Arm A | Arm B |
| --- | ---: | ---: |
| Strict semantic-valid | 2/8 | 0/8 |
| Semantic-valid candidates | 7/13 | 3/13 |
| Omission cases | 2 | 5 |
| Missing items | 2 | 6 |
| Extra items | 6 | 10 |
| Fact-kind correct | 7/13 | 4/13 |
| Role correct | 10/13 | 9/13 |
| Exact provenance span | 12/13 | 12/13 |
| Textual provenance valid | 12/13 | 12/13 |
| Identity diagnostics | 3 | 3 |
| Constraint-overlap diagnostics | 9 | 6 |
| Provenance-only false rejects | 0 | 0 |
| Authority-eligible cases | 2/8 | 0/8 |

### Transition

- PASS→PASS: 0
- PASS→FAIL: 2 — `RU-B-001`, `RU-E-001`
- FAIL→PASS: 0
- FAIL→FAIL: 6

### Applicability outside the strict denominator

- `NOT_APPLICABLE`: `RU-D-001`, `RU-E-003`, `RU-G-003`
- `UNSCORABLE`: `RU-A-003`, `RU-B-002`
- `RU-A-003/A` timeout은 UNSCORABLE이며 재실행하지 않았다.

## Cost

Semantic denominator와 같은 8 paired cases 기준:

| Metric | Arm A | Arm B | Change |
| --- | ---: | ---: | ---: |
| Input tokens | 21,832 | 24,272 | +11.18% |
| Output tokens | 1,397 | 1,299 | -7.02% |
| Latency | 432,262 ms | 435,556 ms | +0.76% |

전체 12 complete raw pairs 기준 input 32,787→36,447 (+11.16%), output
2,152→1,931 (-10.27%), latency 643,981→644,911 ms (+0.14%)다.

## Decision

`REJECT`

Corrected v2에서도 FAIL→PASS가 없고 기존 PASS 두 건이 regression했다. Omission,
missing, extra가 모두 증가했고 semantic-valid candidate와 authority-eligible case가 감소했다.

## Artifacts / production effect

- Historical observations: `evaluation/results/ru294-producer-ab-20260919/observations.json`
- Historical observations SHA-256: `626184b22db2891fda8502f5faaaec9b59c4c02cd3231f35861997b8b816deea`
- Corrected rescore: `evaluation/results/ru294-corrected-v2-rescore-20260920/rescore.json`
- Corrected rescore SHA-256: `e164f38eb03a099387f621e1f37abbca32db0519f91c722be6e671553cb9f9bb`
- Production diff/revert: 없음 / 필요 없음

## Revisit condition

Prompt examples가 아닌 별도 semantic ownership 또는 model strategy를 사전 등록할 때만 재검토한다.
