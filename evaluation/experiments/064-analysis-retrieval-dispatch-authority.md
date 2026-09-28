# 064 — Work Analysis / Retrieval 실제 dispatch 관측 및 0-call preflight

## 목적과 범위

- 변경 전 재현 기준: `a00cd0f1e9c1451ffdc4c7f65f309193f6318ec7`.
- 구현 통합 parent: `9e0a68f30f4d1ccf8f3d2f0d6da7ae12e8aa2061`.
- 확정된 두 graph의 예산 사전검사·관측 결함만 수정한다. Prompt, Schema, State, semantic owner, retry/limit, Approval/Execution 정책 변경은 없다.
- 검증은 합성 inference/Connector 결과와 실제 Product graph·semantic owner·`account_provider_dispatch`를 연결한 component 검사다. 실제 모델/외부 Provider 호출은 0이다. Canonical 92 또는 업무 성공률 결과가 아니다.

## 최초 손실과 수정

| 경계 | 변경 전 결함 | 수정 및 보존한 authority |
| --- | --- | --- |
| Work Analysis extract / duplicate | dispatch가 기존 budget dict를 in-place 갱신한 뒤, 그 객체와 반환 budget을 빼서 실제 호출을 0으로 기록했다. duplicate에서 relation과 Task satisfaction이 각각 scope를 쓰면 일부 호출만 남을 수도 있었다. | 진입 시 `llm_calls_used` 정수를 캡처하고 해당 owner가 반환한 budget에서 뺀다. nested scope가 합친 반환 budget을 외부의 오래된 ContextVar로 다시 덮지 않는다. |
| Work Analysis entity / temporal / information gaps / action necessity / risks | Prompt가 있으면 trace를 1로 올려 repair/fallback을 포함한 2~3 dispatch를 1로 기록했다. | 기존 dispatch ledger의 진입·반환 차이로 trace를 기록한다. 결정적 duplicate/action 경로는 원 state budget과 0-call을 보존한다. |
| Retrieval select_evidence | 빈 후보·exact selection 등 기존 결정적 경로도 unconditional preflight에서 호출 상한 소진을 이유로 차단됐다. | 기존 semantic owner가 실제 `infer`를 요청할 때만 preflight/bind한다. shortcut 판단을 graph에 복제하지 않는다. 호출하지 않았다면 현재 반환 budget을 보존하고 stale ContextVar를 merge하지 않는다. |
| Retrieval sufficiency | `structured_output_attempts=1`을 실제 호출수로 취급했다. 확인 응답 후 같은 owner를 재호출하는 finalize 경로는 budget에는 반영해도 trace에 더하지 않았다. | 일반 진입과 confirmation resume 각각의 실제 ledger delta를 기록한다. 기존 메타데이터 형상은 그대로이며 호출량 authority로 사용하지 않는다. |

실제 소비 budget은 변경 전에도 provider dispatch 경계에서 부과됐다. Work Analysis의 alias/기본값 및 sufficiency의 고정값 오류는 관측 누락이며, 예산을 회피했다는 뜻이 아니다. select_evidence에서만 실제 0-call 경로를 잘못 거절하는 실행 제어 결함도 확인했다. 진짜 모델 호출이 필요한 selection/confirmation은 상한 소진 시 계속 거절된다.

## 직접 RED → GREEN

변경 전 두 graph의 해당 메서드를 `git show a00cd0f1:<path>`에서 AST로 읽어 현재 Python 프로세스 메모리에만 바인딩했다. checkout/reset, 파일 덮어쓰기, 모델 호출은 하지 않았다. 같은 고정 반례 22개에서 **13 FAIL / 9 PASS**를 재현했다.

- Work Analysis 4 semantic invokes에서 실제 dispatch가 각각 1/2/3이면 budget은 4/8/12인데 trace는 모두 2였다. extract/duplicate의 alias 차감과 다른 owner의 기본 1이 합쳐진 결과다.
- entity/temporal의 실제 2/3 dispatch가 trace 1이었다.
- 일반 sufficiency의 실제 2/3 dispatch가 trace 1이었다.
- confirmation-resume sufficiency의 실제 1/2/3 dispatch가 trace에는 추가되지 않았다.
- 빈 selection을 예산 100에서 실행하면 inference 0회인데 `ABSOLUTE_LLM_LIMIT_EXHAUSTED`가 발생했다.
- 정상 1-dispatch, 실제 호출 필요 시 cap 거절, 기존 결정적 no-call 보존은 control로 유지했다.

