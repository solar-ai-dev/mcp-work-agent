# 064 — EVALUATION Work span selector codec

## 가설·범위

기존 Product Work LLM은 업무 경계와 `request_spans`를 생성한다. 현재 `identify_requested_work.py`는 이 문자열이 원문에 정확히 한 번 나타나야만 provenance로 결속한다. 모델이 비공백 문자는 모두 보존하면서 띄어쓰기만 바꾸면, 의미 판단 이후의 문자열 결속에서 중단된다.

이번 비활성 후보는 **LLM 입력·Prompt·Schema·runtime·호출 수·Work 의미 선택은 그대로 두고 candidate→State admission만 확장**한다. 따라서 “validator 변경 없음”이 아니다. 생성된 span은 원문 위치를 선택하는 후보이며, 최종 provenance는 반드시 실제 원문 slice라는 두 단계를 분리한다. Product source·활성 Prompt·persisted Schema는 바꾸지 않는다.

파일은 `scripts/production_work_span_codec_candidate.py`와 `tests/evaluation/test_production_work_span_codec_candidate.py`다. 순수 함수 `materialize_work_spans(value, *, user_request, bindings=None)`를 기존 raw 재검증에서도 사용할 수 있다. 반환값은 기존 `RequestedWorkDefinitionV1`이며, 내부에서 기존 `validate_requested_work_definition`을 통과한다.

## Owner / 계약

| 경계 | Product 현재 계약 | EVALUATION 후보 |
|---|---|---|
| Producer | 기존 Work supporting LLM call이 `schema_version=1`, `work_units[].request_spans[]` 생성 | 동일. PromptRef·Prompt 본문·입출력 Schema·router·sampling 불변 |
| Candidate validator / codec | exact substring가 유일해야 함 | exact 우선. exact 0개에만 공백 비교 view에서 유일한 위치를 결속. exact 복수는 즉시 거절 |
| State | WorkUnit ID와 `USER_REQUEST` provenance | 동일. 원문 offset과 `user_request[start:end]`를 저장. 생성 selector를 source_text라고 기록하지 않음 |
| Projection | 검증된 WorkUnit과 원문을 후속 RU owner에 전달 | 기존 입력 그대로. codec은 Source/Output/Effect/Constraint/Relation을 생성하지 않음 |
| Consumer | Goal/Source/Output/금지 및 후속 Route consumer | 기존 typed State 소비. 승인·권한·Scope·Tool·Planning 의미 불변 |
| Revision | 기존 Product router의 bounded schema repair 및 Work 검증 | 기존 호출/repair 유지. codec이 재추론·추정 매칭·semantic repair를 호출하지 않음 |

Canonical06의 `requested_work = current-request exact provenance`, Work boundary 소유 및 semantic item owner 분리는 유지한다. Canonical15의 EVALUATION 선언 범위에서만 Work **candidate 문자열 admission**을 확장한다. Product 적용으로 승계하지 않으며, 채택 시 이 producer/candidate/final-provenance 구분을 owning 계약과 함께 반영해야 한다. 새 persisted field·State·Node·checkpoint version은 만들지 않았다.

적용 범위는 fresh `request.identify_goal` physical invocation 내부의 supporting Work candidate validator뿐이다. invocation-local ContextVar로 원문·Run을 결속하고 종료/예외 시 해제한다. 기존 Goal/RequestIntent, confirmation, reconsideration 및 pending confirmation은 원래 경로를 사용한다. 기존 GoalOutput evaluation bridge와 함께 실제 compiled RU gate에서 검증했다.

## 결정적인 결속 규칙

1. 공백만 있는 selector는 거절한다.
2. exact 일치 1개면 기존 offset/text를 그대로 사용한다. 공백 제거 시 비슷한 다른 구간이 존재해도 이미 유일한 exact 선택을 변경하지 않는다.
3. exact 복수는 바로 거절한다. 다른 Work가 점유한 위치로 대상을 추정하지 않는다.
4. exact 0개일 때만 양쪽 문자열에서 명시된 Unicode White_Space를 제외한 view를 만든다. 비공백 codepoint는 대소문자·문장부호·조합형 등을 포함해 그대로 비교한다.
5. 첫 위치 다음 **한 codepoint**부터 다시 검색해 겹치는 출현도 확인한다. 출현이 없거나 여러 개면 거절한다.
6. 유일하면 원문의 첫 비공백 offset부터 마지막 비공백 다음 offset까지 최소 연속 구간을 선택한다. 내부 원문 공백/개행을 그대로 보존한다. fallback의 양끝 공백은 위치 추론에 사용하지 않는다.
7. 같은/다른 Work의 원문 구간 겹침은 거절하고, 기존 읽기 순서대로 `work-N`을 부여한다. 최종 typed validator는 여전히 원문 slice의 exact 일치를 검사한다.

