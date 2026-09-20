# #294 Concise Zero-Shot Producer

Owning issue: #294

## Problem / hypothesis

현재 Prompt의 instruction 복잡도를 줄이고 requested-fact boundary만 보존하면 qwen3.5:9b first-response semantic quality가 개선되는지 비교했다.

## Baseline / candidate

- Arm A: current production Prompt 1.0.62, zero-shot
- Arm B: approved concise zero-shot instruction
- 유일한 model-visible arm 차이: instruction text
- Product SHA: `2cc7b3aae22b81a06174ded393881001df2662b8`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Runtime: `LOCAL_GPU`, `/api/generate`
- Attempts/responses/complete raw pairs: 26/26/13

## Historical v1 evaluation

`INVALID_FOR_FINAL_COMPARISON`

Strict semantic-valid A 2/13 → B 1/13, omission 4→7, missing 6→10,
extra 13→23, semantic-valid candidates 7/20→3/26으로 기록됐다. 이 점수는 defective
derived Gold/Grader/Validator를 사용했으므로 최종 Decision authority가 아니다.

## Corrected v2 evaluation

- Evaluator commit: `40fb5c23fc5bb5e9517b3d13a48acce99c5b6220`
- Strict denominator: `SCORABLE` 8 cases
- Raw first-response를 v2 scorer로 직접 재채점
- Qwen/provider calls: 0

| Metric | Arm A | Arm B |
| --- | ---: | ---: |
| Strict semantic-valid | 2/8 | 1/8 |
| Semantic-valid candidates | 7/13 | 3/14 |
| Omission cases | 2 | 5 |
| Missing items | 2 | 6 |
| Extra items | 6 | 11 |
| Fact-kind correct | 7/13 | 6/14 |
| Role correct | 10/13 | 6/14 |
| Exact provenance span | 12/13 | 9/14 |
| Textual provenance valid | 12/13 | 9/14 |
| Identity diagnostics | 3 | 4 |
| Constraint-overlap diagnostics | 9 | 8 |
| Provenance-only false rejects | 0 | 0 |
| Authority-eligible cases | 2/8 | 1/8 |

### Transition

- PASS→PASS: 1 — `RU-B-001`
- PASS→FAIL: 1 — `RU-E-001`
- FAIL→PASS: 0
- FAIL→FAIL: 6

### Applicability outside the strict denominator

- `NOT_APPLICABLE`: `RU-D-001`, `RU-E-003`, `RU-G-003`
- `UNSCORABLE`: `RU-A-003`, `RU-B-002`

## Cost

Semantic denominator와 같은 8 paired cases 기준:

| Metric | Arm A | Arm B | Change |
| --- | ---: | ---: | ---: |
| Input tokens | 21,832 | 17,408 | -20.26% |
| Output tokens | 1,402 | 1,310 | -6.56% |
| Latency | 421,706 ms | 351,407 ms | -16.67% |

전체 13 complete raw pairs 기준 input 35,474→28,285 (-20.27%), output
2,322→2,257 (-2.80%), latency 690,108→592,275 ms (-14.18%)다.

## Decision

`REJECT`

Token과 latency 감소는 secondary metric이다. Corrected v2에서 새 PASS가 없고 기존
PASS 한 건이 regression했다. Omission, missing, extra, identity 혼입이 증가하고 candidate
semantic, role, provenance, authority quality가 감소했다.

## Artifacts / production effect

- Historical observations: `evaluation/results/ru294-concise-zeroshot-ab-20260920/observations.json`
- Historical observations SHA-256: `333d04b5a37869ce4ea0680b95b53f0d2fd75b5128d9b13f2e636d31cbde50ea`
- Corrected rescore: `evaluation/results/ru294-corrected-v2-rescore-20260920/rescore.json`
- Corrected rescore SHA-256: `e164f38eb03a099387f621e1f37abbca32db0519f91c722be6e671553cb9f9bb`
- Production diff/revert: 없음 / 필요 없음

## Revisit condition

Semantic quality를 개선하는 별도 ownership 또는 model strategy가 사전 등록될 때만 재검토한다.
