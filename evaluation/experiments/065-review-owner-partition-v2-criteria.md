# 065 — 한 호출 안에서 Review 관측 대상 분리 v2 (실행 전 고정)

## 새 근거와 가설

v1은 실제 모순을 인식했어도 `ISSUE`로 Plan만 지적했다. 기존 role은 Intent를 기준으로
Plan을 검사하는 반면 suffix는 Intent 자체도 검사하도록 했다. 원문→Intent와 Intent→Plan의
두 비교가 같은 findings 안에서 경쟁하며, Request 관측에도 Action/Route/Evidence/free code
필드가 강제됐다. 이는 관측 가능한 계약 문제이며 모델 내부 실패 원인이 확정된 것은 아니다.

이번 단일 구조 후보는 같은 LLM 호출의 결과를 `request_intent_findings`와
`planning_findings`로 구별한다. 전자는 현재 Work ID·semantic field path·설명만 생성한다.
후자는 기존 Review 형상을 그대로 사용한다. Request 관측의 code/kind는 typed section에서
메타데이터로 투영하며 자유 문자열을 해석해 종류를 바꾸지 않는다. 앞서 만든 current
Intent/Plan·exact provenance receipt를 재사용하고 Source/Output/의미 수정값은 만들지 않는다.

기존 Prompt에 예외 규칙·few-shot을 누적하지 않고 두 관측 대상의 책임을 설명하는 역할로
교체한다. 원문·선택·명시적 정정·미승인 WRITE 금지·기존 target 근거 책임은 유지한다.
Node/LLM 호출 추가0, Product runtime/Prompt/Schema/Graph 변경0. 평가용 형상만 달라진다.

## 입력·예산·비교

v1의 동일4입력(Core005 frozen 실제 Review1 + 독립 합성3)을 바꾸지 않는다. 사용자 요청·
Case/Fixture/Gold 변경0. 동일 actual9B digest/Ollama/seed/options, temperature 미전송 유지.
baseline4 FIRST는 v1의 원 raw에서 current Product wire 일치 검증 후 재사용한다.
실패 v1 후보4 FIRST도 기존 원기록과 보고서에 남긴다. 새 후보 FIRST는 입력당1회 **총4회**,
repair/retry0, generation concurrency1, timeout180초. 실패를 대체하지 않는다.

이전 raw hash: `22b7fbcb1257f3aede60f2f82d6c561e4c3d80c1e5fdc5fdc764ebab9ae113af`.
현재 Product wire·모델·Dataset·fixture가 달라지면 호출 전에 준비 오류로 중단한다. 실행 직전
HEAD/source/Prompt/schema/wire/hash를 sealed plan에 저장하고 실행 후 원 raw와 분리해 검수한다.
모델 중 테스트/수정 병행0, Provider/Graph/승인 실행0. 자원은 기존 RAM/GPU 한 모델만 사용한다.

## 고정 판정

- Core005: 원문↔Intent의 Output 책임 모순을 Request 관측으로 선택했는가. 설명만 맞고
  Plan/Route에 돌리면 owner 전달 FAIL(모순 인식 PARTIAL은 별도 기록).
- 정상 CREATE: 추가 결함/불필요 RU 재판정0.
- Plan 제목 오류: Plan 관측으로 ISSUE, 정상 Intent 재해석0.
- selected UPDATE/현재 target 근거 없음: 근거 누락을 인식하되 ID 재질문이나 Intent 오류로
  바꾸지 않음. 전체 snapshot/생략된 모든 BEFORE를 강제하지 않음.
- 구조, 의미, 실제 revision/Graph 연결을 구분. closed refs는 양쪽 동일 추가 진단이고
Product shape와 분리. 새 version의 Product shape INVALID는 예상 비활성 계약 차이지
  모델 오류로 세지 않음.

실행 전 직접33 PASS/5.24초, Ruff PASS. 준비 단계에서 기존 v1 baseline4개가 현재 Product
wire와 같음을 검증했고 새 호출 목록은 후보4개뿐이다. v1의 실패를 대체하지 않는다.
같은 시점 Product의 Work revision 재사용 수정은 별도 `ff0591f5`이며 Review payload 변경0이다.

한 번의 성공은 안정성 증명이 아니다. 새 Request 관측이 나와도 기존 Main Supervisor는
소비하지 않으므로 아직 복구 성공/Production 채택으로 부르지 않는다. 좋아지면 먼저 typed
handoff·dependent invalidation 경계를 확대하고, 악화되면 최초 owner/field/provenance 실패를
보존해 같은 Prompt 지시를 재추가하지 않는다. 전체92 평가는 유력한 연결 후보 전까지0.
