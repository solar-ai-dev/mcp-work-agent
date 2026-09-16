# 022. Review의 현재 요구·제안 관계 투영

기준 SHA `53842ae6`, clean working tree. 목표는 Preview 수정 권위와
Review 재검토의 이전/현재 제안을 구분하는 제품 입력을 찾는 것이다.
LoRA·전역 State 재설계·새 Agent는 제외한다. `AGENTS.md`와
`LangGraph_Goal.md`, 017~021의 기각·잔여 실패를 따른다.

## 0. 021 평가 State 충실도 선확인

021의 Retrieval artifact는 `source_statuses=[]`,
`availability_results=[]`, `missing_information=[]`로 재구성됐다.
원본 023/028 연결 기록은 coverage=SUFFICIENT, missing_information 0,
Calendar/Event/FreeBusy/Gmail/Task source COMPLETE, availability 1개를
보존한다. 그러나 현행 Review 및 Planning ACTION Projection은 이 세
배열을 LLM 입력에 투영하지 않고, `project_current_action_evidence`는
Evidence reference를 사용한다. 원본 Review Route·Policy 입력은 021
정상 사례와 바이트 정규화 hash가 동일하다. Goal 입력의 차이는 이미
채택된 017 Gmail receipt envelope 분리와 Run 기준시각뿐이다.
따라서 빠진 배열은 이번 Review LLM 결과 차이의 원인이 아니며,
근거 없는 재구성·RU/Retrieval 재실행은 하지 않는다. 이 검증은 저장
입력과 코드 경계 대조이며 Provider 조회 성공 자체의 새 증거는 아니다.

## 1. Preview 수정의 현재값 후보 — 실행 전 고정

첫 공통 실패는 `USER_EDIT_023`에서 사용자 수정된 `payload.title`이
Plan과 일치하는데 Review가 원래 제목을 기준으로 허위 ISSUE를 만든
것이다. 현행 입력에는 원래 RequestIntent, Plan,
`user_action_modifications`가 각각 있지만 수정 path/value와 현재
Action/Route의 결속은 LLM이 다시 찾아야 한다.

후보 A는 현행 입력이다. 후보 B는 같은 Prompt source·output schema와
기존 전체 입력을 유지하고, 검증된 Preview modification의 exact
action_id/path/value를 현재 Plan Action/Route/argument 값에 결속한 작은
`current_user_edit_bindings` Projection만 추가한다. 원래 요청과
수정 기록은 보존한다. 일치 여부나 올바른 finding을 모델 입력에
넣지 않으며, unmatched/ambiguous ID/path는 임의 대응시키지 않는다.
이 필드는 개발 bundle의 optional input으로만 비교하고, 제품 채택은
추후 동일 Node·연결 결과에 따른다.

고정 Node 비교는 023의 실제 저장 Preview-title 수정 입력, 028의
검수 가능한 합성 title 수정, 023의 수정값과 Plan title이 불일치하는
반례를 A/B 각각 1회, 정상 023/028을 현행 1회씩 총 최대 8 호출로 한다.
028 수정·023 불일치는 합성 대조이며 실제 업무 성공률이 아니다.
`qwen3.5:9b` 동일 digest, temperature 0/seed 1729, 고정 Evidence,
Prompt source/output schema, 독립 Run budget을 쓴다. 원출력·입력
fingerprint·schema/repair·토큰·지연·실패 전부 ignored result에 남긴다.

채택 후보 조건: 일치하는 두 수정 Plan의 허위 title ISSUE 감소,
불일치 Plan의 실제 title 오류 발견, 정상 Plan 회귀 없음. 1회 개선은
안정성 증명이 아니므로 유력할 때 고정 반복 및 compiled 연결로 확장한다.
결과가 불량하면 필드만 제품에 추가하지 않고 의미 표현/Review 책임을
재검토한다. 실제 Provider READ/WRITE와 전체 92는 이번 비교에서 0.

첫 8호출은 Schema 완료. `USER_EDIT_023`은 A가 허위 ISSUE 3건,
B가 1건이라 완전 해결은 못 했다. 028의 합성 수정은 A가 허위 ISSUE 1,
B가 0이었다. 수정값과 Plan이 어긋난 합성 반례는 A/B 모두 실제 ISSUE를
찾았고, 정상 023/028은 각 0건이었다. B의 남은 023 finding은
RequestIntent에 남은 수정 전 title/description을 현재 요청처럼 해석한다.
단순 정보 추가로 완전 개선되지 않았으므로 B는 제품 미채택이다.