공백 집합은 Unicode White_Space의 25 codepoint로 고정했다: U+0009~000D, U+0020, U+0085, U+00A0, U+1680, U+2000~200A, U+2028, U+2029, U+202F, U+205F, U+3000. Python `isspace()`가 추가로 인정하는 U+001C~001F는 포함하지 않는다. U+200B/FEFF 같은 zero-width/BOM도 제거하지 않는다. offset은 기존 Product와 같은 Python 문자열 codepoint 기준이다.

Case별 문구, fuzzy/편집거리, 철자·숫자·대소문자·문장부호 보정, NFC/NFKC, 의미 동의어는 없다. 이 codec을 Constraint value, Provider ID, 사용자 exact edit literal에 적용하지 않는다.

## 검증과 한계

- 신규 직접 테스트 **30 PASS**: exact 우선, 겹치는 복수 출현, Unicode/비공백 변조, 숫자/문장부호/zero-width, 원문 overlap, 순서·Work 수 유지, current-Run 격리, prior/resume 원복 및 실제 compiled Product RU owner 연결.
- 실제 Product compiled gate는 기존 Work/Goal/금지/Source/status **5회 fake-wire 호출**을 유지한다. Work Prompt ID·원문 입력·출력 Schema는 기존 값이며 후속 Source Work binding 및 cached Output handoff가 유지된다. 이것은 모델 의미 품질 PASS가 아니다.
- 처음 pytest 수집에서 테스트 매개변수 `request`가 예약어라 실패했다. 테스트 이름만 `original_text`로 수정한 뒤 위 30개가 통과했다. 후보나 Product 의미 검증 assertion을 완화하지 않았다.
- Ruff PASS. 후보 파일 mypy `--follow-imports=silent` PASS.
- 실제 모델/Provider 실행 **0**, Product source/Prompt 변경 **0**, commit **0**.

codec은 Work 개수·관계를 고치지 않는다. 금지를 별도 Work로 승격한 출력도 문자열 결속이 타당하면 그 두 Work를 그대로 보존한다. 055/v34의 과분해·공통 identity 누락 해결을 주장하지 않는다. exact가 없고 whitespace-equivalent 구간이 반복되면 여전히 결속 실패이며, 이것을 억지로 통과시키지 않는다. 단어 일부 선택도 기존 exact selector와 같은 허용 범위이지 의미 정확성 보장이 아니다.

017/035 등 기존 FIRST raw로 재검수할 수 있지만, 바뀌는 평가는 **Work binding 수용 여부**뿐이다. 원 raw와 과거 Run 결과는 불변으로 남기고 원본 hash·codec version/hash·exact/fallback 모드·결속 결과를 별도 기록한다. 과거에 실행되지 않은 Source/Tool Route/Planning 성공을 추정해 점수를 승계하지 않는다. 실제 후속 연결·반복 의미 안정성과 비용 효과는 아직 모델 미검증이다.

## 기존 raw 재검증 결과

`scripts/regrade_work_span_codec.py`는 현재 Product Work PromptRef·출력 Schema와 일치하고
원문만 입력받은 실제 FIRST만 선택했다. Core8/continuation/v34의 Product Work 기록
21개(서로 다른 요청 9개)를 재사용했으며 새 모델·Provider 호출은 0이다.

- 기존 exact binder: 구조 ACCEPTED 14 / REJECTED 7.
- codec: 구조 ACCEPTED 21 / REJECTED 0.
- 기존 ACCEPTED 14개는 최종 typed Work 정의가 완전히 같으며 회귀 0.
- 총 span23개: exact15, 비공백 문자 동일·유일한 공백 변형8.
- 추가로 통과한 것은 017/035/049의 문자열 결속이며 과거 Run의 결과나 의미 점수는 변경하지 않았다.
- 005의 금지 문장은 선택 span 밖에 남고, 049의 span 사이 쉼표도 덮지 않는다. 이를 코드로
  추가하거나 업무 의미 복구라고 부르지 않는다. 후속 owner가 원문/Work를 소비하는지는 별도 gate다.

재검증 코드의 직접 검사 **15 PASS**, Ruff/mypy PASS. 모델 의미 판정은 모두 UNREVIEWED다.
명시 Unicode White_Space 집합을 사용하는 최종 보고서는
`evaluation/results/064-work-span-codec-v35-replay/report-unicode-whitespace.json`,
SHA256 `82a64a73d73cb1b6a9d96df6eed898efcc32efc1c930f3427960f0ddc697dadb`다.
각 행에 원본 calls hash·call index·Prompt/schema/input/원문 hash·실제 runtime·원문 offset을
결속했고 원본 bytes 변경0을 확인했다. 이 결과만으로 Product 채택·업무 성공을 선언하지 않는다.
