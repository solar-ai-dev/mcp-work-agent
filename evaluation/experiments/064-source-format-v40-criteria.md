# 064 v40 — Source FIRST format-only 진단 사전 기준

## 원인 가설과 범위

Output owner의 format 실험을 Source의 개선 근거로 승계하지 않는다. 별도의 Source
FIRST가 capability의 fact inventory 전체를 복사하거나 새로 만들 Draft를 이미 존재하는
Source로 선택하는 현상이 decoding format 제약과 관련 있는지 작게 분리한다.
이 실험은 Source owner 진단이며 RU 전체·Tool Route·업무 성공 평가나 Product 채택이 아니다.

입력은 `064-work-span-codec-v35-connected-t1`의 기존 FIRST 세 개로 고정한다.

| Case | 원 arm | 보존할 요청 의미와 검토 항목 |
| --- | --- | --- |
| CORE-005 | production | 선택 Task의 상태·기한 조회. Task와 selected-target/binding을 보존하는지 확인한다. 원 FIRST의 title/notes/identity/list identity 추가는 필요한 사실 범위의 과잉으로 별도 기록하며, 그것만으로 전체 업무 FAIL을 만들지 않는다. |
| CORE-017 | work-span-codec-v35 | 작업 목록과 해당 날짜 Calendar의 Task/Event 근거가 필요하다. TaskList/Calendar 같은 parent 보조 자료는 필수 사실과 구분한다. 작성할 안내 Draft를 기존 Draft 조회 대상으로 잘못 요구했는지 별도 확인한다. |
| CORE-049 | work-span-codec-v35 | 명시된 메일·Task·Calendar 근거를 보존한다. Thread/Message의 합리적인 대안 및 함께 사용하는 경로를 허용하며 exact Resource 조합을 업무 Gold로 만들지 않는다. 새 후속 Task/Event/Draft 결과를 기존 Source 조회 대상으로 혼동한 항목은 따로 기록한다. |

Canonical 원문과 `required_semantics`/`forbidden_semantics`가 의미 검수의 근거다.
원 Goal/Work/조건 projection을 정답으로 수정하지 않는다. 추가 Source라는 이유만으로
필수 근거 누락 또는 금지 위반과 같은 실패로 취급하지 않는다. 각 Source는 필요한 자료,
허용되는 선택적 자료, 근거 없는 불필요 자료를 구분하여 사람이 검토한다. 실제 조회/지연/답변
영향은 이 진단에서 측정하지 않으며, WRITE/권한/승인 의미 역시 이 owner의 측정 범위 밖이다.

## 입력·실행 고정

- 기존 constrained Source FIRST 3개를 baseline으로 재사용하고 후보만 각 1회: **신규 3 HTTP 호출**.
- 순서: 005 → 017 → 049. Source FIRST는 prompt ID와 revision `base_projection` 부재로 유일하게 찾는다.
- Source PromptRef/hash, 원문을 포함한 전체 input, body schema, model digest, temperature **0.05**,
  seed **20260923**, num_ctx **16384**, think=false 및 timeout180초를 원 wire와 동일하게 유지한다.
- 실제 Product assembler/transport의 메모리 payload 재구성이 원 wire hash와 같아야 한다.
  candidate는 top-level `format`만 삭제한다. Prompt 재결속·다른 의미 규칙 추가는 허용하지 않는다.
- source plan/raw/call과 row hash, dataset/fixture/Case/reference-time/fault binding,
  실행 HEAD·runner·직접 owner/validator/Prompt 코드 hash를 plan에 결속한다.
- baseline 3회는 `new_call=false` 및 원본 경로/hash/index로 표시한다. usage도 신규 3회와 분리한다.
  baseline의 현재 구조 재검증은 과거에 기록된 검증 결과라고 표시하지 않는다.
- 직렬1, HTTP retry/schema repair/semantic revision/Graph/Provider 호출0. 독립 결과 폴더와
  영구 plan claim을 사용하며 실패 Trial을 덮어쓰거나 성공할 때까지 재실행하지 않는다.

## 판정과 관측

1. 첫 원 응답의 strict JSON → 원 Source schema → 기존 Source exact-set owner validator 결과를 보존한다.
2. 후보 응답 전체가 lowercase `json` 태그의 단일 완결 fence일 때만 wrapper를 제거하고 같은
   schema/owner validator를 적용한다. 앞뒤 설명·여러 fence·부분 JSON·다른 태그는 거절한다.
3. 원 응답과 strict 실패를 덮어쓰지 않는다. codec 이후 구조 결과는 별도 필드로 기록한다.
4. SOURCE_REQUIRED/NOT_REQUIRED, required_information, target_scope, work_unit_ids를 그대로
   기록한다. capability inventory와 선택 필드의 집합 동일성은 관측일 뿐 의미 성공/실패 기준이 아니다.
5. 필수 자료 누락, 선택적 자료 사용, 불필요 자료 추가, 신규 Output을 기존 Source로 혼동한 경우,
   target scope/binding 손실을 각각 검토한다. 모델이 비워 둔 항목에 NOT_REQUIRED를 채우거나
   의미 validator로 Source를 새로 만들지 않는다.

raw 의미 판정은 `UNREVIEWED`다. 내용이 개선돼도 exact-set/schema 실패는 별도로 남긴다.
각 arm calls/input·output tokens/reported·wall latency와 신규 응답 load duration을 기록하며,
이 작은 표본을 성능·반복 안정성 일반화 또는 전체 Production 업무 점수로 합산하지 않는다.

실행 준비 CLI는 기존 단일 runner의 `--owner source`다. 이 문서 작성 단계에서는 모델0,
Provider0이며 Product parser/Prompt/State 변경 및 활성화는 없다.