수정 후 같은 22개는 **22 PASS**다. 이어 Task relation+satisfaction의 nested scope와 Action owner를 포함한 compiled control 3개를 추가했다. 최종 **신규 25개를 포함한 인접 294 tests PASS (4.34s)**, Ruff PASS, mypy 3 files PASS다.

상위 작업에서 이어 수행한 RU~안전 경계 broader gate는 **2291 PASS (13.65s)**다. 294개와 중복되므로 둘을 합산하지 않는다. 전체 pytest/모델 평가는 아니다.

추가 고정 불변식:

- selection FIRST가 구조적으로 누락된 합성 결과를 내어 기존 semantic revision을 1회 사용: infer 2회 × actual dispatch 2회 = delta 4, `semantic_revisions_used_by_failure=1` 모두 보존.
- state budget 100 / 오래된 ContextVar 1일 때 결정적 Work Analysis와 빈 selection·일반 sufficiency는 state 100 및 trace 0을 보존한다.
- confirmation 응답을 다시 판단하는 기존 non-deterministic 경로는 budget 100에서 여전히 호출 전에 거절된다.
- Task 모드 compiled control은 relation, requested Task satisfaction, action necessity 호출을 모두 통과하며 nested owner의 실제 dispatch를 누락하지 않는다.
- component supervisor stub은 finalize에서 trace를 교체하므로 compiled trace 검사는 **finalize 직전 실제 graph 값**을 사용했다. 최종 budget/분석 결과/다음 route는 별도로 확인했다. 실제 Product `project_supervisor_state`는 state/stage/decision trace를 merge하는 기존 코드가 있으며 이 작업은 그 merge를 변경하지 않았다.

## 검증 명령

```powershell
.venv/Scripts/python.exe -m pytest -q tests/component/langgraph/test_production_agent_subgraphs.py tests/unit/application/agents/work_analysis tests/architecture/langgraph/subgraphs/work_analysis tests/unit/adapters/langgraph/subgraphs/work_analysis tests/unit/application/agents/retrieval/test_select_evidence.py tests/unit/application/agents/retrieval/test_assess_sufficiency.py tests/unit/application/agents/retrieval/test_assess_sufficiency_disposition.py tests/unit/adapters/langgraph/subgraphs/retrieval/test_select_evidence_projection.py tests/architecture/langgraph/subgraphs/retrieval/test_select_evidence_node.py tests/architecture/langgraph/subgraphs/retrieval/test_assess_sufficiency_node.py
.venv/Scripts/python.exe -m ruff check src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py src/google_work_agent/adapters/langgraph/subgraphs/work_analysis/graph.py tests/component/langgraph/test_production_agent_subgraphs.py
.venv/Scripts/python.exe -m mypy src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py src/google_work_agent/adapters/langgraph/subgraphs/work_analysis/graph.py tests/component/langgraph/test_production_agent_subgraphs.py
```

## 한계 및 미변경

- 합성 runtime의 2/3 dispatch는 실제 ledger 다중 호출 반례이지 실모델 schema repair/fallback 품질 평가가 아니다. 기존 실제 CORE005 T3는 sufficiency 1회·repair 0이고 Work Analysis를 건너뛰었으므로 이번 결함의 실모델 재현 근거로 주장하지 않는다.
- 오류로 node update 자체가 반환되지 않는 경우의 durable ledger는 기존 실행 coordinator/dispatch guard authority를 유지한다. 새로운 공통 예외 계측 framework를 추가하지 않았다.
- Work Analysis의 confirmation resolution clear가 return 뒤에 있는 별도 코드 관찰은 본 변경에 섞지 않았다. 정상 재진입에서의 의미 수명 결함 여부는 별도 근거가 필요하다.
- Product Prompt/Schema/State 및 외부 승인·WRITE 정책 변경 0. 실제 Provider WRITE/SEND 0. 모델 실행 0. commit/push는 상위 작업에서 수행한다.
