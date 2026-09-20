# #287 P0-1 Preservation Floor

Owning issue: #287

## Problem / hypothesis

Source identity를 보존하는 floor가 requested source facts와 source responsibility를 개선하는지 확인했다. 세부 hypothesis 문구와 별도 official baseline link는 artifact에 기록되지 않았다.

## Candidate / Dataset / runtime

- Experiment ID: `ru287-candidate-a-final-focused13-20260918`
- Product SHA: `2cc7b3aae22b81a06174ded393881001df2662b8`
- Prompt refs: production `identify_goal` 1.0.62, source dependency 1.0.2
- Dataset/subset: RU v2 focused 13; source target 9 + controls 4
- Model/runtime: `qwen3.5:9b`, digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, `LOCAL_GPU`
- Grader: original `ru-quality-dev-grader-v2`

## Metrics

- Attempts/completed: 13/12
- Strict/semantic PASS: 1/13
- PASS case: `RU-F-001`
- Source target PASS: 0/9
- Execution failures: semantic contract 1 (`RU-D-001` provenance binding)
- Provider calls: 76
- Input/output tokens: 172,871 / 5,282
- Latency: 2,371,580 ms
- Requested-fact-specific omission/missing/extra: `NOT RECORDED` by this grader

## Decision

`REJECT — CONFIRMED`

새 target PASS가 없고 requested-fact semantic 개선을 입증하지 못했다. Derived #294 Gold/Grader를 사용하지 않았으므로 그 결함의 직접 영향은 없다.

## Artifact / production effect

- Artifact: `evaluation/results/ru-quality-dev-20260918/ru-quality-dev-candidate-a-focused-13case.json`
- SHA-256: `fd57af194d2be23f29cc6489c33c6bfb900183671a105a79f2574275ae3e5d17`
- Production diff: 없음
- Revert: 필요 없음

## Revisit condition

Preservation을 명시적으로 관측하는 corrected contract와 target/control 근거를 사전 등록한 경우에만 재검토한다.
