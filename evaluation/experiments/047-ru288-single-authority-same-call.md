# #288-B Single-Authority Same-Call

Owning issue: #288

## Problem / hypothesis

`identify_goal` 한 호출이 기존 goal 책임과 requested-fact producer 책임을 함께 소유할 때 semantic quality와 handoff가 개선되는지 확인했다.

## Baseline / candidate

- Stored comparison: #287 P0-2 artifact
- Candidate: `identify_goal` Prompt 1.0.63에서 `requested_fact_candidates`를 같은 호출로 생성
- Product SHA: `2cc7b3aae22b81a06174ded393881001df2662b8`
- Dataset/subset: RU v2 focused 13
- Model/runtime: `qwen3.5:9b`, digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, `LOCAL_GPU`
- Grader: original `ru-quality-dev-grader-v2`

## Metrics

| Metric | P0-2 | #288-B |
| --- | ---: | ---: |
| Completed | 10/13 | 5/13 |
| Strict PASS | 1/13 | 0/13 |
| Semantic PASS | 1/11 | 0/5 |
| Runtime failures | 1 | 8 |

- `RU-F-001`: PASS→FAIL runtime regression
- Validated bindings observed: 3 (`RU-A-003` 1, `RU-E-001` 2)
- Binding/handoff 관측은 성공했지만 두 case 모두 최종 semantic FAIL

## Decision

`REJECT — CONFIRMED`

Producer omission/semantic error와 8 runtime failures가 handoff 관측 이점을 압도했다. Derived #294 evaluator를 사용하지 않았으므로 그 결함의 직접 영향은 없다.

## Candidate F

`NOT RUN / HOLD`

Candidate F는 #288-B와 달리 goal과 requested-fact 판단을 두 호출로 분리하는 가설이다. Two-stage 자체가 실패한 것이 아니며, 비교 authority였던 derived requested-fact evaluator가 corrected v2로 교체되기 전에는 실행하지 않는다.

## Artifact / production effect

- Artifact: `evaluation/results/ru-quality-dev-20260919/ru-quality-dev-288-b-focused-13case.json`
- SHA-256: `9040f3148ec957bfa98eef18b161e7826cd0c32541b6fed23667c751f45537b5`
- Production diff: 없음
- Revert: 필요 없음

## Revisit condition

Candidate F는 corrected evaluator를 기준으로 별도 사전 등록하고 사용자가 실행을 승인할 때만 진행한다.
