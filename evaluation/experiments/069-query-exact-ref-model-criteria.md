# 069 — 실제 frozen checkpoint에 결속한 Query exact-ref 수정 FIRST 검증

목적은 `b7c449fa`의 확정 Product Schema 수정이 실제 모델→validator→build_query까지
연결되는지 확인하는 것이다. 새 Prompt/Schema/정책 후보를 추가하지 않는다.
067 MainGraph는 Query LLM0이라 이 gate가 미검증으로 남았다.

## 기존 authority와 사전 확인

- 원 기록: `evaluation/results/066-core005-main-graph-t3`의 call8(Query FIRST), Run
  `aac59d4e-2167-4d94-8998-91a5a90c905f`.
- `runtime/data/google_work_agent.db`, context_retriever namespace의 step0,
  checkpoint `1f1bb53a-c418-681e-8000-23616bc4bf86`만 read-only로 읽는다.
- DB SHA256 `e9a90afc248ec626aea853164e0746b845b80b4f418767b2ab39c3481c18fb8d`;
  checkpoint BLOB SHA256 `801bf02c22f3fbf39529309bbfc2ae4adf423ceae293d53c496ed421638a9b25`.
- 실제 ToolRoutePlan hash `cae5e657f77f7278a344fc10b9ed3bbb2bd6145fbc990a7a03295cc24ed6ca27`.
  TASK/TASK_LIST authority는 실제 state에서 읽고 Prompt의 coarse TASK에서 복원하지 않는다.
- current exact-ref/scope/initial planner/policy projection의 전체 input은 원 FIRST와 동일,
  hash `38b954e7e9cc504b54a9150b36f91d7fb7acae0edfee5674f89d56377b8baf4e`.
- PromptRef도 동일. Schema 차이는 DETAIL_FETCH ref의 자유 문자열→검증된 exact selected
  ref enum 한 곳뿐. current schema hash
  `d29ec1fb0845b430b46183fcf2dfcb1ba8b215e82e0715c32d1ed84e7c8798a1`.

## 고정 예산과 성공 범위

신규 FIRST1회만, actual installed9B/Ollama와 원 Query runtime options를 hash로 결속한다.
prepare/execute를 분리하고 source·model·checkpoint·input·Prompt drift면 실행하지 않는다.
180초/호출, concurrency1, repair/retry/fallback0, 실제 Provider READ/WRITE0.
원 checkpoint/Run/budget/settings 변경0. 역사 시각은 원 temporal 해석 입력일 뿐
현재 Provider 데이터의 과거 재현이나 원 Run의 resume가 아니다.

기존 `plan_query`가 원자 추론 port를 호출할 때 원 input과 current bounded schema를 확인한다.
첫 응답·정규화·검증·후속 revision 요청을 그대로 기록하되 두 번째 모델 dispatch는 차단한다.
통과하면 기존 `build_query`로 typed READ plan까지만 만든다. Connector는 호출하지 않는다.

- exact DETAIL_FETCH ref가 첫 출력에서 생성되는가(코드의 native-ID 접두어 보충 금지).
- 현재 validator와 build_query가 수용하는가, 현재 frozen route/identity/scope가 보존되는가.
- 실패면 정확한 최초 reason/field/원 candidate를 기록하고 재실행하지 않는다.
- 원 T3의 잘못된 RU Output·constraints는 수정하지 않는다. Query gate 통과가 그 오류나
  CORE005 business 성공을 해결한 것으로 판정되지 않는다.

결과는 FIRST 구조·consumer 연결·업무 성공을 분리한다. 과거 FIRST/revision 실패 기록은
보존하고 신규 호출·입출력 tokens/latency를 별도로 기록한다. Product 추가 변경0,
release activation0, 전체92/MainGraph/승인 후 Execution/Verification 재평가0이다.
