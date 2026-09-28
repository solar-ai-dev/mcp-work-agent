# 064 — 실제 Production Graph의 로컬 snapshot 연결

## 실행 전 경계

- 목적: RU/Tool Route의 부분 통과와 Retrieval/Planning/최종 답변까지 연결된 성공을 구분한다.
- 현재 제품 Graph/composition/SQLite/서명 selection handle/durable handoff를 사용한다. HTTP 세션, API 서버, UI는 사용하지 않는다.
- 기존 Canonical 실행기의 fault 없는 Case는 Live Provider 경로여서 이번 오프라인 실험에 사용하지 않는다.
- `production_snapshot_runtime.py`는 connector startup **이전**에 외부 port를 snapshot으로 교체한다. Product source는 변경하지 않는다.
- Google/GitHub MCP 시작, OAuth/OS Keyring, WRITE dispatch, 외부 socket/자식 process는 차단한다. 모델 실행을 명시적으로 켠 경우에만 loopback Ollama 11434 및 기존 Product의 읽기 전용 GPU probe 두 명령을 허용한다.
- 실제 snapshot의 selected resource ID/parent/payload를 검증한다. Gold는 모델 입력에 전달하지 않는다. 연결됨 상태는 로컬 fixture metadata이며 실제 계정 인증 증명이 아니다.
- 각 시험은 비어 있는 별도 `evaluation/results/` runtime을 사용한다. 기존 DB/settings, 실행 중 서버는 변경하지 않는다.
- seed는 composition 인자로 결속하며 런타임 생성 후 policy를 바꾸지 않는다. READ 입력/결과는 별도 복사해 관측한다.

## 직접 검증

- 9 unit/component 검사 PASS, scoped Ruff/mypy PASS.
- 실제 StartRun → durable handoff → compiled MainGraph → 첫 RU inference 도달을 sentinel로 확인했다. 이 검사는 모델 호출 0, Provider 호출 0이다.
- 이는 실제 모델의 업무 성공 판정이 아니다. 실제 모델 trial의 사전 등록과 결과는 별도 기록한다.

## 첫 실제 모델 Trial의 사전 범위

- CORE-005 한 Case, 한 Trial. Product budget/temperature/Prompt는 변경하지 않는다. seed20260923, qwen3.5:9b의 실제 digest, 실행 HEAD/코드/Prompt/Registry/Dataset/snapshot/Python hash를 실행 직전 plan에 결속한다.
- 사용자 요청: 선택한 Task의 상태와 기한 조회, 새 Task 생성 금지. 선택 ID/parent는 기존 서명 selection handle을 통해 결속한다.
- Gold는 요청한 미완료 상태와 date-only 예정일을 답하는지 검수하는 데만 사용한다. 모델 입력에는 원문과 실제 선택 Resource만 전달한다.
- CORE-005는 reference time이 필요 없는 과거 상태 조회이며 Canonical의 `reference_time=null`을 유지한다. 현재 시각에 맞추려고 Fixture 날짜를 바꾸지 않는다.
- 외부 supervisor의 600초 및 최대 20 모델 dispatch 시도 상한을 적용한다. dispatch 시도/실제 wire 호출/Product budget 계수는 구분한다. 상한 도달은 `EXPERIMENT_BOUND_REACHED`, 업무 의미 판정은 별도다.
- 확인/승인/재인증/복구 대기 시 자동 응답이나 resume를 하지 않는다. 실제 WRITE는 허용하지 않는다.
- Context의 외부 연결 차단은 worker drain까지 유지하고, wall timeout이면 격리 child 전체를 종료한다.
- 원 LLM 응답, repair, owner 입력/실효 sampler, snapshot READ 결과, 영속 Evidence와 최종 답변을 로컬에 보존한다. 실패 Trial을 덮어쓰거나 성공할 때까지 반복하지 않는다.
- 실행 전 현재 Product 관련 unit/component 회귀 1,583건 PASS(9.32초). 기존 1,583건을 같은 묶음으로 재확인한 수치이며 누적 합산하지 않는다. 업무 성공률/92 평가 점수가 아니다.
