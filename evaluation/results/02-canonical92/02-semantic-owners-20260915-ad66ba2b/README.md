# CORE-009 / CORE-012 / CORE-013 의미 경계 개선 결과

평가 SHA: `ad66ba2b57f00ac64239cf1b2862815f8e7cf39e`

## 결과 요약

| Case | Product 경계 결과 | 자동 판정 | 최초 분기 / 비고 |
|---|---|---|---|
| CORE-009 | BLOCKED | PRODUCT_FAIL | Request Understanding가 명시된 Task source를 누락하고 Gmail SEND를 발명한 뒤 Retrieval의 `QUERY_USER_CONSTRAINT_MISSING`에서 차단 |
| CORE-012 | WAITING_APPROVAL | PRODUCT_FAIL | generic confirmation 제거 성공. Task/Calendar READ와 Gmail Draft CREATE Preview 정상. 기존 semantic judge가 Draft를 SEND로 오판 |
| CORE-013 | BLOCKED | PRODUCT_FAIL | 이번 1회는 Request Understanding source-dependency 중복으로 `OUTPUT_SCHEMA_INVALID`; schema repair도 중복 반복 |
| CORE-001 | COMPLETED | PASS | 회귀 PASS |
| CORE-002 | COMPLETED | PASS | 회귀 PASS |

| Case | LLM | Connector READ | Connector WRITE | LangSmith Trace |
|---|---:|---:|---:|---|
| CORE-009 | 8 | 4 | 0 | `01a0a29e-654b-7cf0-a512-388c52f8fec0` |
| CORE-012 | 14 | 6 | 0 | `01a0a29f-143a-77e1-b440-b7bd72920aa1` |
| CORE-013 | 4 | 4 | 0 | `01a0a2a0-ca62-7291-ae90-bfea85662a1d` |
| CORE-001 | 8 | 4 | 0 | `01a0a2a1-66f3-7431-8784-85d6e99c2cd3` |
| CORE-002 | 8 | 8 | 0 | `01a0a2a2-4944-7713-b96e-d2e18dd5c268` |

CORE-012의 deterministic checkpoint, 승인 전 WRITE 금지, 중복 effect 검사는 모두 PASS다.
실제 action은 `gmail_create_draft / CREATE`이고 Connector WRITE는 0이다. 자동 판정은
Judge/Grader를 수정하지 않는 이번 범위에서 원시 결과로 그대로 보존한다.

## 수정 전 최초 의미 분기

| Case | Last correct boundary | First divergence | Owner | Reason code | Root cause |
|---|---|---|---|---|---|
| CORE-009 | base goal | Task source 누락 | Request Understanding / source dependency | 최초 미검출 | qwen 의미 오판; 후속 Recovery는 실제 obligation 없이 과대 분류됐음 |
| CORE-012 | source/output/recipient/period | Connector 조회 대상을 USER missing으로 판정 | Request Understanding / ambiguity | `REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION` | `business_concepts`를 searchable anchor로 보지 않고 USER 판정을 그대로 확정 |
| CORE-013 | Request Understanding / Tool Route | Calendar query가 `인쇄소 슬롯` 대신 `Atlas QR` 사용 | Retrieval / Query Planner | 최초 미검출 | 후속 빈 CHANGED delta는 validator가 정당하게 `OUTPUT_SCHEMA_INVALID` 처리 |

Production 수정은 CORE-012 owner에만 적용했다. CORE-009의 qwen 의미 오판과 CORE-013의
제외 범위 Query Planner 품질은 수정하지 않았다.

## 직접 영향 검증

| 검증 | 결과 |
|---|---:|
| Request Understanding unit/component | 235 PASS |
| 추가 ambiguity 경계 | 36 PASS |
| Ruff / mypy | PASS |
| Architecture | 370 PASS / 1 FAIL |

Architecture 실패는 시작 HEAD부터 존재한 평가 harness/API 테스트 함수명 4건이며 이번 변경의
새 위반은 0이다. 전체 component 묶음의 기존 Retrieval Query Planner 실패 2건은 명시된
제외 범위로 수정하지 않았다.

## 실행 집계

| 항목 | 결과 |
|---|---:|
| 전체 Case | 5 |
| Product 분모 | 5 |
| PASS | 2 |
| Product LLM 호출 | 42 |
| Semantic Judge 호출 | 5 |
| Connector READ | 26 |
| Connector WRITE | 0 |
| Simulated Provider effect | 0 |
| rerun-to-pass | 0 |

## 판정

| Verdict | Count |
|---|---:|
| PASS | 2 |
| PRODUCT_FAIL | 3 |

## 최초 실패 Owner

| Owner | Count |
|---|---:|
| PRODUCT | 3 |

세부 원시 결과는 로컬의 `cases/CASE-*.json`, `experiment_manifest.json`, `summary.json`에
보존했다. Provider Resource 식별자가 포함될 수 있는 원시 파일은 gitignored 상태를 유지하고,
비식별 요약인 이 README만 원격에 커밋한다.

공식 Case Run은 각 1회이며 `rerun-to-pass = 0`, Provider WRITE/SEND = 0이다.
