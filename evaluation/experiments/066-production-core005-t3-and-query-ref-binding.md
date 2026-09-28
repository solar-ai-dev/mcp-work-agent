# 066 — 현재 MainGraph T3 실패 보존 / Query exact-ref Schema 정합화

## 실제 연결 결과

사전 기준 `066-production-core005-t3-criteria.md`대로 CORE005를 1회 실행했다.
HEAD `977e55d4f7c124fb5546332dd1a5003a8e4a2d5a`, trial
`f91b1eb7-c602-464a-b60f-d6a7ba3f3753`, Run
`aac59d4e-2167-4d94-8998-91a5a90c905f`다. 비활성 v4/v45 후보는 적용하지 않았다.
과거 T1/T2를 덮어쓰지 않고 actual Product MainGraph/StartRun/SQLite/runtime과 로컬
snapshot READ 경계를 사용했다. 현재 Product 입력만의 연결 검증이지 Live Provider E2E가 아니다.

**업무 결과 FAIL / Product BLOCKED.** 조회 요청에 미요청 UPDATE/SEND가 생성됐으며,
Query 첫 출력과 기존 1회 semantic revision 모두 invalid exact ref로 거절됐다.
외부 cap/timeout/환경 오류가 아니라 Product validator stop이다. 실제 snapshot READ0,
외부 Provider READ/WRITE0, 승인0, rerun-to-pass0. Query 수정 뒤 이 Trial을 재실행하지 않는다.

| 경계 | 실제 관측 | 판정 |
| --- | --- | --- |
| Work | 단일 Work, 조회 문장의 exact provenance. 생성 금지는 span 밖이나 각 owner의 원문에 그대로 존재 | 한 Work 자체는 타당. 금지를 원문에서 버린 것으로 단정하지 않음 |
| Goal FIRST | goal/완료조건은 상태·기한 READ와 새 Task 생성 금지를 보존. 그러나 additional constraints의 due에 조회 지시, description에 내부 필드명 조각도 생성 | Goal 문자열이 WRITE를 요구한 것은 아님. 실행값 슬롯 오염은 별도 잔여 실패로 관측하며 Output 오판의 인과 원인으로 확정하지 않음 |
| prohibition / Source | CREATE FORBIDDEN, 필요한 Task 상태·기한/선택 identity 보존 | v4 과거 금지 누락과 섞지 않음 |
| Output FIRST | 원문과 READ Goal을 보고도 TASK/UPDATE와 GMAIL_MESSAGE/SEND를 생성 | 미요청 외부 변경 의미가 처음 생성되는 owner. 후속 조립이 발명한 결과 아님 |
| Tool Route | Task READ와 TaskList discovery, 두 WRITE Output을 유지 | 잘못된 RU 의미가 실제 frozen Route에 전해짐 |
| Query FIRST / revision | 입력에는 typed `task:<id>`가 있지만 schema는 임의 non-empty string. 두 출력 모두 prefix 없는 native ID | 기존 validator가 `RETRIEVAL_ROUTE_SCOPE_VIOLATION`, `$.route_queries[].detail_candidate_ref`로 올바르게 차단 |

Output Prompt는 현재1.1.1이다. 과거 T2의1.1.0과 동일 SHA/Prompt라고 부르지 않는다.
최신 Goal/Output 통합 후보의 과거 연결 개선도 이번 Production 결과로 승계하지 않는다.
Query 결함을 고쳐도 앞선 Output/Goal 의미 실패가 해결됐다는 뜻이 아니다.

## 코드로 확정한 별도 계약 결함과 수정

`plan_query._route_operations`는 current-Run selected/exact ref가 있으면 DETAIL_FETCH를
허용한다. 기존 `validate_retrieval_query_plan_v2`도 같은 Route의 exact refs와 해당
Resource fetched refs의 합집합을 허용한다. 하지만
`query_plan_schema._bind_route_operation`은 전달받은 `allowed_resource_refs`를 쓰지 않고
fetched candidates만 enum에 넣었다. 첫 READ 전 candidates가 비면 free string이 됐다.

