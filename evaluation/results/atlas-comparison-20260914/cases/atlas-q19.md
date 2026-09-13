# Atlas q19

## 최초 차이와 비인과 차이 구분

raw `identify_goal`은 성공에서 `scheduled_date/description`, 실패에서 `due/notes`를 냈고, final Gmail message required-information 수도 4에서 3으로 달랐다. 하지만 두 Run 모두 최종 Source `GMAIL_THREAD + GMAIL_MESSAGE`, 동일 frozen Gmail route, 초기 `KEYWORD/ANY` 검색까지 도달했다. 이 raw 차이가 실패를 일으켰다는 근거는 없다.

최초 실패 유발 차이는 조회 결과/continuation 경계다.

- 성공: `gmail_search_threads` 2회, 첫 호출 `has_next_page=true`, 둘째 `false`; 이후 `gmail_get_thread` 12회
- 실패: `gmail_search_threads` 3회 모두 `has_next_page=true`; detail 0회
- 실패 round 0→1에서 선택 집합은 2건 교체되어 새 후보 가치가 있었다.
- 실패 round 1→2에서는 선택 집합 변화가 0이었지만 새 page-state와 20개 후보가 있었으므로 단순 같은-page 반복은 아니다.

성공의 정확 effective query와 Provider snapshot은 safe projection에 없다. 실패 query는 `{"Atlas" "담당자" "최종 기준일"}`이다. 따라서 query 차이와 Provider 데이터 차이를 분리해 확정할 수 없다.

## 실제 실패 입력/출력

round 2의 sufficiency:

```json
{
  "status": "NEEDS_MORE_DATA",
  "issues": [{
    "slot": "gmail_candidate_detail",
    "issue_type": "MISSING",
    "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"]
  }]
}
```

동시에 deterministic follow-up은 `NEXT_PAGE/UNREAD_PAGE_AVAILABLE`이었다. cfcf assessor는 별도로 계산한 detail plan 수를 budget authorization에 전달해 semantic additional-round counter를 쓰지 않았고, actual planner는 NEXT_PAGE를 선택했다. 세 번째 page 이후에도 follow-up이 승인되어 executor가 `advance_current_round_no(current_round_no=2, is_followup=true)`를 호출했고 `RetrievalRoundLimitExceeded`가 발생했다. 네 번째 Provider 호출은 0이다.

## 관련 코드 위치 (`cfcf1faf`)

- `src/google_work_agent/application/agents/retrieval/plan_query.py:415-445`: NEXT_PAGE expansion을 candidate DETAIL_FETCH보다 먼저 선택
- `src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py:1007-1055`: 실제 plan과 별도인 `detail_followup` 수로 follow-up budget 승인
- `src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py:1364-1380`: actual operation으로 round advance
- `src/google_work_agent/application/agents/retrieval/finalize_retrieval.py:425-452`: `MAX_RETRIEVAL_ROUNDS=3` guard

## 권장 최소 수정과 현재 HEAD 차이

한도를 늘리거나 DETAIL_FETCH 우선순위를 새 규칙으로 고정하지 않는다. assessor가 실제 deterministic follow-up을 한 번 계산해 그 operation 집합으로 budget을 승인하고, NEXT_PAGE가 4번째 round를 요구하면 connector 호출 전에 PARTIAL로 종료하는 것이 최소 수정이다.

조사 시점 HEAD `55f85993`에는 아래 취지의 수정이 이미 존재한다. 이번 작업에서는 제품 코드를 수정하거나 이 HEAD의 결과를 cfcf 결과와 섞지 않았다.

```diff
diff --git a/src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py b/src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py
@@ def _assess_sufficiency_node(self, state):
-        detail_followup = plan_candidate_detail(...)
+        deterministic_followup = deterministic_query_plan(...)
+        planned_operation_kinds = {
+            query["operation"] for query in deterministic_followup["route_queries"]
+        }
+        planned_detail_fetch_count = (
+            len(deterministic_followup["route_queries"])
+            if planned_operation_kinds <= {"DETAIL_FETCH"}
+            else 0
+        )
         sufficiency_result, retry_budget, should_plan_followup = authorize_retrieval_followup(
-            detail_fetch_count=len(detail_followup["route_queries"]) if detail_followup else 0,
+            detail_fetch_count=planned_detail_fetch_count,
             can_acquire_new_information=(
+                followup_fits_retrieval_round_budget(
+                    current_round_no=current_round_no,
+                    operation_kinds=planned_operation_kinds,
+                )
                 and has_retrieval_followup_path(...)
             ),
         )
diff --git a/src/google_work_agent/application/agents/retrieval/finalize_retrieval.py b/src/google_work_agent/application/agents/retrieval/finalize_retrieval.py
@@
+def followup_fits_retrieval_round_budget(*, current_round_no, operation_kinds):
+    if set(operation_kinds) <= {"DETAIL_FETCH"}:
+        return True
+    return current_round_no + 1 < MAX_RETRIEVAL_ROUNDS
```

이 수정은 예외와 잘못된 accounting을 닫지만, cfcf 실패와 동일한 Provider pagination에서 최종 답변까지 복원한다고 증명하지는 않는다. 성공 query/snapshot이 없으므로 page/detail 우선순위 변경은 별도 통제 Run 전에는 제안하지 않는다.
