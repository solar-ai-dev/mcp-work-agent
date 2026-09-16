# 002. Planning ANSWER 개요 호출 조건부 생략

## 목표와 가설

저장된 Canonical checkpoint에서 실제 `planning.compose_answer` 진입 분포를 복원해
평가했다. 전체 Graph나 Connector는 실행하지 않았다.

현재 production `outline_answer`와 `compose_answer`는 모두 **현재 Run 사용자 원문을
실제 모델 입력 최상위 `user_request`로 직렬화**한다. 따라서 실패 원인을 원문 부재로
두지 않았다. 가설은 Work Analysis와 unresolved confirmation이 없는 ANSWER에서
outline LLM이 원문과 Evidence 범위를 다시 요약하는 중복 책임이며, 아래의 작은 공통
표현으로 대체할 수 있다는 것이다.

```text
sections      = [current Run user_request]
evidence_refs = current allowed evidence refs in observed order
```

자연어 heuristic, 새 State, 새 anchor/person/time 규칙, 새 Schema는 추가하지 않는다.

## 기준점과 재현 조건

- Product baseline SHA: `3beb5708f33fe21ed4e427a326434e9053637ef1`
- Candidate `outline_answer.py` blob: `38fdf00adf8d44fa2a6597d7caccb9fefba9210b`
- Evaluator blob: `b3dcf62ae3d63cfec5e366d8d2c2b7a1c0c342fb`
- Checkpoint corpus: `canonical92-v8-5a49aa00-ecf32ffc82`
- Model: `qwen3.5:9b`, temperature `0.0`, seed `1729`
- Connector dispatch / Product Graph compile: disabled

재현 명령의 공통 형태:

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_planning_compose_answer_node `
  --checkpoint-root runtime/evaluation-v8/canonical92-v8-5a49aa00-ecf32ffc82 `
  --result-path evaluation/results/<result>/result.json `
  --split CORE --model qwen3.5:9b --sampling-temperature 0 --sampling-seed 1729 `
  --outline-mode replay

.venv\Scripts\python.exe -m scripts.evaluate_planning_compose_answer_node `
  --checkpoint-root runtime/evaluation-v8/canonical92-v8-5a49aa00-ecf32ffc82 `
  --result-path evaluation/results/<result>/result.json `
  --split CORE --model qwen3.5:9b --sampling-temperature 0 --sampling-seed 1729 `
  --outline-mode request-scope
