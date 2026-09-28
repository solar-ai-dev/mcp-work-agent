# Review / Planning ANSWER 실제 호출 계측 정합화

## 범위와 기준

- 수정 전 Product 기준: `4242f7d75b450ef80f4ab45f2d784c4335720530`.
  구현 parent HEAD는 `0668ed93eee983ab534fef7bec5fdc6b867464d2`이며,
  그 사이 변경은 evaluation runner/report뿐이다.
- 가설: Review는 semantic owner가 결정적으로 끝나기 전에 LLM 예산을 검사하며,
  Review와 Planning ANSWER의 trace는 실제 dispatch 대신 semantic 결과 수/상수 1을 센다.
- Product Prompt·Schema·State·Node·모델 설정·예산 상한·Review 의미 검사·Approval 변경 없음.
- 실제 모델/Google/GitHub Provider 호출 및 WRITE/SEND: 0. 합성 Port가 실제
  `account_provider_dispatch` 경계만 호출하는 직접 component 검증이다. 업무 성공률 검증이 아니다.

## 수정 전 재현과 변경

| 경계 | 수정 전 실제 메모리 재현 | 변경 |
| --- | --- | --- |
| Review 정확한 결정적 Plan 검사 | 예산 100/100, 필요한 infer 0인데 `ABSOLUTE_LLM_LIMIT_EXHAUSTED` | owner가 invoke할 때만 기존 예산 사전 검사. 결정적 검사는 그대로 실행 |
| Review 비결정적 검사 | infer 1 / 실제 dispatch 2 / budget +2인데 trace +1 | 호출 전 정수 counter capture → actual dispatch ledger 차이로 trace 기록 |
| Planning ANSWER outline/compose | 각각 infer 1 / dispatch 2 / budget +2인데 trace +1 | 두 physical Node도 같은 actual ledger delta 사용 |
| Planning deterministic outline control | 예산 100/100에서도 infer 0 정상 | 기존 동작 유지 |

실제 호출이 필요한 Review/ANSWER는 100/100에서 계속 거절된다. 99/100에서 FIRST
dispatch를 계상한 뒤 두 번째 dispatch가 발생하려 하면 기존 guard가 차단하고 budget 100을
보존한다. 즉 예산 차감 권한은 원래도 실제 dispatch ledger에 있었으며, 이번 수정은 예산
우회나 상한 확대가 아니라 잘못된 사전 차단 및 trace 누락을 고친다. 처리하지 않는 예외의
Node trace 반환을 새로 만들지 않으며, durable dispatch 기록의 기존 계약을 유지한다.

## 리뷰 중 발견한 직접 회귀

`7f187cf2`의 이전 Planning ACTION 계측 수정은 결정적 0-call 경로에서도 항상
`consume_llm_call_budget`을 불렀다. 이때 현 Node가 budget을 bind하지 않았다면 이전
ContextVar의 budget이 현재 State에 합쳐질 수 있었다. 본 변경의 첫 Review diff에도
동일 문제가 있어 commit 전 독립 리뷰로 제거했다.

과거 커밋의 두 Planning 메서드를 `git show`로 읽어 메모리에서 실행했다. checkout이나
파일 교체 없이, current State=100 / 기존 bound budget=1 / exact title 두 Route / infer 0
조건에서 objective와 arguments 모두 사용하지 않은 PromptRef 접근 `KeyError`가 재현됐다.
이는 잘못된 음수 ledger delta를 실제 호출로 취급한 결과이며 과거 수정의 회귀로 기록한다.

최종 구현은 실제 invoke 여부를 **merge 여부에만** 사용한다. invoke가 없으면 기존 State
budget과 trace 0을 보존하고, invoke가 있으면 현재 budget을 bind한 뒤 actual ledger delta를
쓴다. 예상 Route 수나 bool을 호출 수로 쓰지 않는다. `AlreadySatisfied` 반환 경로에도 같은
조건을 적용했다. Review 및 ACTION의 stale bound=1 / State=99·100 반례를 고정했다.

## 직접 확인

- 신규 Review/ANSWER 직접 검사: 14개.
- Planning ACTION stale budget 반례: 4개 추가.
- 기존 인접 검사 포함: **437 PASS**, 단일 pytest process, 3.57초.
- 상위 회귀 gate: **2215 PASS / 12.20초**, 단일 pytest process.
  RU·Tool Route·Retrieval·Planning·Review·LangGraph adapter/architecture,
  budget·Approval·Claim·ExecutionAttempt·Verification·Recovery,
  durable dispatch/Approval persistence 및 production subgraph component를 포함한다.
  437개와 중첩되므로 두 수를 합산하지 않는다. 모델 실행과 동시 실행하지 않았다.
- Ruff 및 Mypy: 변경 Product graph 두 파일과 직접 테스트 두 파일 모두 PASS.
- 직접 검사에서 exact Review 결과/Plan은 변하지 않으며, dimension 통과를 Approval이나
  실제 실행 권한으로 승격하지 않는다. Snapshot Review·기존 Review validator와 실제
  Planning/Review integration 검사를 함께 실행했다.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/adapters/langgraph/test_review_answer_dispatch_budget.py tests/unit/adapters/langgraph/test_task_calendar_snapshot_review.py tests/unit/adapters/langgraph/test_planning_route_call_budget.py tests/unit/adapters/langgraph/test_agent_kernel_budget.py tests/unit/adapters/langgraph/test_planning_review_execution.py tests/unit/application/agents/planning tests/unit/application/agents/review tests/component/langgraph/test_production_agent_subgraphs.py tests/architecture/test_planning_review_owner_local_structure.py tests/architecture/langgraph/subgraphs/planning tests/architecture/langgraph/subgraphs/review
```

## 판단 및 미검증

확정 코드 결함의 owner-local 수정이다. 새 Prompt 실험, 의미 Gold 수정, 모델 성능 결론은 없다.
실제 모델의 repair 발생률·latency·최종 업무 성공률, 전체 Canonical 92 및 전체 pytest는
이 변경의 검증 범위가 아니다. 기존 Schema/State가 동일하므로 checkpoint migration이나
과거 Run budget 재작성은 하지 않는다. 최종 commit/push는 상위 작업에서 수행한다.
