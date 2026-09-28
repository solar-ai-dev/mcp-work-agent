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
