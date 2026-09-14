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

Dataset Gold와 실행 준비 상태는 별도다. 새 시각을 결정해야 하는 46개 Case는
`PENDING_TEMPORAL_BINDING`이며 임시 날짜를 넣지 않는다. Juniper 검토 Event의
시간 결속, Room Conflict의 Yuna Calendar owner binding, Delta 교체 뒤 휴지통
메시지도 노출하는 현재 Product thread read 제한을 미완료 상태 그대로 manifest에
기록한다. 이 항목을 제외하거나 모델 실패로 바꾸지 않는다.

HOLDOUT 표식은 기존 ID 분류 보존용이며 blind holdout을 뜻하지 않는다. v8은 아직
모델 평가 전이므로 과거 Dataset 점수나 Production Smoke 결과를 승계하지 않는다.

## 평가와 기록 경계

Gold는 제품 Prompt나 Provider 업무 본문에 넣지 않는다. WRITE Case는 Preview와
승인 대기, 승인 후 실제 Effect, 독립 Provider 재조회를 서로 다른 관측 시점으로
평가한다. 평가 결과는 `evaluation/results/<주제>-<YYYYMMDD>/`에 두고, DB·checkpoint·
replay·로그 같은 실행 상태는 runtime 영역에 둔다.

과거 Production Smoke 요약은 [`experiments`](experiments/)에, 누적 실행 이력은
[`실행기록.md`](실행기록.md)에 있다. 이 기록은 v8 평가 결과가 아니다.