가장 작은 수정은 이 generation Schema의 enum을 이미 전달된 두 집합의 합집합으로
맞추는 것이다. 첫 호출과 semantic revision은 동일 bounded Schema를 재사용한다.
Canonical05에도 기존 identity authority와 생성 Schema의 정합성을 명시한다.

- native ID prefix 추정/문자열 보정/validator 완화0.
- exact refs는 기존 connector+Resource+Route binding에서 온다. 다른 Route의 selected ID를 합치지 않는다.
- fetched refs는 기존 Resource-prefix 필터와 validator 범위를 그대로 따른다. 개별 query-origin 격리를 새로 보장한다고 주장하지 않는다.
- 참조가 전혀 없을 때 actual caller는 DETAIL_FETCH를 기존대로 제외한다. low-level helper의 미사용 일반형까지 변경하지 않는다.
- Prompt/State/Node/Graph/Schema version/예산/실행권한 변경0. persisted candidate 의미와 resume 계약 불변.

## 검증

새 직접 Schema/validator 반례 12개: 수정 전 **6 FAIL / 6 PASS**, 수정 후 **12 PASS**.
선택 참조-only, 조회 후보-only, 두 authority 합집합, 같은 Resource의 다른 Route 참조,
다른 Resource 참조, prefix 없는 ID/임의 ID 거절을 확인했다. 기존 plan_query 포함75 PASS.
Agent/compiled graph/workflow/Approval/Execution/Verification/Recovery 관련
**1,698 PASS / 7.06s**, scoped Ruff/mypy PASS. 이는 fake/직접 계약 회귀 검사이며
실제 모델의 다음 응답이나 전체 업무 성공률을 보증하지 않는다.

추가 실제 `initial_retrieval_planner_input → plan_query → build_query` 연결 검사2 PASS:
두 frozen Route를 사용해 single-selected shortcut을 피했고, bare ID 첫 출력은 보존한 채
기존 semantic revision1회로 넘어간다. 첫/revision의 실제 Schema는 동일하게 typed exact
ref만 허용하며 materialized ref도 그대로다. no-ref 반례는 actual planner가 DETAIL_FETCH를
제외하고 SEARCH만 허용함을 확인했다. 새 직접14개 전체 PASS, 추가 모델/Provider0.

## 실행 비용·결속

- 실제 wire/dispatch9, 입력30,204/출력977 tokens, 보고 LLM 합58,619ms, wall61,421ms,
  usage 누락0. 이 dispatch는 LLM 요청이며 Connector 호출 수가 아니다.
- qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  Ollama0.34.0, seed20260923/ctx16384/think=false. Goal0.1/Source0.05/Output·ambiguity0,
  나머지 temperature 미전송은 모델기본값1이며 0으로 표기하지 않는다.
- Dataset `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`,
  fixture `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
  Case reference_time=null; Run UUID/실제시각과 역사적 실행 차이는 plan/raw에 보존했다.
- Product tree `e0d6f6491b0a0009066ad913b6cca20c86cf7a2afccd854975c95f60cea33f6f`,
  end binding 불변 확인. generation 동시1, generation 중 코드편집/pytest0.
- raw `evaluation/results/066-core005-main-graph-t3/raw.json`, SHA256
  `da254aefc83db3f29f94c48a45543bc19c14b5f2e5aa78cde6bee04338f45ab5`.
- calls 같은 폴더 `calls.json`, SHA256
  `b86202441c8ebc80a605025bd70d7e09f2eb2bdb83b26098340fec550033497d`.

원 raw는 UNREVIEWED를 유지하며 이 문서가 별도 의미 검수다. 상세 원문/Provider ID는
기존 ignore 결과 경계에만 보존한다. #290 identity schema 정합화는 채택하되 #287의
Source 누락·미요청 WRITE·Goal 실행값 오염은 남아 있다. Source v45는 회귀로 기각했고,
Query 개선을 RU 안정화/Canonical92 통과나 Retrieval 이후 성공으로 합산하지 않는다.
