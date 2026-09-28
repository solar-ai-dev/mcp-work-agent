# 080 — Source 문구와 실제 조회 대상의 판정 경계 보완

## 목적과 범위

이 문서는 076/079의 CORE-049 부분 Source 평가를 현재 consumer 계약과 다시
대조한 **읽기 전용 감사 addendum**이다. 기존 raw, 사전 기준, 점수, 보고서는
수정하지 않는다. 새 Dataset/Gold 또는 수정 점수표가 아니다.

핵심 구분은 다음과 같다.

- Source owner가 반환한 정보 요구의 의미가 올바른가.
- 그 표현이 실제 Query의 대상·필터를 바꾸었는가.
- Provider 조회와 Evidence 선택이 실제로 필요한 자료를 누락했는가.

076/079는 첫 번째 경계의 부분 Source 실험이다. Query/Provider까지 실행한
결과가 아니므로 뒤의 두 결과를 관측한 것처럼 확장하지 않는다.

## 동일 입력과 달라진 출력

v42의 `schema_constrained` CORE-049 Source 입력, 076 TASK focus 입력,
079 TASK focus 입력에서 다음 여섯 값을 JSON 객체 순서와 무관하게 비교했다.

| 입력 | v42 → 076 | 076 → 079 |
| --- | --- | --- |
| 사용자 원문 | 동일 | 동일 |
| Goal candidate 및 constraints | 동일 | 동일 |
| RequestedWorkDefinition | 동일 | 동일 |
| 선택 Resource refs | 동일 | 동일 |
| 기준시각 | 동일 | 동일 |
| 전체 Source catalog | 동일 | 동일 |

따라서 Goal constraints의 신규 작업 제목·초안 수신자 search terms와 신규
산출물 시각 period는 079가 새로 만든 입력 변화가 아니다. 세 실행이 공유한
upstream 해석이다. 이 입력이 잘못된 Source 표현을 유발했다는 인과관계까지
입증한 것은 아니다. 전체 Source와 focus 실험의 반환 범위·Prompt/Schema 및
076/079의 생성 조건 차이도 유지해서 해석해야 한다.

원문은 기존 Atlas 메일·작업·캘린더를 참고하여 **새 인쇄소 인계 작업**과
점검 일정·안내 초안을 준비하라는 요청이다. 정확한 업무 개수나 한 가지 분해
모양을 요구하지 않는다.

| 관측 | 실제 TASK 첫 출력 | 근거의 범위 |
| --- | --- | --- |
| v42 baseline | `title`, `notes`, `due`, `completion_status` 등 일반 fact 목록 | TASK 필요 여부와 일반 정보 종류를 표현했다. 전체 Source의 다른 문제나 불필요 identity fact까지 해결했다는 뜻은 아니다. |
| 076 | 새 인쇄소 인계 작업의 **현재** 제목·내용·마감일·완료 상태 | 아직 작성할 새 결과를 기존 Source의 현재 사실로 표현한 owner 수준의 명확한 혼동이다. |
| 079 | 기존 인계 작업 제목·마감일, 기존 작업 완료 상태 | 기존 Atlas 작업 전체보다 문구가 과도하게 한정될 위험이 있다. 다만 이것만으로 실제 검색 target이 인계 작업으로 변경됐다고 확정할 수 없다. |

세 출력 모두 TASK `SOURCE_REQUIRED`, `target_scope=CRITERIA`,
`work_unit_ids=[work-1]`를 유지했다. `required_information`의 자연어 표현과
typed target scope를 동일한 계약 필드로 취급하지 않는다.

## 현재 consumer를 통한 정적 추적

아래는 현재 Product 코드의 소비 경로 확인이며, 076/079 결과를 합쳐 새
RequestIntent나 Query를 실행한 기록이 아니다.

