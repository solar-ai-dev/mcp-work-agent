# 081 — 확정값의 재생성 대신 사실 참조 선택

## 가설와 범위

067 actual Planning FIRST는 `needsAction`을 진행 중으로 과잉해석했다. 068에서는
same-Run/version `incomplete` fact를 실제 입력과 instruction에 넣어도 같았다.
입력에 사실을 다시 반복하거나 상태 규칙을 늘리지 않는다. 기존 compose 한 호출에서
질문에 필요한 Evidence field ref를 고르고, 값은 기존 snapshot resolver/formatter가
렌더하는 output ownership 후보를 비교한다. Product에는 활성화하지 않는다.

자동 요청 유형 분류는 이번 실험에 없다. 고정한 단일 Task 직접 사실 조회 두 입력만
대상이며, 요약·분석·다중 자료·부분 결과의 대체 설계로 일반화하지 않는다.

## 고정 비교

- 실제067 CORE005 상태·기한 input/snapshot, 068 completed 상태·메모 control을 재사용.
  068 raw bytes와 기록된 model/runtime/current Product wire를 다시 검증한다.
  실제 snapshot은 원067 READ/argument/Run/version에서 재구성해 기존 값과 대조한다.
  합성 control은 저장된 input/snapshot을 쓰고 신규 업무 사실을 보강하지 않는다.
- candidate 두 입력 각 FIRST2, 순서 actual1/control1/actual2/control2, **최대4 calls**.
  역사 baseline은 각각1회이며 추가 baseline0. 동일 candidate 2회의 제한된 반복 관측을
  전체 신뢰성으로 확대하지 않는다. 실패도 모두 보존하고 rerun/repair/revision0.
- 9B digest/Ollama/options는 원 compose와 동일. seed20260923/ctx16384/think=false,
  temperature 미전송(모델 기본1), presence 미전송(기본1.5), strict schema format.
  Source080 temperature0.05와 합쳐 하나의 workflow 비용처럼 보고하지 않는다.
- 기존 user_request/intent/outline/Evidence 등 입력은 그대로 유지한다. 응답 계약에
  현재 snapshot에서 사용 가능한 evidence_ref/field pair만 닫는다. snapshot 값은 새
  input으로 공개하지 않는다. 모델은 값/자유문장을 생성하지 않는다.
- []는 draft 없음. unknown/stale/conflicting snapshot은 선택지 없음. validator는
  field 선택의 의미를 고치거나 정답 field 집합을 채우지 않는다.
- actual: 미완료와2026-08-10 date-only를 보존, 착수·진행률/시간/업무완료 발명0.
  control: 완료와 원 notes 모두 전달. 메모를 없애고 상태만 맞히면 PASS가 아니다.
  추가 title 표시는 identity 설명으로 허용하되 무관 field/조건 손실은 별도 표시한다.
- materialized Answer에는 기존 Product validator를 적용. 구조/ref 선택/값 보존/
  의미 충족을 구분. 모델이 일부 필드를 빠뜨린 경우 생성기는 자동 보충하지 않는다.

## 실행·안전

단일 generation, 실행 중 코드편집/pytest0, timeout180초. 기존 sealed plan/exclusive claim/
incremental raw/실제 usage 저장 사용. 환경/transport 오류는 후속 NOT_DISPATCHED로 남긴다.
그 외 구조/의미 실패 때문에 고정4를 줄이지 않는다. hidden reasoning 저장/활용0.

먼저 refs·snapshot version/hash·unknown·notes injection·빈 선택·자유문장 거절을 model-free
검증하고 실행 전 코드·Prompt·fixture·tests hash를 봉인한다. 직접 테스트에서 만들어낸
선택값은 모델 성공이 아니다. 미채택 후보는 그대로 비활성 보존한다.

Production source/Prompt/Node/State/Approval 변경0, 외부 Provider/WRITE0, 전체92/LiveE2E0.
보고는 067/068 원결과→081 결과·각 FIRST·refs/values/omission·calls/tokens/latency와
ADOPT/REJECT/HOLD를 포함한다. Canonical92 점수나 실제 전체 workflow 성공으로 승계하지 않는다.