## 2. 수정 전 constraint의 역할 결속 — 두 번째 비교 전 고정

앞선 B 결과에서 새 근거는 수정 path와 동일 이름의 RequestIntent
constraint가 그대로 남아 모델에 상충하는 현재값처럼 보인다는 것이다.
후보 C는 B의 값 결속 안에 **동일 field가 정확히 하나인 경우에만**
그 기존 constraint를 `superseded_request_constraint`로 연결한다.
원래 Intent는 삭제·변경하지 않고, 다른 constraint·completion condition·
권한에는 손대지 않는다. field가 없거나 중복이면 임의 대응하지 않는다.
이는 title 문자열이나 Case ID를 찾는 규칙이 아니라 검증된 사용자
수정 path와 기존 typed constraint의 관계 표시다. 정확한 literal의
provenance가 없는 값을 새 명시 요구로 승격하지 않는다.

고정 대상은 같은 023 실제 Preview 수정, 028 합성 수정, 023 합성
수정 불일치 3개. B/C를 교차 순서 각 1회, 총 **6 신규 호출**한다.
나머지 Prompt source/output schema·모델·Evidence·Run budget은 동일.
두 일치 입력은 허위 finding 0, 불일치는 실제 ISSUE를 유지해야
유력 후보로 본다. 하나라도 실제 오류를 숨기거나 새 과잉 결함을 만들면
제품 채택하지 않는다. 결과가 좋으면 고정 반복과 compiled 연결을
추가로 정하고, 이번 1회 결과로 안정성을 선언하지 않는다.

두 번째 비교 6호출도 Schema 완료. B는 023 허위 ISSUE 1·028 0,
수정 불일치 실제 ISSUE 1이었다. C는 023 허위 ISSUE 3, 028 허위
ISSUE 5로 악화했고, 수정 불일치만 맞혔다. 이전 constraint를 같은
Prompt에 더 붙이는 방법은 **기각**한다. 예컨대 028 C는 실제로
일치하는 설명·시간까지 ISSUE로 만들었다. 추가 정보가 관계 해석을
안정화한다는 가설은 반증됐다.

## 3. 현재 요구 materialization — 세 번째 비교 전 고정

새 방법은 두 권위 값을 계속 병렬 제시하지 않는다. validated Preview
modification이 정확히 하나의 Action/path에 결속되고, 해당 path의
마지막 segment와 같은 field의 RequestIntent constraint가 단 하나이며,
기존 constraint에 별도 검증된 source provenance가 없는 경우에만
Review Prompt용 **현재 요구 Projection**의 그 value를 수정값으로
대체한다. 원래 RequestIntent artifact/meta/원문과 수정 이력은 State에
그대로 둔다. 수정되지 않은 constraint·완료 조건·Route·Policy는
바꾸지 않는다. 중복 field·다중 Action·provenance가 있는 constraint·
비문자 값·없는 Action/path는 임의 대응하지 않고 기존 입력을 유지한다.
이는 Case/문구 규칙이 아니라 현재 Run의 검증된 수정 적용이다.

개발 후보 D는 기존 `request_intent` LLM Projection만 이렇게 바꾸고
기존 Prompt source/output schema를 유지한다. 현재 023·028 일치 수정과
023 수정 불일치에 A(현행)/D 각 1회, 총 **6 신규 호출**, 순서 교차.
정상 023/028과 날짜·금지 위반은 수정값이 없어 입력이 바뀌지 않으므로
이미 저장된 동일 입력 결과를 회귀 기준으로 재사용한다. D가 두 정상
수정에서 허위 finding 0이고 불일치에서는 ISSUE를 유지해야 유력하다.
그 경우 다른 field·복수 Action 반례와 반복 비교 및 compiled 순환을
추가로 계획한다. 결과가 불량하면 materialization 범위/책임을 다시
검토하며 제품에 활성화하지 않는다.

세 번째 A/D 6호출도 Schema 완료. D는 028 합성 수정의 제목 허위
ISSUE를 제거했지만, 023에서는 title 허위 ISSUE 대신 이미 있는
Task·Calendar 근거를 부족하다는 ISSUE/EVIDENCE_GAP 두 건을 만들었다.
023 수정 불일치는 발견했으나 종료시각 일치까지 오류로 지적했다.
**현재 요구 materialization도 제품 미채택**이다. 같은 Preview
표현만 재조정하지 않고 Review의 근거 판단 책임과 upstream의 검증된
availability 전달을 다음 별도 가설로 본다.
