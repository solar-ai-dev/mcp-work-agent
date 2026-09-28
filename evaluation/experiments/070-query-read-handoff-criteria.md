# 070 — 069 실제 Query 출력의 deterministic READ handoff component

069 모델 Trial은 종료 상태로 보존한다. 새 모델 호출이나 원 Run resume 없이, 저장된
첫 출력이 Connector READ 인자와 route/Work 귀속으로 정확히 내려가는 인접 경계를 확인한다.
069는 build_query까지만 검증했으므로 이 component 결과를 원 Trial에 소급 합치지 않는다.

## 고정 입력과 경계

- 069 plan SHA256 `020e7509e70e24716de6821bfb5ddbad1f3689647ad60c3cd46d6e33188ec346`,
  raw SHA256 `86335bcc9dac46eb9961dfa5e34e0eb31958ebd40595162a7eee77e22bd52735`.
- 원066 exact checkpoint·selected identity·설정은069의 read-only 검증을 재사용한다.
  현재 Product/Registry/Dataset/fixture와 원 결속이 달라지면 실행하지 않는다.
- 실제 normalize/validator/build_query → selected exact identity → project_connector_call
  → current Registry READ binding → execute_read + SelectedResourceReadPort
  → in-memory cache/acquisition → source-status route/Work projection.
- Connector만 로컬 fixture/synthetic port다. account getter는 명시적인 합성 실행 context이며
  현재 실제 Google 로그인·권한을 확인했다는 의미가 아니다.
- 기존 Product/Prompt/State/Node/예산 정책 수정0. 역사 DB·Run·checkpoint·결과 변경0.
  새 in-memory budget/cache만 사용하고 같은 READ를 WorkUnit별로 복제하지 않는다.

## 관측·반례

정상 path는 snapshot READ1, exact Task ID와 parent, frozen Tool capability,
동일 route/Work binding과 cache/result identity를 확인한다.
허용 범위 밖 parent와 계정 불일치, WRITE binding, 허용 Tool 제거는 기존 owner에서
synthetic dispatch 전에 차단돼야 한다. 다른 Run으로 cache를 resolve할 수 없어야 한다.
모든 성공/실패/control 결과를 새 `evaluation/results/070-query-read-handoff/`에
배타적으로 보존한다. 실패를 성공까지 반복하거나 기존 raw를 바꾸지 않는다.

신규 LLM0, 실제 Provider READ/WRITE0, Approval0, graph/user-facing workflow 실행0.
이는 component gate이며 semantic Evidence 선택·Sufficiency·Planning 답변·업무 완료,
실제 OAuth/Provider 권한, Canonical92 또는 반복 모델 안정성의 증거가 아니다.
기존 Query/READ/scope/Work handoff 관련 작은 직렬 테스트로만 회귀를 확인한다.
