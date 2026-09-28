# 065 — Work 정의 변경 후 오래된 조회 재사용 차단

## 최초 손실과 수정

기준 `c07fb203`. Review→Request 재판정 후보의 migration 조사 중 기존 Supervisor의
`_request_input_semantics`가 Source responsibility와 constraints만 비교함을 확인했다.
같은 Work ID가 새로운 원문 span/occurrence/관계에 결속돼도 InputPlanReuse를 발급할 수
있었다. Retrieval의 Work별 Evidence는 ID로 결속되므로 실제 Planning projector가 새 Work
정의와 옛 Evidence를 함께 전달했다. 자연어 이해 문제가 아닌 revision/freshness 코드 결함이다.

수정 owner: `adapters/langgraph/main/supervisor_artifact_revisions.py`.
기존 재사용 비교에 `requested_work` snapshot 한 항목을 추가한다. ID 문자열만 같다는 이유로
업무 의미가 같다고 추정하지 않는다. 새 RequestIntent revision의 Work 정의가 달라졌으면
기존 dependent invalidation으로 Input Route/조회/후속 Artifact를 무효화한다.

Source·constraints·Work가 같고 Output/Goal/완료조건만 바뀐 정상 재사용은 유지한다.
새 semantic field·Node·LLM·counter·버전 migration·Prompt 변경0. 기존 persisted shape를
새 계약으로 변환하지 않는다. Domain 승인·실행 사실을 지우지 않고 기존 Graph reference
invalidation을 그대로 사용한다. Validator가 새 업무 의미를 만들지 않는다.

## 직접 근거와 검증

신규 직접10개: span 변경, 같은 원문 문자열의 다른 occurrence offset, 관계 추가/삭제,
Work 추가/삭제의 거절6; Goal/완료조건/Output-only 수정의 재사용 유지3; historical comparison1.
실제 RequestIntentV3 validator와 Planning `project_route_semantic_inputs`를 사용했다.

historical test는 기존 두 필드 비교만 test scope에서 주입한다. 그 경우 실제 invalidator와
freshness gate가 옛 Retrieval을 허용하고 실제 consumer가 새 Work+옛 Evidence를 조립하는
것을 재현했다. 전체 과거 checkout이나 실제 모델을 실행한 것으로 주장하지 않는다.
현재 비교에서는 해당 Retrieval이 무효화되고 재사용 표식이 남지 않는다.

- 최초 기존 인접28 PASS/0.91초.
- 신규·인접·평가용 구조54 PASS/5.73초(중복 포함; 합산하지 않음).
- application agents / run use-cases / LangGraph adapters 및 Review 후보 직접 테스트
  **2,157 PASS/14.73초**, 단일 pytest 프로세스. 전체 repository pytest는 아님.
- 변경 Product/신규 직접 테스트/후보 실행기4파일 mypy PASS. Ruff import 정렬1건 수정.
- 모델/Provider/승인 호출0. 의미 품질 점수·Canonical92 새 점수0.

해결 범위는 stale Work binding의 재사용 차단이다. upstream Source/Output 의미 오판이나
Review의 잘못된 revision owner 선택을 해결했다고 주장하지 않는다. Review v1은 REJECT로
보존하며 v2의 한-call 관측 대상 분리 후보는 별도 고정 비교 중이다. 실험 성공 여부와 무관하게
이 코드 결함의 직접 반례·정상 재사용 control은 유효하다.
