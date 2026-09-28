# Planning route-local 호출 예산·관측 정합화

수정 기준 HEAD: `5caa9939`(결함 조사 시작 `72dd131a`와 Product 코드는 동일).
실제 모델 평가가 아닌 Product physical-node/component 결함 수정이다.
모델 호출 0, 외부 Provider READ/WRITE 0, Prompt·Schema·State·예산 상한 변경 0.

## 확정 원인과 영향

`PlanningSubgraph._draft_action_objective_node`와 `_compose_arguments_node`의 preflight는
각 Route에 **전역** RequestIntent/Evidence를 넣어 호출 필요 여부를 계산했다.
반면 실제 Application owner는 WorkUnit binding으로 Intent/Evidence를 좁힌 뒤
같은 결정적 작성 조건을 판단했다. 서로 다른 입력 때문에 다음이 재현됐다.

| Typed 입력 | 수정 전 | 수정 후 직접 검증 |
| --- | --- | --- |
| 독립 Task CREATE 두 개, 업무별 exact title이 각각 First/Second | 전역 title 충돌로 예상 2, 실제 0. budget 99/100에서 `ABSOLUTE_LLM_LIMIT_EXHAUSTED`로 불필요 차단. 여유 budget의 새 lazy Prompt cache에서는 실제 호출이 없어 ref가 없는데 trace가 참조해 `KeyError` | 두 Preview title 보존, 0 dispatch, trace 0. budget 사용량 0/99/100에서 모두 결정적 작성 |
| 첫 업무만 exact title, 두 번째는 적절한 title 작성 필요 | 전역 첫 title로 예상 0, route-local 실제 1. trace는 0으로 누락 | 두 번째 업무만 호출. 첫 title을 차용하지 않고 해당 Work/근거만 전달. 실제 dispatch 1 기록 |
| 한 semantic infer 안에서 FIRST + repair/fallback에 해당하는 dispatch 2회 | 예상 Route 수는 실제 Provider 호출 수를 표현하지 못함 | 기존 dispatch ledger의 정수 전후 차이 2 기록 |

수정 전의 trace 2/실제 0 메모리 확인은 Prompt ref가 이미 존재하는 조건이며,
새 인스턴스 lazy cache 조건에서는 잘못된 ref 접근으로 먼저 실패한다. 둘을 구분한다.
실제 budget 차감은 기존 `account_provider_dispatch` 권위였으므로 예상 숫자만큼
budget을 허위 차감했거나 실제 상한을 우회했다고 판정하지 않는다. durable accountant가
연결된 메모리 반례에서는 과소예측이어도 실제 dispatch가 차감되고 cap 100에서 차단됐다.

## 수정 경계

- 기존 Planning projection owner에 `project_route_semantic_inputs`를 두어 preflight와
  두 actual owner가 동일 WorkUnit별 Intent/Evidence를 소비한다. 원문·Goal을 새로
  해석하거나 변경하지 않고, 공유 Evidence는 복제하지 않는다.
- arguments의 결정적 payload 선택은 preflight와 작성이 같은 helper를 사용한다.
- 노드 진입 시 `llm_calls_used` **정수**를 저장하고 종료 시 기존 dispatch ledger와
  병합한 실제 budget 차이로 trace를 기록한다. semantic infer 횟수를 대신 쓰지 않는다.
- 실제 호출이 없으면 trace/local state에 사용하지 않은 Prompt ref를 붙이지 않는다.
  실제 호출이 있으면 lazy-loaded ref가 존재해야 하는 기존 불변식을 유지한다.
- `GmailDraftUpdateAlreadySatisfiedError`로 ANSWER를 반환해도 실제 2 dispatch가
  budget/trace에 남는다. 새 Action/WRITE는 만들지 않는다.
- `RequiredContainerUnresolvedError`는 모든 Tool schema/container를 LLM보다 먼저
  결속하는 현재 경계에서 발생한다. 실제 post-call 예외로 오인하지 않고 0 dispatch
  confirmation control을 고정했다. 공통 예외 framework를 확장하지 않았다.
- 미처리 timeout의 durable dispatch 보존은 기존 coordinator 경계이며 이번 변경은
  실패한 노드의 trace 반환까지 새로 설계하지 않는다.

## 직접 검증

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/adapters/langgraph/test_planning_route_call_budget.py tests/unit/adapters/langgraph/test_agent_kernel_budget.py tests/unit/application/agents/planning/test_project_request_intent_for_work_units.py tests/unit/application/agents/planning/test_draft_action_objective_per_output_route.py tests/unit/application/agents/planning/test_compose_arguments_per_output_route.py tests/unit/adapters/langgraph/test_planning_review_execution.py -q
```

결과: **95 passed**. 실제 Product physical Node와 fake structured runtime을 연결했고
fake runtime도 기존 `account_provider_dispatch`를 호출한다. 외부 모델·Provider는 없다.
추가 검증은 변경 source 4개 mypy, 관련 Python ruff, `git diff --check` PASS다.

상위 작업의 인접 회귀는 **2,019 passed / 10.32초**다. RU/Retrieval/Planning/Review,
LangGraph·Prompt architecture, budget/Approval/Claim/ExecutionAttempt/Verification/Recovery,
Provider dispatch checkpoint 및 Approval durability의 기존 검사를 단일 pytest 프로세스로
실행했다. 95개 직접 검사와 겹치므로 숫자를 합산하지 않는다. 전체 pytest는 아니다.
모델 실행과 겹치지 않았고 시작 시 RAM 여유20.1GB, GPU 유휴43°C였다.

확인 범위는 제어·계측 및 route-local handoff이며 Canonical 92, 실제 LLM 안정성,
Retrieval 이후 전체 업무 성공률이나 출시 승인을 의미하지 않는다.
최종 commit/push는 상위 작업에서 기록한다.