| 경계 | 실제 코드와 확인 사실 | 여기서 주장할 수 없는 것 |
| --- | --- | --- |
| Source → RequestIntent | `request_understanding/identify_goal.py:740` 및 `contracts/request_goal_candidate_schema.py:586`은 Source 정보를 Work binding을 유지한 `USER_REQUIREMENT/required_information` constraint로 전달한다. | Source 문자열이 이미 검색 필터로 승인됐다는 주장 |
| RequestIntent → Query input | `retrieval/plan_query.py:1858`의 initial projection은 원문과 전체 RequestIntent를 전달한다. 따라서 Query LLM이 Source 정보를 볼 수 있다. | 이 입력만으로 Query가 반드시 잘못 판단했다는 주장 |
| Query exact anchor | `retrieval/plan_query.py:1277,1365`의 anchor 필드는 search terms·subject·participant 계열이며 `required_information`은 포함하지 않는다. 검증된 refs와 route-local typed constraints가 별도 경계다. | 정보 요구 문자열을 동일 문자열의 title/keyword 필터로 자동 변환한다는 주장 |
| Task SEARCH → Provider | `adapters/langgraph/subgraphs/retrieval/graph.py:358`은 TASK SEARCH에 `CONTAINER_REF`를 허용한다. `projections/execute_read_projection.py:125`는 container와 typed 상태 범위를 실제 인자로 내린다. 제목 Query 인자는 없다. | '기존 인계 작업 제목' 때문에 Provider가 그 제목만 조회했다고 단정하는 것 |
| 획득 자료 → RAG | `retrieval/rag_retrieve_rerank.py:44,77,202`는 `USER_REQUIREMENT` 문자열을 점수용 token으로 소비한다. 문구 차이는 순위에 영향을 줄 가능성이 있다. | 해당 자료 집합에서 실제 순위·top-k 누락이 발생했다는 주장 |
| Evidence / Sufficiency | `retrieval/select_evidence.py:269`와 `assess_sufficiency.py:592`는 전체 RequestIntent를 LLM에 전달한다. 정보 요구의 잘못된 한정이 뒤 판단에 전파될 가능성은 남는다. | 모델의 선택·충분성 판단과 최종 업무 실패를 이미 관측했다는 주장 |

위 Application 상대 경로는 `src/google_work_agent/application/agents/` 기준이다.
Adapter 경로는 `src/google_work_agent/` 기준이다. line은 감사 시점의 탐색 위치다.

## 기존 판정의 해석 보완

- 076의 신규/기존 사실 혼동은 Source owner 첫 출력에 직접 근거한다. 이를
  실제 Provider target 오선택이나 전체 업무 실패와 같은 의미로 쓰지 않는다.
- 079의 기존 FAIL 기록은 보존한다. 다만 근거는 **Source 정보 요구 문구의
  과도한 한정 위험**까지다. typed target 변경 또는 실제 Atlas Task 누락을
  확인한 확정 downstream FAIL로 인용하지 않는다.
- 079를 여기서 자동 PASS/PARTIAL로 재채점하지도 않는다. 올바른 Task 자료가
  읽힐 수 있다는 코드상 가능성과 필요한 Evidence가 실제 소비되었다는 증명은
  다르다. 별도 보완 평가가 있으면 기존 판정과 구분하여 남겨야 한다.
- 079의 다른 항목에서 확인한 strict Schema 위반, 중단 경계, 비용 관측과
  Product 미채택 사실은 이 감사로 바뀌지 않는다.

## 다음 provenance 후보의 동기

현재 Source는 fact 요구를 자유 문자열에 담고 target scope와 Work binding을
별도로 전달한다. 정보 종류를 설명하면서 신규 산출물의 명칭·시각을 기존 Source
주체에 붙이는 문제와, 이후 consumer가 그 문구를 어떻게 쓰는지는 분리해 볼
필요가 있다.

다음 후보를 검토하는 동기는 Source 판단의 **원문상 근거와 주체 관계**를
명시적으로 보존할 수 있는지 확인하는 것이다. 새 표현을 도입했다는 이유만으로
의미 개선이나 실제 조회 성공을 가정하지 않는다. required information 문구를
lexical 규칙으로 고치거나, 새 검색 target/권한을 deterministic하게 발명하거나,
한 가지 WorkUnit 수를 정답으로 강제하는 근거로 이 감사를 사용하지 않는다.

후보 평가는 provenance 구조 보존, Source owner 의미, Query/획득/Evidence의
실제 연결 결과를 각각 구분해야 한다. 모델이 이미 잘못 판단한 값을 참조에
결속했다는 사실만으로 정답으로 인정하지 않는다.

## 재현 근거와 수행량

| 로컬 원본 | bytes SHA-256 |
| --- | --- |
| `evaluation/results/064-source-presence-v42-t1/raw.json` | `f5b40bd0d4e36e0f7d9138d00d9d0bdd45cbebc5cd954a110ced1d3a50c6ee52` |
| `evaluation/results/076-source-focal-t1/raw.json` | `f59b013d514e5fd5ef805a8c5a086341db1442afff5eef1cef05bcc1fb7131d5` |
| `evaluation/results/079-source-focal-reasoning-format-t1/raw.json` | `6dacf447eaf6269c4c0d583b56785f75dfb841b0d45c176976f4835b9ab8dc65` |

원문·Goal·Work 등의 비교는 기존 raw만 읽어 수행했고 원본은 변경하지 않았다.
이 addendum 작성의 신규 모델/Graph/Provider/테스트 실행은 모두 0이다.
제품 코드·Prompt·Dataset·Gold·과거 점수 변경도 0이다. 상세 raw는 기존 로컬
ignore 규약을 유지하며, 이 문서에는 비민감 결론만 남긴다.
