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

## 잔여

1. `DEC-001`의 선택값은 구현됐지만 deterministic production-composition에서 partial
   approval과 same-Run restart confirmation이 각각 선택된 18/20 한도 안에서 여전히
   `BLOCKED`다. 한도 확대·owner 제거·지원 범위 축소 중 추가 제품 의미 결정 전에는 보류한다.
2. Juniper initial query coverage와 Atlas q19 query/evidence 품질은 구조 결함과 분리한
   `NODE_SEMANTIC_FAIL` 후속 품질 작업.
3. Dataset 115개 실제 Live는 자동 runner/provisioning/WRITE 승인 범위 확정 후 별도 실행.

## 재개 지점

`decisions.json`의 네 결정은 모두 확정·반영됐다. 다음 제품 변경 전에는 `DEC-001`의 남은
E2E가 고정 한도 안에서 지원되어야 하는지, LLM owner를 줄일 수 있는지, 또는 지원 범위를
축소할지 결정한다. 새 공식 검증 batch는 동일 SHA/Prompt/model 설정을 사전 고정하고
rerun-to-pass 없이 실행한다.
