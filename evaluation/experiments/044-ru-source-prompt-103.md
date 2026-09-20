# RU Source Prompt 1.0.3

Owning issue: #287

## Problem / hypothesis

Source-dependency Prompt 1.0.3이 focused source-responsibility cases를 개선하는지 확인했다.

## Baseline / candidate

- Product SHA: `2cc7b3aae22b81a06174ded393881001df2662b8`
- Stored comparison: source-dependency Prompt 1.0.2를 사용한 P0-1 run
- Candidate: source-dependency Prompt 1.0.3
- 주의: 두 artifact 모두 `official_baseline=false`이며 candidate artifact가 baseline link를 직접 기록하지 않았다. 아래 비교는 동일 Dataset/subset/model/runtime/grader를 사용한 저장 artifact 간 비교다.

## Dataset / runtime

- Dataset: `evaluation/development_datasets/agent/ru_quality_dev_v2.jsonl`
- Dataset SHA-256: `db1e86c80f67db113baa28626bbd14f014ed3d18c26c7452077547ed6dd6d59d`
- Focused subset: 13 cases, source target 9 + controls 4
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Runtime: `LOCAL_GPU`, production Request Understanding subgraph
- Grader: `ru-quality-dev-grader-v2`, SHA-256 `664ed0d35923ad2a71a0f80521dee6852558bf5bd0c2bec58d1ccced60bdfd5e`

## Metrics

| Metric | Stored comparison | Prompt 1.0.3 |
| --- | ---: | ---: |
| Attempts / completed | 13 / 12 | 13 / 13 |
| Strict PASS | 1/13 | 1/13 |
| Source target PASS | 0/9 | 0/9 |
| Input tokens | 172,871 | 188,268 |
| Output tokens | 5,282 | 5,579 |
| Latency | 2,371,580 ms | 2,598,374 ms |

- FAIL→PASS: 0
- PASS→FAIL: 0
- Input tokens: +15,397, +8.91%
- Latency: +226,794 ms, +9.56%

## Failure signatures / regression

Candidate failures were dominated by source-responsibility mismatch: 7 cases. 추가 strict PASS 없이 token과 latency가 증가했다.

## Decision

`REJECT — CONFIRMED`

새 PASS와 target PASS가 없고 비용만 증가했다. Derived requested-fact evaluator를 사용하지 않았으므로 #294 evaluator 결함의 직접 영향은 없다.

## Artifact / production effect

- Artifact: `evaluation/results/ru-quality-dev-20260918/ru-quality-dev-source-prompt-1.0.3-focused-13case.json`
- Artifact SHA-256: `3a76dd220473a4b48e18b75d2407edfd1baaf70ac9cb182830ea6f1215ea36d0`
- Production diff: 없음
- Revert: 필요 없음

## Revisit condition

새 source-responsibility contract 또는 다른 model strategy가 사전 등록된 비교에서 target semantic PASS를 만들 때만 재검토한다.
