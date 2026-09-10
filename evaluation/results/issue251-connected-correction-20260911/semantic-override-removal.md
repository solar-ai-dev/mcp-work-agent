# 의미 강제 제거 결과

| 항목 | 상태 | 코드 커밋 | 검증 노드·경계 | 결과 |
| --- | --- | --- | --- | --- |
| A. 보호 제약 equality/freeze/synthesis | 이번에 제거함 | `6e3e4ad8051e267b55266356343989a481059759` | `plan_query` → `build_query` → LangGraph projection | 별도 보호 제약 복제·객체 동등성 검사를 제거했다. route 지원 operation/kind, 필수 container/resource, 검증된 participant 승격 검사는 유지했다. |
| B. 업무 개념 exact-substring 및 반복 literal 폐기 | 이번에 제거함 | `6e3e4ad8051e267b55266356343989a481059759` | `preserve_explicit_search_anchors` | 업무 개념을 source-owned literal로 고정하지 않고, 동일 literal이 원문에 반복돼도 실제 원문 anchor를 보존한다. |
| C. term 수·참여자 수 기반 match mode/constraint 강제 | 이번에 제거함 | `6e3e4ad8051e267b55266356343989a481059759` | Gmail planner kind/participant resolver → `plan_query` | deterministic semantic constraint 생성 helper를 제거했다. typed 입력에서 허용 kind와 검증된 identity만 제공하며, KEYWORD/CONCEPT 및 결합 의미는 owning Agent 결과를 사용한다. |
| D. follow-up의 CONCEPT·exact subject·새 synonym 강제 | 이번에 제거함 | `6e3e4ad8051e267b55266356343989a481059759` | `has_retrieval_followup_path` → `plan_query_expansion` | exact subject/CONCEPT 존재 여부로 후속 검색을 차단하지 않는다. 기존 최대 3회, stop reason, no-progress 및 budget 경계는 유지했다. |
| E. unread page의 필수 이슈 강제 | 이번에 제거함 | `6e3e4ad8051e267b55266356343989a481059759` | `assess_sufficiency_node` → `assess_sufficiency` | `has_next_page`만으로 `UNREAD_PAGE_AVAILABLE`을 필수 누락으로 만들던 후처리를 제거했다. 실제 pagination 경로는 그대로 유지했다. |
| F. USER+MISSING의 connector owner 재지정 | 이번에 제거함 | `6e3e4ad8051e267b55266356343989a481059759` | `assess_sufficiency` result validation | 모델의 typed resolution source를 후처리로 덮어쓰던 normalization을 제거했다. 실제 선택과 자료 조회 책임을 같은 값으로 바꾸지 않는다. |
| G. 날짜 regex 기반 Evidence role/선택 override | 이번에 제거함 | `6e3e4ad8051e267b55266356343989a481059759` | `select_evidence` | regex로 Evidence role을 CONTEXT로 바꾸거나 segment/resource를 제외하던 guard를 제거했다. 날짜 projection과 provider timestamp 같은 보조 사실은 유지했다. 전체 직접 의미/연결 215건과 구조·Prompt 40건, Ruff 및 변경 source mypy가 통과했고 삭제 symbol/caller는 0이다. |
| 전체 제품 검증 | 남은 문제 | `6e3e4ad8051e267b55266356343989a481059759` | 전체 Graph·Browser·실제 LLM/Provider | 이번 승인 범위에서 실행하지 않았다. 직접 검증 결과를 전체 업무 품질 또는 Live PASS로 확대하지 않는다. |
