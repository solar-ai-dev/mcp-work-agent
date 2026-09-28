# 080 — Source 조회 근거의 원문 결속과 전달

## 가설과 이전 실험과의 차이

076은 Resource membership을 개선했지만049에서 기존 Atlas 자료 대신 새 인계 Task의
현재 정보를 요구했다. 077의 Goal constraints 제거는 범위 회귀를 만들었고,079는
최종 응답을 얻었으나 기존 인계 작업으로 문구를 한정하는 위험이 남았다.
이 실패를 Product Query가 이미 잘못 실행됐다는 증거로 확대하지 않는다.

현재 Source는 사실 요구와 SINGULAR/CRITERIA 및 Work binding을 소유하지만, 구체적인
조회 대상의 원문 결속은 별도 표현하지 않는다. 일반 Constraint의 Work binding은 같은
업무 안의 기존 자료와 신규 Output 역할을 구분하지 않는다. Source/Output을 자동 분리할
기존 typed 역할이 있는데 consumer가 버린 것으로 주장하지 않는다.

이번 비활성 후보는 기존 **전체 Source 한 호출**에서 기존 자료 요구의 원문 구간을
함께 선택하고, 그 선택을 파생 문자열로 다시 만들지 않고 Source artifact로 보존한다.
v7의 생성형 target_description은 후속 binding에서 보존되지 않았고, v43은 membership과
details를 두 호출로 분리했다. 이번에는 추가 의미 호출·필요 정보 요약·Resource별 N호출을
만들지 않는다. WorkUnit 수나 하나의 정답 분해를 강제하지 않는다.

원문 일치는 올바른 Source 해석의 증거가 아니다. 새 Output 구간도 원문에 있으면 구조상
결속 가능하며, 그 구간을 조회 근거로 잘못 고른 경우 의미 실패로 남긴다. validator가
단어를 보고 올바른 구간을 선택하거나 잘못된 Source 판단을 교정하지 않는다.

## 고정 입력과 실행

- Core017 →049 →005 →009 →059, 각 FIRST1, **신규 최대5회**. 새 baseline 호출0.
- 기존071 control의 준비 경계를 재사용해 v42의 실제 default Source FIRST5와 현재
  Product Prompt assembly/input/schema/validator/runtime의 재구성을 검증한다.
  원 baseline bytes/plan/row/wire hash와 Case·Dataset·Fixture binding을 보존한다.
- 역사 Source 결과는 재사용 자료이며 새 동시 paired baseline이나 현재 전체 RU 점수가
  아니다. 신규5와 재사용5의 사용량을 분리하고, 시간 차이의 인과를 단정하지 않는다.
- 원문·Goal(기존 constraints 포함)·Work·선택 identity·기준시각·전체 Registry catalog를
  그대로 둔다. 허용된 변화는 비활성 역할의 계약 선언, 결정적 `request_tokens` 입력,
  REQUIRED 항목의 `source_request_ranges` 및 이를 표현하는 응답 Schema/PromptRef다.
  모델이 고른 range는 현재 원문 slice로 결속하며 별도 Source artifact에 보존한다.
- model/digest/Ollama version 및 실제 sampling은 기존 Source와 동일하다:
  qwen3.5:9b, temperature0.05, seed20260923, num_ctx16384, think=false,
  top-level format 유지, presence override없음, stream=false. 077/079 변형을 섞지 않는다.
- 실행 전 HEAD와 Product/helper/runner/test/Canonical/criteria hash, 모든 실제 wire 및
  input/schema hash를 봉인하고 재계산한다. Gold·기대 판정·Case ID는 모델 입력에 넣지 않는다.
- 직렬1, timeout180초, repair/retry/semantic revision0. 기존 exclusive plan claim과
  결과 폴더 덮어쓰기 금지, dispatch 전후 incremental raw 보존을 재사용한다.
- Schema/provenance/의미 실패여도 고정5를 실행한다. transport/model/completion 환경
  실패는 기존 circuit으로 중단하고 나머지를 NOT_DISPATCHED로 보존한다.
  숨겨진 추론 본문은 저장하거나 검수·정답 복원에 사용하지 않는다.

## 사전 의미 기준

| Core | 기존 자료 의미와 확인할 회귀 |
| --- | --- |
|017|현재 Task 목록과 해당 날짜 Calendar 사실을 보존한다. 작성할 새 Draft를 기존 Draft 조회 근거로 오인하지 않는다. Task 목록에 새 날짜·상태 제한을 추가하지 않는다.|
|049|Atlas 메일·작업·Calendar 근거를 보존한다. 새 인계 Task/Event/Draft의 값이나 이름을 이미 존재하는 조회 대상으로 바꾸지 않는다. Task 마감과 Event 시작은 구별한다.|
|005|선택 Task의 상태·기한, 단일 대상과 Work binding을 유지한다. 실제 상태/기한을 발명하지 않는다.|
|009|요청한 메일과 Task의 필수 업무 사실을 보존한다. container 보조 자료 추가만으로 전체 실패로 보지 않되, 필수 item 사실 누락과 구분한다.|
|059|현재 답장 근거가 되는 메일의 내용·참여자 의미를 보존한다. 새 작성 결과를 기존 Draft나 무관한 Resource 조회로 바꾸지 않는다.|

실제 Canonical 원문·required/forbidden semantics를 authority로 사용하고 exact Resource
조합이나 WorkUnit 개수를 새 Gold로 만들지 않는다. 합리적인 Thread/Message 대안을 허용한다.

다음 결과를 따로 기록한다: strict JSON/Schema, closed range/Work 검증, membership,
필수 사실·조회 대상·범위, 원문 결속의 의미, merge/consumer 전달, 불필요 Source, 비용.
구조 통과만으로 의미 성공을 선언하지 않는다. 모델 응답의 누락을 NOT_REQUIRED로 채우거나
잘못된 사실/대상 문자열을 잘라내지 않는다. 원 raw와 materialized 값을 함께 보존한다.

직접 fake/component gate는 선택된 원문과 Work·사실의 불변 전달만 증명한다. 잘못된 새
Output 구간도 exact이면 구조상 허용되는 반례를 포함하며, fake가 정답을 준 결과를 모델의
업무 의미 성공으로 세지 않는다. Query handoff 검증은 별도 관측으로 보고하고 실제 Query
LLM·Provider 조회 성공과 혼동하지 않는다.

## 범위와 판단

Source owner5 결과이며 RU→Tool Route·Retrieval/Planning·전체 업무·Canonical92 평가가
아니다. CREATE no-Source 합성 control, Confirmation/Revision, 반복 안정성과 전체 Source
소비의 Product migration은 이번 모델5회에서 검증하지 않는다.

판정은 원문 의미 보존과 기존 성공 회귀를 함께 보고 ADOPT/REJECT/HOLD로 남긴다.
좋은 range 형식이나 membership 개선만으로 새 표현을 채택하지 않는다. `RECORDED`는
실행 기록 완료일 뿐 구조/의미 PASS가 아니며 raw 의미 표식은 NOT_REVIEWED로 유지한다.

Product source/활성 Prompt/State/Node/예산/Approval/Execution 변경0, Graph0,
Provider READ/WRITE0, Holdout/Stress 튜닝0. 실행 중 편집·pytest·다른 모델 호출0.
