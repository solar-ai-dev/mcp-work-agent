# 067 — Goal 입력 UUID/시각 교차 진단 (후보 채택 실험 아님)

## 새 근거

066 T3와067 실제 MainGraph에서 Work FIRST의 wire/content는 동일하고 Goal 입력은
Run-local selected ref UUID와 reference time 두 값만 다르다. Goal PromptRef/Schema,
실제 model digest/options는 동일하지만 첫 Goal/후속 금지·Output의 의미는 달라졌다.
Query code fix가 원인인 것도, 단순 같은-input variance인 것도 현재 근거로는 아니다.

이번에는 두 입력 요인을 분리한다. alias/Prompt/새 Schema/State/Node를 아직 구현하지 않는다.
Goal 원 결과2개는 재사용하고 교차 입력2개만 신규 생성한다. 새로운 RU 설계를 성급히
채택하기 위한 점수 대신 다음 owner-local 입력 후보의 인과 근거가 있는지 판단한다.

## 비교 셀

| selected resource_ref_id | reference_time | 실행 |
| --- | --- | --- |
| 066 UUID | 066 시각 | 원 FIRST 재사용 |
| 067 UUID | 067 시각 | 원 FIRST 재사용 |
| 066 UUID | 067 시각 | 신규1 FIRST |
| 067 UUID | 066 시각 | 신규1 FIRST |

066 시각은2026-09-29T00:45:06+09:00,067 시각은01:27:17+09:00이다.
Case 자체 reference_time=null인 과거 사실 조회이며 위 값은 실제 당시 Run의 clock이다.
과거 시각의 Provider를 재현했다고 주장하지 않는다. 두 ref는 동일 Provider Task/parent의
서로 다른 과거 Run-local identity다. 이번 조합은 **고립된 LLM 입력 진단**이지 실제 Run의
참조/권한을 바꾸는 조작이 아니다. 검증된 결과로 다른 Run의 ref를 이관하지 않는다.

## 동결/검증

- Canonical CORE005 원문/Gold/Fixture 및 Work 의미 변경0. 고정2교차셀 각1회.
- Product source/Prompt/Schema/State/Graph/사용자 Settings 변경0.
- `identify_goal_output_schema`와 현재 Product assembler/transport로 각 과거 원 wire를
  완전히 재구성한 뒤 hash가 일치해야 실행한다. Schema/Prompt drift면 실행하지 않는다.
- 원 입력의 recursive diff는 지정한 두 leaf뿐이어야 한다. options·model·Schema·Prompt
  차이가 있으면 동일 요인 실험으로 쓰지 않는다.
- qwen3.5:9b 실제digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  Ollama0.34.0, Goal temp0.1/seed20260923/ctx16384/think=false.
  그 밖의 미전송 옵션과 실제 model defaults를 보존한다.
- 최초 wire2회만 허용. repair/retry/fallback/rerun0. HTTP timeout180초/호출,
  동시1, 실행 중 편집·pytest·다른 모델0. 결과 디렉터리/plan claim 재사용 금지.
- Profile/model/context/Prompt/hash를 plan/raw에 결속. Provider·Graph·승인0.

## 의미 검수 (모양/개수를 Gold로 삼지 않음)

- Goal은 선택 Task의 상태·기한을 조회하는 업무여야 한다. 실제 값을 조회 전에 만들거나
  새로운 외부 변경 업무로 바꾸면 실패다.
- 완료조건은 필요한 답변 의미를 보존하되 근거 없는 완료 상태·시각·실행을 요구하지 않는다.
- 명시된 대상/범위를 바꾸지 않는다. 어떤 슬롯/어휘를 택했는지는 단독 정답이 아니다.
- 실행값 슬롯의 조회 지시문/내부 Schema 문자열 등 오염을 원 FIRST에서 따로 기록한다.
  source span에 등장했다는 사실만으로 올바른 실행값이라고 보지 않는다.
- CREATE 금지는 기존 prohibition owner 책임이다. Goal에 문장으로 반복되지 않는 것만으로
  Goal 실패 처리하지 않지만 새 CREATE를 긍정 업무로 추가하는 것은 허용하지 않는다.
- strict Schema/현재 validator/normalized result와 의미 검수를 분리한다.
  normalized 값이 바뀌면 변경 위치를 보존하며 validator가 업무 의미를 대신 만들지 않는다.

한 셀1회로 반복 안정성·통계적 인과를 확정하지 않는다. factor 교차에서 일관된 품질 차이가
없으면 UUID-only alias 후보의 효능 근거로 삼지 않는다. Source/Output을 새로 호출하지
않으므로 그 owner 품질, 전체92, MainGraph/최종 업무 성공 수치는 만들지 않는다.
역사적 two cells와 신규two cells의 시점·cache/load 차이도 한계로 기록한다.
