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

## 잔여

1. `DEC-001`: 정상 multi-output/same-Run confirmation의 LLM-call budget 또는 owner 축소 결정.
2. `DEC-002`: RU semantic 오판에 deterministic guard를 둘 의미 범위 결정.
3. `DEC-003`: FAILED→CONTRACT_VIOLATION recovery taxonomy 결정.
4. `DEC-004`: 자연어 target anchor 동일성 정책 결정.
5. Juniper initial query coverage와 Atlas q19 query/evidence 품질은 구조 결함과 분리한
   `NODE_SEMANTIC_FAIL` 후속 품질 작업.
6. Dataset 115개 실제 Live는 자동 runner/provisioning/WRITE 승인 범위 확정 후 별도 실행.

## 재개 지점

제품 코드를 더 수정하기 전에 `decisions.json`의 결정부터 받는다. DEC-001은 현재
deterministic E2E 6건의 직접 blocker다. DEC-002는 Selected Event와 Atlas Draft의 현재
첫 semantic producer에 영향을 준다. 이후 동일 SHA/Prompt/model 설정으로 새 공식 검증
batch를 사전 고정하고 rerun-to-pass 없이 실행한다.
