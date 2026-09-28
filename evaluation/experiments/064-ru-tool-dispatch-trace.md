# RU / Tool Route 실제 dispatch Trace 정합화

수정 기준 HEAD: `00af8431`. Product physical-node의 계측 결함 수정이며
모델 품질 실험이 아니다. 모델 호출 0, 외부 Provider READ/WRITE 0.

## 원인과 확인 근거

- RU `identify_goal`은 호출 **후** State와 반환 patch의 budget을 뺐다.
  fresh Work 호출이 State의 mutable budget을 먼저 변경한 뒤 복사되므로
  Work dispatch가 빠졌다. confirmation resume에서는 같은 budget 객체를
  끝까지 사용하면 실제 호출이 있어도 차이가 0일 수 있었다.
- 기존 실제 결과
  `evaluation/results/064-work-span-codec-v35-connected-t1/CASE-CORE-005/production/raw.json`
  은 `retry_budget.llm_calls_used=7`, `trace_context.llm_call_count=6`이고
  인접 `calls.json`에 실제 wire 7회가 남아 있다. 원본 기록은 변경하지 않았다.
- RU temporal/ambiguity, Tool determine/selection은 호출 필요 여부 또는
  unique capability 개수를 기록했다. semantic infer 한 번에 여러
  FIRST/repair/fallback dispatch가 있어도 Trace가 이를 표현하지 못했다.
- 실제 RunBudget과 durable dispatch accountant는 이미 각 dispatch를
  차감하고 제한한다. 이 문제를 예산 우회나 실제 사용량 미차감으로
  판정하지 않는다. 별도 wire 관측 결과도 영향받지 않는다.

## 최소 수정

기존 두 graph의 다섯 physical-node wrapper에서 노드 진입 시
`llm_calls_used` **정수**를 저장하고, 기존 owner가 반환한 실제 사용량과의
차이를 `llm_call_count`에 반영한다. 처리된 validation 실패가 budget을
patch에 넣지 않는 경우에는 원래 State의 갱신된 authority를 사용한다.
실제 dispatch가 0이면 사용하지 않은 LLM call ID/Prompt ref도 추가하지 않는다.

새 counter, 예산 증액, Provider dispatch 변경, Prompt/Schema/State/Graph 변경은 없다.
WorkUnit binding, capability 공유, confirmation, 승인·실행 경계는 그대로다.
기존 capability 수 사전 추정은 실제 선택 owner의 책임이며 변경하지 않았다.

처리되지 않은 예외로 노드가 반환하지 않으면 이번 수정도 새 Trace patch를
만들지 않는다. 해당 dispatch의 durable 보존은 기존 coordinator/dispatch
계약이다. 새 예외 처리 framework를 만들지 않았다.

## 직접 검증

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/adapters/langgraph/test_ru_tool_dispatch_trace.py tests/unit/adapters/langgraph/test_request_understanding_budget_gate.py tests/unit/adapters/langgraph/test_tool_selection_capability.py tests/unit/adapters/langgraph/test_connector_prerequisite_node.py tests/component/langgraph/test_production_agent_subgraphs.py
```

**101 passed / 2.78초**. 기존 실제 thin node/Application owner와 재사용한
fake inference를 연결하고 fake에서도 `account_provider_dispatch`를 호출했다.
실제 9B repair/fallback 안정성을 검증한 것은 아니다.

- fresh Work 포함 6 semantic invoke의 6/12/18 dispatch를 정확히 기록.
- target confirmation에서 기존 Work/Source 보존 시 0, Source가 없어서
  Source owner만 호출하면 2 dispatch. Goal/Work 재생성 없음.
- temporal/ambiguity 한 invoke의 1/2/3 dispatch, temporal 0-call 유지.
- 같은 capability의 Route 2개는 infer 1회, 독립 Route/Work binding 유지.
  서로 다른 capability는 각각 선택, Tool 후보 하나는 0-call 유지.
- determine의 deterministic 0-call과 inference 1회, bounded semantic
  revision 후 confirmation으로 끝나도 실제 dispatch 전체를 기록.
- cap 직전 repair의 두 번째 dispatch는 기존 예산 경계에서 차단되고
  첫 번째 소비량은 남는다.
- 기존 compiled Tool component의 `trace==1` assertion은 유지했다.
  그 fake에만 dispatch accounting을 opt-in했다. 다른 owner의 비계측
  fake를 일괄 변경하거나 assertion을 완화하지 않았다.

초기 직접 검사에서 발견한 confirmation fixture 필드 누락과 이미
deterministic하게 처리되는 route fixture는 테스트 입력만 정정했다.
공통 fake 전체에 accounting을 켰을 때 무관한 Retrieval fake/durable
계측 방식이 충돌해, 이번 검사 대상 Tool component에만 적용했다.
이 테스트 준비 오류를 Product 회귀나 모델 실패로 세지 않는다.

변경 Python Ruff, Product graph 두 파일 scoped mypy, `git diff --check` PASS.
상위 인접·안전 회귀 **2,197 passed / 11.86초**: RU/Tool/Retrieval/Planning/Review,
LangGraph·Prompt architecture, budget/Approval/Claim/ExecutionAttempt/Verification/Recovery,
dispatch checkpoint/Approval durability와 compiled production-agent component를
단일 프로세스로 실행했다. 직접101과 중복되므로 합산하지 않는다.
전체 pytest/새 모델 실행은 하지 않았다. 최종 commit/push는 상위 작업에서 기록한다.
