# #251 검색 실행 계약 잔여 3건

측정 제품: `9e2912a9fd300125ff9302c42bebe9332b7a26ce`

| 항목 | 최초 원인 | 수정 내용·커밋 | 검증한 노드/경계 | 결과 |
|---|---|---|---|---|
| RU literal provenance 연결 | 일반 `search_terms`·제목·참여자 literal은 finalizer가 모델 provenance를 제거한 뒤 현재 Run 원문에 다시 결속하지 않았고, 배열 값은 scalar provenance validator까지 도달하지 못했다. | literal 역할의 각 값을 `ConstraintV1` scalar로 정규화하고, 코드가 `USER_REQUEST` 또는 해당 `CONFIRMATION_RESPONSE`의 실제 span을 생성하도록 기존 finalizer owner를 교정했다. `business_concepts` 등 모델 가설은 보호 사실로 승격하지 않았다. `9e2912a9` | 실제 `identify_goal → finalize_intent → RequestIntent.constraints → derive_protected_constraints_by_route → build_query` | **PASS** — 복수 literal 결속, 위조 span 재생성, 확인 응답 출처, 빈 제약 유지, 명시 literal 변경 거절과 별도 `CONCEPT` 가설 변경 허용을 확인했다. |
| `plan_query` 무진전 종료 routing | `_plan_query_node`가 `FINALIZE`를 반환해도 router가 항상 `build_query`로 이동했고 Graph successor에도 `finalize`가 없어 과거 계획을 다시 소비했다. | router가 기존 `FINALIZE` marker를 소비하고 Graph successor에 `finalize`를 등록했다. 새 유효 계획에서는 stale marker를 제거했다. `9e2912a9` | 실제 `_plan_query_node` wrapper·`route_after_plan_query`·compiled Retrieval successor, 통제 LLM/Connector Port | **PASS** — 반복 후보는 `plan_query → finalize`로 종료되어 Builder 및 추가 Connector 호출이 0이었고, stale 종료 표시 뒤 새 계획은 `plan_query → build_query → execute_read`로 진행했다. |
| PHRASE 순서·반복과 identity | 모든 constraint 배열을 정렬해 `KEYWORD+PHRASE.terms`의 실행 순서와 query identity를 함께 바꿨다. | PHRASE terms만 입력 순서와 반복을 보존하고, ANY/ALL 및 CONCEPT 대안은 기존 안정 정규화를 유지했다. 실행 constraint와 identity가 같은 canonicalization을 사용한다. `9e2912a9` | `_canonical_constraints → _normalize_constraints → _query_identity → Gmail connector argument projection` | **PASS** — `납품 → 회신 → 검토 → 회신` 순서·반복이 Gmail query에 유지되고, PHRASE 순서 변경은 다른 identity, ANY/ALL·CONCEPT 순서 변경은 같은 identity임을 확인했다. |
| 직접 검사 | 해당 없음 | 변경 없음 | 직접 unit/component/architecture 93개, 변경 production 4파일 mypy, 변경 11파일 Ruff | **PASS** — pytest `93 passed`; mypy·Ruff 통과. 실제 LLM·Connector·전체 Graph·Browser·전체 suite는 지시대로 미실행했다. |

이번 결과는 순수 통제 검사이므로 새 Run ID나 LangSmith trace를 만들지 않았다.
