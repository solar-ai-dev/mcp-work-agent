# 064 — Goal 검색 슬롯을 Source 외부 의존성으로 취급하는 경계

## 확인 범위

기준 Product `ba7503b3`(v44 결과 기록까지, 제품 코드는 직전과 동일).
실제 `identify_goal_with_budget`와 기존 strict fake structured owner를 연결하고,
caller-local `validate_source_dependency_semantics`만 test-scoped identity 함수로 바꾼
계약 비교다. 파일은 `tests/evaluation/test_source_dependency_guard_authority.py`.
**실제 모델·Graph·Provider 호출0**. Fake가 업무 정답을 대신 생성한 성공률이 아니며,
정해진 typed 입력/출력에 대해 Product consumer가 어떤 결정을 하는지 확인했다.

## 확인된 최초 경계

`identify_source_dependencies.py:314`의 현재 guard는 다음만 본다.

1. Output responsibility 없음
2. 모든 Source가 NOT_REQUIRED
3. Goal의 search_terms 또는 business_concepts 배열이 nonempty

셋이면 `INTENT_SOURCE_DEPENDENCY_CONTRADICTION`으로 bounded Source revision을 요청하고,
같은 결과가 유지되면 거절한다. 원문에 필요한 사실이 제공됐는지, 외부 자료에서만 확인할
수 있는지 검사하지 않는다. **실제 READ를 직접 주입하지는 않는다.**

Canonical06의 Goal/Source 책임 분리, Goal Prompt의 일반 설명/제공자료 경계, Source Prompt의
제공값만으로 가능한 요청을 함께 보면, 검색어·업무 개념의 존재는 외부 자료 필요성의 충분조건이
아니다. Canonical05의 해당 슬롯은 Retrieval에 들어온 의미의 소비 규약이지 외부 의존성의
증명 규약이 아니다. 동일 Work 안의 조회 대상과 신규 결과 조건을 구별하는 typed 역할도 없다.

## 실제 caller component 결과

| 입력·fake owner 결과 | 현 guard | guard 제거 후보 | 판단 |
| --- | --- | --- | --- |
| 메모 본문을 원문에 제공, 그 안의 프로젝트 승인 요청 정리; Source0 | Source 2회 요청 후 거절 | Source 1회 요청, no-READ 허용 | **정상 입력자료 답변의 결정적 false-positive 확인** |
| 내 메일의 승인 요청 조회; Source가 잘못0 | Source 2회 요청 후 거절 | Source 1회 요청, no-READ 허용 | **제거만 하면 실제 근거 누락도 허용하는 위험** |
| 일반 인사말, 검색 의미 없음, Source0 | 정상 | 동일 | 유지 |
| 외부 메일 조회, Thread Source 명시 | 정상 | 동일 | 유지 |
| 독립 Draft CREATE, Source0 | 정상 | 동일 | 유지 |
| 선택 exact Thread identity + Thread READ | identity 보존 | 동일 | 유지 |
| 같은 Run target_resource 확인, prior Source0 | Source0 schema 거절 / 정상 Source 허용 | 동일 | confirmation의 at-least-one 경계는 별개로 유지 |

위의 ‘Source 1/2회’는 fake port에 전달한 **요청 수**이며 실제 모델 호출 수가 아니다.
제공 메모와 외부 메일 두 반례 모두 원문·extractive Goal·Work provenance, 최초 동일 owner
출력 및 실제 revision input을 검사했다. 일반/정상 조회/독립 WRITE control은 caller 최종값과
budget이 같았다. 후보는 scoped monkeypatch이며 Production import/runtime에 남지 않는다.

직접 11개 component와 기존 identify_source_dependencies/identify_goal 회귀를 단일 pytest로
실행해 **138 PASS / 0.59초**, Ruff check/format PASS. 이 수치를 모델 의미 PASS나 실제
업무 완료로 쓰지 않는다. baseline의 실제 잘못된 거절과 후보의 위험한 허용을 모두 통과 조건으로
기록한 경계 테스트다. 현재 보존 모델 raw에서 같은 false-positive가 관측됐다는 증거는 없다.

## 판단

**guard 단순 제거는 REJECT, Production 변경0.** 이것은 안전 권한 경계가 아니라 Goal의
문자열 슬롯으로 Source 의미를 다시 판정하는 경계이지만, 그 검사를 없애기만 하면 기존에
막았던 외부 Source 누락도 함께 허용한다. business_concepts만 빼거나 특정 문구로 제공자료를
감지하는 패치는 하지 않는다. 새 field나 LLM 호출을 즉시 추가해 또 다른 semantic authority를
만들지도 않는다.

이 결과는 다음 구조 검토의 근거다. 검증기가 외부 자료 필요성을 검사하려면 그러한 판단을
소유한 Source owner의 typed 근거가 있어야 하며, Goal 검색 슬롯을 대신 증거로 사용할 수 없다.
하지만 같은 모델이 출력한 추가 boolean 하나는 판단이 참이라는 독립 증명이 아니다. 기존
Source 누락·제공자료 반례·정상 외부조회 모두를 보존하는 계약과 결과가 확인되기 전에는
이 guard를 없애고 안정화됐다고 보고하지 않는다.

v44 실패는 Source FIRST 자체의 메일 누락이며 이 guard를 실행하지 않았다. 두 원인을
섞지 않는다. Approval/Permission/Scope/Identity/Execution/Verification/Recovery 변경0,
실제 Provider WRITE/SEND0, 모델0, 제품 Prompt0. 상세 재현은 추적된 직접 테스트로 가능하다.
