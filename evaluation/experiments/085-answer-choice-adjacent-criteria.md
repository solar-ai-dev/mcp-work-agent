# 085 — mode-first 답변 표현의 인접 synthetic control

## 가설과 범위

084의 lookup·completed·정리 반례 결과가 유력하지만, Task snapshot에 상태/기한이 없는
메모 요청과 Task fact catalog가 없는 Calendar 요청은 아직 검증하지 않았다. 기존 065의
두 실제 FIRST 입력·snapshot·응답을 그대로 재사용하여 083의 답변 방식 선택과 084의
mode-first 생성 순서가 이 인접 범위를 회귀시키지 않는지만 확인한다.

새 Prompt 규칙·예시·어휘·semantic guard는 추가하지 않는다. 083의 ROLE/PromptRef와
choice schema를 재사용하고 format branch의 properties에서 mode만 앞에 둔다.
한 Task에서 사용 가능한 fact가 있으면 기존 FACT_REFERENCES/PROSE 두 분기를 유지한다.
Calendar처럼 081 catalog가 없으면 기존 계약대로 PROSE만 허용한다. 이 단일 분기의
property 순서만 085 helper에서 처리하며 083/084 원 코드·raw는 수정하지 않는다.

이것은 `SYNTHETIC_PLANNING_FIRST_NOT_GRAPH_OR_CANONICAL92` owner-local 진단이다.
065는 실제 계정·Run의 Provider 조회가 아니라 명시적 synthetic typed fixture의
application outline/compose FIRST였다. snapshot은 원 fixture의 exact Resource/version/hash를
그대로 검증·재사용하며 이를 실제 Provider 또는 새 same-Run 조회 증거로 바꾸지 않는다.

## 사전 고정 입력·의미 기준

| 입력 | 보존할 요청·사실 | 실패/회귀 기준 |
| --- | --- | --- |
| SYNTHETIC_TASK_NOTES | 선택 Task의 메모: 장비 수령 항목을 확인할 것. 원 snapshot에는 title/notes만 있다. | 메모 누락·다른 업무 주장, 없는 status/due 생성. title/status만 답하고 메모를 대체하면 실패. |
| SYNTHETIC_CALENDAR_LOCATION | 선택 Event의 2026-08-18 10:00~11:00 Asia/Seoul, location=한빛회의실. | 장소/시각 누락·변경, Task로 오인, 근거 없는 변경/저장 주장. |

내용을 정확히 전달하면 FACT/PROSE 선택이나 문장 모양 자체를 정답으로 강제하지 않는다.
Task title fact가 선택지에 있는 것은 title 추가를 요구한다는 뜻이 아니다. 구조 통과와
필요 정보 보존을 별도 검수한다. 누락은 누락으로 기록하고 validator가 field를 채우거나
틀린 선택을 PROSE로 자동 변경하지 않는다. Calendar PROSE-only는 불가능한 Task ref를
생성하지 못하게 하는 기존 closed fact 계약이며 의미 정답을 강제하는 새 분류가 아니다.

## 동일성·예산

- 역사 raw: `065-read-answer-handoff-t1/raw.json`, SHA256
  `607b474471238c2fd77e7b30234a7fa3a3d9360925296c40845532ba313caf7a`.
- 역사 plan: 같은 디렉터리 `plan.json`, SHA256
  `00fd6f33489da6d33660e204bfafcabf68c9b88780c09da41b372eb64e614fb4`.
- 현재 Product PromptRegistry/assemble/transport로 원 FIRST를 재구성하여 전체 projection 및
  실제 HTTP serialization bytes가 일치할 때만 역사 baseline을 재사용한다. 달라지면 모델
  실행 전에 중단하고 새 baseline 예산을 다시 정한다. 과거 Product HEAD와 현재 HEAD는
  다를 수 있으나 wire 동일성을 검사하고 각각의 출처를 보존한다.
- 원 user_request/Intent/개요/Evidence와 sampling/options/seed/think를 바꾸지 않는다.
  출력 계약·역할 본문은 기존 083 choice로 교체하고, 그 choice schema의 허용값은
  유지한 채 084와 같은 mode-first 순서만 적용한다. 새 역할 문구는 추가하지 않는다.
  현재 model digest/show/version은 원 065와 동일해야 한다.
- 신규 4 FIRST: Task notes1 → Calendar location1 → Task notes2 → Calendar location2.
  역사 baseline은 각 1회, 총 2개이며 새로운 호출·반복 횟수에 합산하지 않는다.
- repair/retry0, timeout180초, concurrency1. transport 실패·timeout·wrong model·incomplete는
  기존 recorder circuit으로 중단하며 남은 항목은 NOT_DISPATCHED로 남긴다.
- baseline 응답을 Prompt/선택/정답 생성에 넣지 않는다. 비교 기준으로만 별도 보존한다.

## 관측·안전

084의 transport byte hash를 재사용하며 single/union branch의 properties 순서를 함께
봉인한다. unordered dict equality만으로 순서 동일성을 주장하지 않는다. 후보 응답의 실제
key 순서, 선택 mode, 원 FIRST, Product answer validator 결과, tokens/latency/load/wall을
기록한다. hidden thinking 본문은 저장하지 않는다.

실행 전후 HEAD/Product/helper/criteria/model 및 역사 source hash drift를 검사한다.
exclusive claim으로 동일 plan 반복 실행과 기존 raw 덮어쓰기를 금지한다. 구조 오류·필드 누락은
그대로 기록하며 성공 trial로 교체하지 않는다. 자동 semantic grader/모델 judge는 없고
초기 판정은 NOT_REVIEWED다.

Product source/활성 Prompt/Registry/State 변경0, 외부 Provider READ/WRITE/SEND0.
새 upstream RU·Retrieval, compiled Graph, 자동 eligibility, 일반 요약 전체 또는 출시 검증으로
확대 해석하지 않는다. 이 기준 문서는 실행 전에 동결하며 결과를 보고 수정하지 않는다.

```text
python scripts/evaluate_answer_choice_adjacent.py --prepare --result-dir evaluation/results/085-answer-choice-adjacent-plan
python scripts/evaluate_answer_choice_adjacent.py --execute-plan evaluation/results/085-answer-choice-adjacent-plan/preregistered-plan.json --plan-sha256 <등록 hash> --result-dir evaluation/results/085-answer-choice-adjacent-t1
python -m pytest tests/evaluation/test_answer_choice_adjacent.py
```
