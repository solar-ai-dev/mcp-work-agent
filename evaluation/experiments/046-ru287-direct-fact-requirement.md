# #287 P0-2 Direct-Fact Requirement

Owning issue: #287

## Problem / hypothesis

Goal 단계 direct-fact requirement와 source binding을 추가하면 user-requested fact가 source responsibility로 전달되는지 확인했다.

## Baseline / candidate

- Stored comparison: P0-1 Preservation Floor
- Candidate: evaluation-only direct-fact candidates and bindings
- Product SHA: `2cc7b3aae22b81a06174ded393881001df2662b8`
- Dataset/subset: RU v2 focused 13
- Model/runtime: `qwen3.5:9b`, digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, `LOCAL_GPU`
- Grader: original `ru-quality-dev-grader-v2`

## Metrics

| Metric | P0-1 | P0-2 |
| --- | ---: | ---: |
| Completed | 12/13 | 10/13 |
| Strict PASS | 1/13 | 1/13 |
| Source target PASS | 0/9 | 0/9 |
| Input tokens | 172,871 | 164,039 |
| Output tokens | 5,282 | 5,638 |
| Latency | 2,371,580 ms | 2,577,469 ms |
| Execution failures | 1 | 3 |

- Direct-fact candidates: 14
- Bindings: 11
- Binding kinds: identity 10, subject 1
- Execution failures: runtime 1, schema contract 1, semantic contract 1

## Failure signatures / regression

Bindings 대부분이 user-result fact가 아니라 resource identity로 수렴했다. Strict 개선 없이 완료율이 낮아지고 latency가 8.68% 증가했다.

## Decision

`REJECT — CONFIRMED`

Meaningful requested-fact 개선이 없고 identity 편향 및 execution regression이 발생했다. Derived #294 evaluator의 직접 영향은 없다.

## Artifact / production effect

- Artifact: `evaluation/results/ru-quality-dev-20260919/ru-quality-dev-p0-2-focused-13case.json`
- SHA-256: `8b419c0f75a87c8d0d6dd5edadeca53cb3032973e6971e124d1f5f86b613c61a`
- Production diff: 없음
- Revert: 필요 없음

## Revisit condition

Identity와 requested result fact를 분리한 typed contract가 먼저 정의될 때만 재검토한다.
