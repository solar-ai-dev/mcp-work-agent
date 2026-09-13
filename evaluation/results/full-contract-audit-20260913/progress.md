# Progress and resume point

## 완료

- 2,306개 실제 대상 inventory와 ID 생성.
- Source Guide와 owning Canonical을 기준으로 Prompt 28개, semantic operation 87개,
  API/Connector/Projection/State/Persistence/Approval/Execution/Verification/Recovery 경계 검수.
- 승인 없이 수정 가능한 확정 결함 14건 수정·직접/인접 검증·owner별 commit/push.
- Prompt exact-set/input-contract/hash, compiled Graph, Retrieval continuation/cache,
  selected Resource, Write lifecycle 회귀 검증.
- qwen3.5:9b + 실제 production compiled LangGraph + Google Workspace + LangSmith로
  공식 Smoke 6건 직렬 1회 실행.
- 전체 Python/Frontend/evaluation 구조 Gate 실행.
- 안전한 결과 artifact와 ZIP 생성·재개방 검증.
- 사용자 결정 `DEC-001..004`를 제품 SHA `b6c42a75c0f2cbe611e719dfb2f90789cf236cab`에 반영하고 직접·인접 계약과
  compiled production-composition 경계를 재검증.
- 결정 이후 Smoke 6건을 제품 SHA `24aeab3f2a671771c4bb41985d95ed603235ffa1`에서
  직렬 1회 실행: Contract 6/6, Business 3/6, LangSmith root 6/6, WRITE 0.
- Selected Event output responsibility와 Quartz no-op Draft UPDATE의 확정 결함을 owner별로
  수정하고 Production 결과로 검증.
- 실제 Node 입력을 고정한 candidate/temperature 실험을 수행하고 q19 `identify_goal`의
  최저 안정값 0.1을 기존 prompt-local policy authority에 반영.
- 최종 영향 회귀 1,100건, test fixture 72건, Ruff, 전체 mypy 1,723파일 통과.

## 잔여

1. `DEC-001`의 선택값은 구현됐지만 deterministic production-composition에서 partial
   approval과 same-Run restart confirmation이 각각 선택된 18/20 한도 안에서 여전히
   `BLOCKED`다. 한도 확대·owner 제거·지원 범위 축소 중 추가 제품 의미 결정 전에는 보류한다.
2. Atlas Draft는 `detect_ambiguity`, Juniper는 `identify_output_responsibilities`가 최신 최초
   의미 실패다. structural guard가 정답을 생성하도록 확대할 수 없어 후속 owner 품질 작업으로 남긴다.
3. Dataset 115개 실제 Live는 자동 runner/provisioning/WRITE 승인 범위 확정 후 별도 실행.
4. 최신 제품 SHA의 최종 Smoke는 Google OAuth 재인증이 필요해 공식 Graph Run 생성 전에
   차단됐다. 재인증 후 동일 SHA의 6개 직렬 Live가 필요하다.

## 재개 지점

`decisions.json`의 네 결정은 모두 확정·반영됐다. Google Workspace 재인증 뒤 제품 SHA
`074a3cc50da59b0cb64ef41a484ebdc4e6f11283`의 공식 Smoke 6건을 직렬 1회 실행한다.
Atlas/Juniper의 남은 semantic producer는 현재 closed Typed State만으로 candidate를 제거할
근거가 없으므로 deterministic correction을 추가하지 않는다. 새 공식 검증 batch는 동일
SHA/Prompt/model 설정을 사전 고정하고 rerun-to-pass 없이 실행한다.