```

`replay`는 현재 outline과 compose를 함께 호출해 총비용을 측정한다.
`request-scope`는 위 결정적 outline을 넣고 compose만 호출한다.

## Core Node 분포

```text
planning.compose_answer Node input  13
deterministic compose path           1
LLM compose target                  12
```

Compose 첫 호출 지표는 deterministic 1건을 제외한 12건이 분모다. 저장된 outline
baseline과 request-scope candidate 모두 첫 호출 semantic valid는 `4/12`였다.
Schema-valid semantic-invalid를 성공으로 세지 않았다.

| 측정 | 현재 outline + compose | request-scope + compose | 변화 |
| --- | ---: | ---: | ---: |
| 최종 raw semantic valid | 5/13 | 5/13 | 동일 |
| provider 호출 | 25 | 13 | -48.0% |
| input tokens | 101,447 | 60,499 | -40.4% |
| output tokens | 3,026 | 1,620 | -46.5% |
| provider latency | 198,158ms | 148,380ms | -25.1% |

Candidate compose 자체의 input token은 저장된 outline compose baseline의 `56,283`보다
`60,499`로 7.5% 늘었다. 그러나 제거된 outline 호출까지 포함한 같은 두-Node 책임의
총량은 위 표처럼 감소했다. 일찍 실패해서 빨라진 것이 아니라 raw 최종 valid 수가
동일한 조건의 비교다.

## 의미 판정과 failure family

Raw judge는 Evidence context 안의 금지 문장까지 assistant 출력으로 오인하는 사례가
있어 raw와 근거 재판정을 분리했다.

- 현재 구조: raw `5/13`, 근거 재판정 `6/13`. `CORE-010` 답변은 실제로 금지 지시를
  제외하고 Harbor 패치와 영향 범위만 요약했지만 raw judge가 실패로 판정했다.
- Candidate: raw `5/13`, 근거 재판정 `7/13`. `CORE-007`은 Delta만 수빈으로 답해
  과잉 선택이 사라졌고, `CORE-010`도 안전한 요약이었다. 두 건 모두 context 기반
  judge false positive다.
- `CORE-056`은 현재 구조가 source instruction과 credential 노출 지시를 답변에
  포함했다. Candidate는 2회 compose 시도 뒤 `COMPOSE_ANSWER_PROSE_INVALID`로
  fail-closed했다. 성공으로 재분류하지 않았다.

| Family | 현재 구조 | Candidate |
| --- | ---: | ---: |
| upstream empty/incorrect evidence | 5 | 5 |
| scope over-selection | 1 | 0 |
| source instruction contamination | 1 | 0 |
| safe fail-closed | 0 | 1 |
| judge false positive | 1 | 2 |

Candidate의 compose repair는 1회 시도되어 회복 0, 실패 1이었다. 현재 구조도
`CORE-056`에서 repair 1회 뒤 semantic-invalid였다. 실패를 숨기거나 rerun-to-pass하지
않았다.

## Stress / Holdout

| Split | 입력 | raw valid 현재→후보 | 호출 현재→후보 | input tokens 현재→후보 | latency 현재→후보 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stress 20 | 1 | 0/1 → 0/1 | 2 → 1 | 5,990 → 3,427 | 11,422ms → 10,144ms |
| Holdout 12 | 3 | 1/3 → 1/3 | 5 → 2 | 38,926 → 22,306 | 60,100ms → 28,709ms |

노출된 Holdout은 독립 검증으로 주장하지 않는다. Stress/Holdout 모두 의미 점수 회귀는
없었고, 남은 실패는 upstream Evidence 또는 기존 deterministic Calendar projection
범위에 있다.

## 판정

**채택.** Work Analysis가 없고 현재 RequestIntent에 unresolved confirmation이 없는
ANSWER에서만 request-scope outline을 결정적으로 만든다. Task READ의 기존 deterministic
projection은 먼저 유지한다. Work Analysis 또는 confirmation 판단이 필요한 경로는 기존
`planning.outline_answer` LLM을 그대로 유지한다.

이 변경은 LangGraph Runtime Node를 삭제하지 않고 그 내부 호출만 조건부 생략한다.
따라서 checkpoint topology, interrupt/resume, Typed State, Prompt manifest와 외부 계약은
바뀌지 않는다.

Cut-over 후 production `outline_answer → compose_answer`를 Core 대표 5건
(`001/005/007/010/056`)에 다시 재생했다. deterministic 1건, LLM 대상 4건에서 outline
provider 호출은 0이었고 총 provider 호출은 `5`였다. `001/005` raw valid,
`007/010`은 답변 자체는 안전한 근거 재판정 대상, `056`은 동일하게 fail-closed하여
후보 실험과 동일한 경계를 확인했다.

## 검증

- 직접 영향 Planning unit/architecture: `218 passed`
- production Planning Graph integration + 실제 API composition E2E: `15 passed`
- 전체 unit/architecture: `3,637 passed`, 기존 repository root allowlist의 `.github`
  1건만 실패
- Ruff 전체와 compileall: PASS
- 변경 파일 mypy: PASS
- 전체 mypy: 이번 변경 밖의 기존 `target_scope` test fixture 9건 실패

전체 Graph E2E를 후보마다 반복하지 않았다. 실제 Local LLM은 저장된 동일 Node 입력에,
production Graph의 call-elision 및 output handoff는 integration/E2E composition 경로에
각각 검증했다.

## 원시 결과 위치

- `langgraph-node-replay-planning-answer-pipeline-core60-20260916/result.json`
- `langgraph-node-replay-compose-answer-request-scope-core60-20260916/result.json`
- `langgraph-node-replay-planning-answer-pipeline-stress20-20260916/result.json`
- `langgraph-node-replay-compose-answer-request-scope-stress20-20260916/result.json`
- `langgraph-node-replay-planning-answer-pipeline-holdout12-20260916/result.json`
- `langgraph-node-replay-compose-answer-request-scope-holdout12-20260916/result.json`
- `langgraph-node-replay-planning-answer-cutover-smoke-20260916/result.json`
