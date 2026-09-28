# 065 — Request-only 의미 검토 v3 (실행 전 고정)

## 새 근거와 변경 경계

v2의 정상 Task CREATE와 Plan 제목 오류 control은 사용자 요청과 RequestIntent가 같다.
Plan만 다른데 후자에서 정상 RequestIntent까지 결함으로 분류했다. 한 호출에서 출력 section만
분리한 방법은 책임 혼합을 막지 못했다. 내부 인과나 반복 빈도까지 증명된 것은 아니다.

이번 평가 후보는 Request 검토의 입력을 `user_request + request_intent`로 제한한다.
원 Intent 안의 Work provenance·selected identity·Constraint/Source/Output은 그대로 전달한다.
Plan/Action/Route/Evidence는 전달하지 않는다. v2의 Request finding 하위 schema를 그대로
재사용하고 기존 Plan finding 결과는 생성하지 않는다. Product role에 규칙이나 사례를 더하지
않고 독립 평가용 role에서 이 책임을 명시한다. 의미를 고치거나 정답을 생성하지 않는다.

현재 고정 입력에는 confirmation/user_action_modifications가 없다. 존재하면 조용히 버리지
않고 실행 준비를 거절한다. 정정이 있는 일반 제품 요청까지 검증됐다고 주장하지 않는다.
Plan ref는 기존 evaluation receipt의 freshness용 local metadata일 뿐 모델 입력이 아니다.
선택 identity가 이미 Intent constraint에 정확히 결속됐다는 전제의 진단이며 원
SelectedResourceRef/계정/parent와의 별도 대조나 잘못된 identity 결속 탐지는 미검증이다.
실제 Product에 추가한다면 기존 Plan Review를 유지하므로 원칙적으로 호출이 **1회 증가**한다.
이번에 Graph/Node를 추가하거나 Request 재판정 경로를 활성화하지 않는다.

## 고정 호출 예산과 재사용

- v1의 baseline4 FIRST는 exact Product wire/model/hash 일치 확인 후 재사용한다.
- v1/v2 실패 원 raw와 판정을 대체하지 않는다.
- v3 고유 입력3개에 FIRST 1회씩, **새 generation 총3회**, concurrency1.
- 정상 CREATE와 Plan 제목 오류는 request-owner wire가 완전히 같아서 한 응답을 alias한다.
  이를 독립 trial2회 또는 성공2개로 세지 않는다. 입력 동일성은 결정적 코드검사로 검증한다.
- seed20260923, temperature 미전송, ctx16384, think=false, timeout180초.
- repair/retry/rerun-to-pass0. 실행 전에 HEAD/source/model/Prompt/schema/wire를 seal한다.
- 모델 중 코드 수정/pytest 병행0. 단일 GPU 모델만 사용하고 RAM/GPU를 점검한다.
- Provider/Graph/승인0. 전체92/Live/제품 업무 성공은 미검증이다.

## 고정 의미 판정

1. Core005: 원문과 현재 Intent의 불필요 Task UPDATE/Gmail SEND 책임을 Request 문제로
   지적하는가. 근거 없는 Goal/완료조건/Source 결함을 추가하면 완전 성공이 아니다.
2. 정상 CREATE(제목 오류 Plan alias 포함): 정상 Intent를 재판정하도록 만들지 않는가.
3. selected UPDATE: Intent에 있는 selected identity를 없다고 하거나 새 ID를 요구하지
   않는가. Target 외부 Evidence 충분성은 이번 입력에 없으므로 **NOT_EVALUATED**다.

구조·의미·실제 Graph handoff 성공을 분리한다. 기존 Product schema INVALID는 비활성
후보 형상 차이로 예상되며 모델 오류로 세지 않는다. closed refs 검증은 의미 판정이 아니다.
Plan 제목 오류/Evidence 누락을 찾지 않았다고 v3의 요청 검토 실패로 세지 않지만,
이를 v1/v2 전체 Review 점수보다 좋아진 것으로 비교하지 않는다. 비교 가능 범위는
Request 모순 식별과 정상 Request 오탐뿐이다.

개선되면 typed handoff와 실제 revision/안전 경계 및 추가 호출 비용을 먼저 확인한다.
악화되면 최초 오류를 보존하고 같은 역할 문구를 더해 재시도하지 않는다.
