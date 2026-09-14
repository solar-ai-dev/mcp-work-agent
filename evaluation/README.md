# Canonical 92 평가 자료

현재 활성 평가 데이터셋과 Gold의 단일 원본은
[`datasets/e2e/canonical_cases_v8.jsonl`](datasets/e2e/canonical_cases_v8.jsonl)이다.
92개 Case ID와 분할은 `CORE 60 / STRESS 20 / HOLDOUT 12`로 고정한다.

## 활성 파일

- [`canonical_cases_v8.jsonl`](datasets/e2e/canonical_cases_v8.jsonl) — 사용자 입력, Provider binding, readiness, 의미 Gold
- [`dataset-manifest-v8.json`](datasets/e2e/dataset-manifest-v8.json) — 버전, hash, 개수, 변경 및 미완료 상태
- [`provider-snapshot-v8.json`](datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json) — 독립 재조회한 Google 자료와 실제 Resource ID

v8은 확정 산정서의 의미 결정을 적용한 버전이다. 가상 주소를 실제 시험 계정에
결속하도록 산정서가 지정한 17개 입력만 함께 변경했고, 그 외 사용자 요청과 Case
identity는 이전 버전에서 유지했다. 이전 Dataset, 별도 Markdown 질문·Gold,
agent/retrieval/micro/Episode 데이터는 활성 평가 기준이 아니며 Git history로만
보존한다.

## 준비 상태

Dataset Gold와 실행 준비 상태는 별도다. 시간 맥락이 필요한 48개 Case는
Provider timestamp를 위조하지 않고 Case별 고정 `run_reference_time`에 결속한다.
실행기는 [`harness/temporal_bindings.py`](harness/temporal_bindings.py)로 이 값을
해석해 해당 시각에서 Run을 시작해야 한다.

STRESS 20개는 [`harness/canonical_v8_fault_profiles.json`](harness/canonical_v8_fault_profiles.json)의
평가 전용 주입 사양을 [`harness/fault_profiles.py`](harness/fault_profiles.py)로
resolve한다. 이 하네스는 제품 코드·Prompt에 fault 의미를 넣지 않는다.

HOLDOUT 표식은 기존 ID 분류 보존용이며 blind holdout을 뜻하지 않는다. v8은 아직
모델 평가 전이므로 과거 Dataset 점수나 Production Smoke 결과를 승계하지 않는다.

## 평가와 기록 경계

Gold는 제품 Prompt나 Provider 업무 본문에 넣지 않는다. WRITE Case는 Preview와
승인 대기, 승인 후 실제 Effect, 독립 Provider 재조회를 서로 다른 관측 시점으로
평가한다. 평가 결과는 `evaluation/results/<주제>-<YYYYMMDD>/`에 두고, DB·checkpoint·
replay·로그 같은 실행 상태는 runtime 영역에 둔다.

과거 Production Smoke 기준점 요약은 [`experiments`](experiments/)에 남긴다.
정리 전 원시 결과와 누적 실행 기록은 Git history에서만 복구할 수 있으며 v8 평가
결과가 아니다.

## v8 공식 실행 경계

- `public_client_v8.py` — loopback HTTP와 공개 Resource selection 계약만 호출한다.
- `public_runner_v8.py` — Case 입력을 Conversation/Run으로 변환하고 공개 관측 상태까지 기다린다.
- `observation_v8.py` — 공개 Run projection과 안전한 Connector/LLM 호출 요약을 정규화한다.
- `grader_v8.py` — 구조적 safety/terminal/effect 판정과 자연어 semantic review를 분리한다.
- `scripts/serve_canonical_v8_product.py` — Case별 새 Product process/checkpoint에 개발 전용 generic DI를 조립한다.
- `scripts/execute_canonical_v8.py` — diagnostic 또는 동결 SHA의 92개 one-shot 평가를 순차 실행한다.

공식 실행은 `public_runner_v8.py → public HTTP API → production LangGraph` 경계이며
Product Handler/Node/private state를 직접 호출하지 않는다. `evaluation_gold`는 실행 입력에서
제거되고 Product 종료 후 grader에서만 사용한다. 결과는 `evaluation/results/**`에만 둔다.
