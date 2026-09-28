# 064 — Review → Tool selection 재검토 전달

## 근거와 범위

- 기준 제품: `7f8fb2c5fc5c5f451a1447e4ed8dc6a8fe6357d7`의 CORE-005 Main Graph T2 기록.
- T2의 최초 의미 오류는 조회 요청을 `TASK/UPDATE + GMAIL_MESSAGE/SEND`로 만든 Output owner의 첫 응답이다. Review는 잘못된 WRITE를 발견했지만, 이 문서는 그 의미 판단 오류를 수정했다고 주장하지 않는다.
- 별도 확정 코드 손실: Main이 보존한 `plan_review.route_issues`가 Tool Routing 입력에서 제외되고, signal은 초기 처리에서 제거되어 실제 `select_tool_if_needed` 호출에 진단이 전달되지 않았다. Canonical 06의 재검토 입력 계약과 달랐다.
- 부모 작업의 후보·실제 모델 실행과 분리한 직접 연결 검증이다. 이 작업의 모델 호출·외부 Provider READ/WRITE·승인: 모두 0.

## 최소 변경

| 경계 | 변경 / 유지 |
|---|---|
| Producer | 기존 Review `PlanReviewResultV2`를 그대로 사용한다. finding 문구를 검사해 revision owner를 추론하지 않는다. |
| Main | Planning을 비우기 전에 Review `meta.based_on`에 현재 Planning revision이 포함되는지 확인한다. stale/잘못된 참조는 Recovery로 보낸다. |
| Local State | 기존 Main `plan_review`·`tool_route_plan`을 Tool Routing invocation-local `selection_reconsideration`으로 복사한다. 새로운 Main semantic authority는 없다. |
| Binding / validator | 현재 Intent revision과 이전 Route가 결속되어 있어야 한다. affected ID는 이전 input/output Route의 closed set이다. Output의 old/new 대응은 connector/resource/effect/WorkUnit binding이 유일할 때만 허용한다. 모호한 대응을 추정하지 않는다. |
| Projection | capability별 입력 하나에 현재/이전 Route ID, 이전 Tool, WorkUnit IDs, 해당 Route의 원래 finding을 각각 보존한다. |
| Consumer | 동일 capability의 기존 선택 1회와 Route별 fan-out을 유지한다. 선택된 Registry capability·Output effect·RequestIntent를 재해석하지 않는다. 후보가 하나면 여전히 LLM 0회다. |
| Revision | 기존 bounded semantic repair 입력의 `base_projection`에 같은 재검토 context가 그대로 남는다. retry/예산은 늘리지 않는다. |

Prompt 본문 bytes 및 hash는 변경하지 않았다. 최초 선택의 입력 필드·값도 기존과 동일하다. optional `reconsideration`의 계약을 위해 selection input version만 1→2, manifest prompt version 1.0.3→1.0.4로 정합화했다. activation은 DRAFT 그대로다. Model-facing 규칙·Few-shot 추가는 없다.

기존 persisted Main artifact 형상 및 승인/실행 경계는 변경하지 않았다. 신규 local optional field가 없는 기존 초기·단일 후보 호출도 직접 회귀에 포함한다. 과거 중간 checkpoint에 이미 없던 진단을 소급 복구했다는 주장은 하지 않는다.

## 직접 확인 결과

- 최종 관련 회귀 **266 PASS**: compiled Tool Routing handoff, capability 선택, Main supervisor, Tool Routing/Review operation 및 architecture, Prompt 계약/registry, shared READ → compiled Planning 연결.
- Ruff PASS. 변경 경계와 의존 파일 25개 mypy PASS.
- 부모 검토에서 agents·LangGraph·Prompt·Approval·ExecutionAttempt·Verification·Recovery unit 및 connected/Prompt architecture 회귀 **1,965 PASS**를 재확인했다. 위 266과 중복되므로 합산하지 않는다. 첫 명령의 존재하지 않는 execution 경로는 실행 전 거절됐으며 올바른 execution_attempt 경로로 검증했다.
- 신규 반례/controls: Route별 finding 구분, 같은 capability 2 Route → 선택 1회, shared READ WorkUnit union 유지, 초기 context 미추가, input-only finding 비투영, stale Intent/Review/Route와 모호한 대응 거절, malformed based_on 방어, RU 오류를 임의 재해석하지 않음, single candidate 0회, bounded repair context 보존, Prompt 본문 hash 동일성.
- 최초 직접 실행 169 PASS / 1 FAIL은 기존 supervisor fixture의 `answer-1`과 Review `based_on=plan-1` 불일치였다. 유효 Planning fixture로 맞춘 뒤 assertion을 완화하지 않고 통과했다.
- fake inference가 Registry 후보를 반환하는 직접 검증이다. 실제 모델의 올바른 Tool 재선택률·호출 토큰·지연·업무 성공률은 미측정이다.

## 남은 경계

1. **Input Route-only finding**은 known affected ID로 검증하지만 Output Tool selection에는 전달하지 않는다. Input capability/Resource 재판정은 이번 수정 대상이 아니다.
2. Review 형상은 RU 의미 오류와 실제 Tool capability 오류의 revision owner를 구분하지 않는다. 이번 수정은 잘못된 RequestIntent를 되돌리거나 조용히 변경하지 않는다.
3. eligibility가 하나뿐이면 잘못된 Output도 기존 같은 Tool을 유지한다. context 전달만으로 false-WRITE가 해결됐다는 뜻이 아니다.
4. 같은 capability에 상충하는 Route별 진단은 구분해 입력에 담지만 기존 1회 선택 결과는 공유한다. 그 상황의 의미적 해결은 실제 모델/별도 ownership 검증이 필요하다.
5. 266 PASS는 구조·계약·회귀 확인이지 Canonical 92 점수나 T2의 업무 성공 판정이 아니다.

판단: **확정 handoff 손실의 최소 수정**, upstream Output 의미 오류 및 실제 재선택 품질은 별도 검증 범위. Commit/push는 부모 작업에서 수행한다.
