# 076 — 단일 Resource 판단: membership 개선, 기존/신규 대상 혼동은 남음

**부분 개선 / Production 미반영.** 전체 catalog와 원문은 유지하고 한 호출에서
한 Resource의 필요 여부와 details를 함께 생성했다. 8개 고정 FIRST 모두 strict
VALIDATED이며 원 출력과 owner 검증값이 동일하다. 미시험 Resource는 보충하지 않았다.

| 부분 판단 | 역사 원 Source에서 해당 항목 | 076 | 실제 변화 |
| --- | --- | --- | --- |
| 017 TASK | PASS | PASS | 현재 작업 목록 CRITERIA, 상태·기한 등 보존 |
| 017 GMAIL_DRAFT | FAIL | PASS | 새 초안 작성에 기존 Draft 조회를 요구하던 오류 제거 |
| 049 TASK | PASS | FAIL | 기존 Atlas Task 대신 **새 인쇄소 인계 작업의 현재 제목·내용·마감일·상태**를 조회할 사실로 생성 |
| 049 GMAIL_DRAFT | FAIL | PASS | 불필요한 기존 Draft 조회 제거 |
| 005 TASK | PASS | PASS | 선택 Task 상태·기한과 SINGULAR 보존 |
| 005 GMAIL_DRAFT | PASS | PASS | 무관한 Draft 조회 없음 |
| 합성 Draft UPDATE | PASS | PASS | 현재 body/recipients 조회 필요, 단일 선택 identity 유지 |
| 합성 자료 제공 CREATE | FAIL | PASS | 기존 Draft 조회 요구 제거, Source 불필요 |

Core의 **부분 Resource 판단 4/6 → 5/6 PASS**, 합성 반례 **1/2 → 2/2 PASS**다.
이 분모는 Case 성공 수가 아니다. 원 baseline의 전체 Source PARTIAL과도 다른 범위다.
membership만 보면8/8이 맞지만049 details가 잘못됐으므로8/8 의미 PASS라고 하지 않는다.
메일·Event 등 미시험 Source, 전체 조립·RU/Route/업무 성공은 아직 검증하지 않았다.

049의 값은 validator가 바꾼 것이 아니라 첫 LLM 출력이다. 기존 Goal projection에는
신규 Task 제목·수신자·시각이 search_terms/period로 평탄화돼 있고 Source/Output 역할
구별이 없다. 이 오염의 영향과 원문 자체의 대상 판단 오류는 아직 분리되지 않았다.
이제 membership 정확도가 개선된 조건에서 해당 입력 영향만 작은 대조로 확인한다.
과거003의 flat Source에서 constraints 제거가 실패했던 사실도 함께 보존하고,
이를 전혀 새로운 해법이나 확정 원인으로 포장하지 않는다.

## 조건·비용

실행 SHA `80baba623e79beb13ad2b2b9b688a61a91f75182`.076사전계획8회,각1회,
concurrency1,retry/repair0,시작·종료binding동일. 기존 Product role의 반환대상3문구만
단일 Resource로 정합화했다. 전체 원문/Goal/Work/catalog와sampling은 보존했다.
원Product FIRST와별도evaluation PromptRef/hash/부분Schema를결속했다.

| 범위 | calls | input/output tokens | reported latency |
| --- | ---: | ---: | ---: |
| Core 부분 판단 | 6 | 22,535 / 248 | 30,228ms |
| 합성 반례 | 2 | 6,717 / 74 | 7,082ms |
| 신규 전체 | 8 | 29,252 / 322 | 37,310ms |

wall37,494ms/load6,828ms,usage누락0. 전체 Source를 이 방식으로 판정하면 등록된
Resource 수만큼 호출이 늘 수 있다. 부분출력시간과baseline 전체출력시간을비교해
지연최적화라고하지않는다. qwen3.5:9b/Ollama0.34.0/기존digest/temp0.05/seed20260923/
ctx16384/think=false/presence미전송. 모델동시1,생성중편집/pytest/다른모델0.
시작GPU0MiB43°C,중간6385MiB100%63°C,종료6385MiB0%47°C(snapshot).
직접/recorder76tests PASS,scopedRuff/mypy PASS. 전체pytest미실행.

Product source/활성Prompt/State/Graph0,Provider/Approval/WRITE0,Holdout/Stress튜닝0,
신규92실행0. 기존073 수정은 유지했다. 전체 안정화 완료나 migration 채택이 아니다.

## 원 근거

- plan `evaluation/results/076-source-focal-plan/preregistered-plan.json`, object hash
  `f4b2b21f6ae0b7ab988d5e3ec481af83788d47dbabda579a9a22c12e176b4a5d`.
- raw `evaluation/results/076-source-focal-t1/raw.json`, bytes hash
  `f59b013d514e5fd5ef805a8c5a086341db1442afff5eef1cef05bcc1fb7131d5`.
- source-admission.json의 focus별strict값·비용, plan의originalwire·현재Source재구성,
  v42/v43역사SHA·rawhash·Dataset/Fixture/modelhash로결속. 상세raw는로컬ignore보존.
