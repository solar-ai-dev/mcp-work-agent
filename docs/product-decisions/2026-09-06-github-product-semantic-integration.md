# Google / GitHub 의미 통합 기록

## 고정 기준

- Product: `292538b429a93638afc1ba3a59f7efff7fb4c836`
- Team: `69848b581e4fbccb88054572e7577c9024ee782f` (main, PR #182)
- Merge base: `da11ea5735ea070a1429dd313d31b5470bb6d97d`
- Integration 시작: Product와 동일. 3.1 INCOMPLETE, 4/8 PARKED.
- 날짜 사실성, LLM budget starvation, 인물 해소의 기존 미완료는 이번 기능 범위에 포함하지 않는다.

## Semantic Integration Map

| Capability | Product 의미 | Team 의미 | 충돌/누락 가정 → 최종 계약 | Owner와 producer → consumer | 통합 검증 |
| --- | --- | --- | --- | --- | --- |
| 요청/identity/provenance | immutable run_input, user_message_id, vague Google READ | 5-field identity, repository source span | 구 source identity와 복원 소비자 → persisted ResourceRef 기반 exact identity, repository는 명시 요청/선택 근거만 사용 | start_run → workflow_execution / main.state → Request Understanding, resume | Gmail/GitHub 선택·복원·메시지 연결, 잘못된 binding 거부 |
| Routing/query | semantic query, temporal axis, bounded expansion | ISSUE/GITHUB_ISSUE, repository, OPEN/CLOSED | type/schema/validator와 실제 모델 경로 차이 → frozen route별 resource/status/container 계약 | tool_routing → retrieval.plan_query / query_plan_schema / build_query → execute_read projection | 실제 output schema 검증, status 교차 오용 거부, shortcut와 inference |
| Acquisition/Evidence | Message provenance, 현재 chunk/version 구조, selected Evidence 유지 | composite Issue identity, github observation/source | Google-only fallback과 source별 normalization → source attribution 유지, 동일 source 안정성·변경 시 stale 제거 | connector_read_projection → normalize_segments → select_evidence / finalize_retrieval → Planning → plan_persistence / resource_ref_projection | Gmail 세부 근거 회귀, Issue list/get, mixed-source retention, 최종 ResourceRef 저장 |
| Sufficiency/follow-up/budget | detail hydration, distinct query, READ partial/WRITE fail closed | CONNECTOR gap | GOOGLE만 인식하는 consumer → source별 frozen route의 SEARCH/PAGE/DETAIL만 허용, 실패·빈 결과·인증 구분 | assess_sufficiency → plan_candidate_detail / plan_query_expansion → Retrieval graph, RunBudget | CONNECTOR 후속 호출/회계, 충분한 route 반복 0, safety-critical 대칭 |
| Supervisor/Confirmation | state-driven routing, freshness, same-Run resume | GitHub typed result/repository choice | READ USER issue 일괄 제거 → Gmail 조기 확인 방지와 repository 선택 책임 분리 | owner result → Supervisor → 기존 Confirmation controller / checkpoint | GitHub typed result, back-edge binding, freshness/no-progress |
| Planning/Approval/Claim | Task/Calendar 부분 WRITE, 승인/실행 admission | Issue effect/target/repository, connector-signed Claim | Google lookup 가정 및 Claim wire 변화 → 동일 lifecycle, exact Connector/target/approved arguments | planning → persisted approval → build_claim_context → MCP validator/dispatch | 교차 Claim/오래된 승인/잘못된 repository I/O 전 거부 |
| Verification/Recovery/answer | terminal Assistant Message, uncertain delivery 안전성 | GitHub 결과 재조회/복구 | source/expected 혼용 → 승인 expected 독립 유지, 동일 Connector actual 검증, blind retry 0 | verify_effect / lookup_unknown_result → Response/terminal commit | UPDATE 필드 검증, mismatch 불승격, answer source와 terminal 1회 |
| Connection/UI | Google 연결, local qwen3.5:9b WORKER/REASONING | GitHub Device Flow/keyring/error action | Google 기본값 가정 → credential/session/UI Connector 일치, 선택적 GitHub 미연결은 Google 방해 0 | composition → credential Port/MCP → API → Frontend | connection isolation, reauth projection, 실제 앱 smoke |
| Registry/persistence/release | signed runtime, existing migration history | GitHub descriptor/hash, migration 0020 | 생성물/서명/기존 DB 정합성 → 기존 generator/검증과 forward migration 적용 | signed registry → runtime registry / launcher / migration discovery | descriptor parity, migration checksum, release composition |

## 실제 발견과 cut-over

- selected identity의 타입 변경 외에 `request_from_run_input_state`, checkpoint admission, 요청 해석, `GET /runs/{id}/context`까지 5-field 계약으로 연결했다. 구 source-only checkpoint는 새 Run/WRITE로 재실행하지 않고 거부한다. `user_message_id`를 보존한다.
- GitHub `OPEN/CLOSED`를 실제 모델 출력 schema와 route별 validator에 연결했다. repository provenance는 Google의 검색 가설과 분리하고, container 누락/충돌을 추측으로 채우지 않는다.
- `GOOGLE/CONNECTOR` follow-up을 해당 frozen route에 묶었다. 정상 빈 결과/실패, READ partial/WRITE 필수 근거, 정책·인증·identity 안전 차단을 구별한다. 새로운 source의 Evidence가 기존 selected Evidence 때문에 영구 배제되지 않도록 bounded retention을 보완했다.
- Argument Writer의 생략 가능한 immutable container가 모델 출력 schema에서 필수여서 조립 전에 실패했다. 생략/동일값 두 schema 경로를 정확히 구분하고 기존 assembler에서 주입한다. 다른 container, 빈 UPDATE, 잘못된 업무 인자 검증은 유지한다.
- 실제 Google READ에서 context API의 구 source 응답 schema 때문에 화면이 최종 답변을 표시하지 못했다. API·Frontend context projection을 5-field/GitHub source/count 계약에 맞췄다.
- 실제 GitHub READ Run `97276f73-d418-4a35-8386-12026e69e60b`는 답변 생성 후 `terminal_commit`에서 실패했다. 자동 병합된 `main.plan_persistence`의 Google-only Evidence handle 해석과 `resource_ref_projection`의 durable resource whitelist 누락을 수정했다. source-family substring 대신 exact resource type으로 frozen Connector를 해석한다. 별도 GitHub terminal writer는 만들지 않았다.
- Claim V2의 connector 서명/양쪽 MCP 검증, BeginExecutionAttempt admission, 승인 expected와 actual의 독립 검증, UNKNOWN_RESULT blind resend 금지를 유지한다. 기존 migration은 수정하지 않고 0020만 추가한다.

## 검증 결과

전체 제품 회귀는 실행하지 않았다. 아래는 직접 영향 범위이며 서로 일부 중복되는 실행 결과를 합산하지 않는다.

| 증거 종류 | 범위 | 결과 |
| --- | --- | --- |
| deterministic unit/contract | 요청 해석·Retrieval·Routing·Planning·Claim·execution·verification·recovery·Connector·identity/resume | 533 passed |
| compiled integration/component/contract | `tests/component/langgraph`, `tests/integration/langgraph`, 선택 context API, MCP subprocess, migration, registry/prompt/Connector 구조, release/launcher | 158 passed |
| controlled production composition | 승인 WRITE·UNKNOWN_RESULT·재시작·재인증, 세 GraphProfile; 실제 workflow와 fake LLM/MCP | 12 passed (42 deselected); 실제 Provider WRITE 증거는 아님 |
| terminal persistence 직접 영향 | GitHub exact ResourceRef/최종 context, 기존 resource projection, answer-only persistence | 15 passed |
| Frontend | app integration 109, settings/onboarding 5, recovery 2, GitHub context 1 | 117 passed; TypeScript typecheck/build 통과 |
| 정적 검사 | Ruff, mypy, diff check, staged Prompt SHA-256 | 통과; mypy 970 source files; 수정 Prompt 3개 hash 일치 |

### 실제 앱 / Provider

- Google selected Gmail READ: Run `56be04e9-75b8-4695-a88d-bf56ac75bdc0`. 실제 UI → production LangGraph/Prompt → Ollama `qwen3.5:9b` (`LOCAL_GPU`) → Gmail → persistence/화면. COMPLETED, USER 1/ASSISTANT 1, Action 0. GitHub 미설정 상태에서도 완료됐다.
- GitHub 재검증: Run `676d9a5a-3dc3-403d-9045-fbbd2c4eec92`. 동일 읽기 요청을 실제 UI에서 재실행했다. Trace에 `identify_goal → plan_query → select_evidence → assess_sufficiency → outline_answer → compose_answer` 6회 모두 Ollama `qwen3.5:9b`/LOCAL_GPU가 기록됐다. checkpoint 회계는 Connector 1, source page 1, detail 0, LLM 6이다.
- 위 GitHub Run은 COMPLETED/SUCCESS, USER 1/ASSISTANT 1, Action 0, Evidence 12, ResourceRef `github/github_issue/solar-ai-dev/google-work-agent#181`이다. 최종 화면의 열린 Issue 번호·제목·상태는 별도 실제 GitHub 조회와 일치한다. 인증 후 앱 재시작에서도 계정 연결을 유지했다.
- GitHub 실제 WRITE/권한 거부/토큰 만료 전체 E2E는 미검증이다. 이슈/댓글 생성·수정·삭제는 하지 않았다. 향후 테스트 이슈 생성은 사용자 소유 개인 repository 또는 `solar-ai-dev`에만 허용된다.

### Baseline 실패의 비교 근거

Product SHA `292538b429a93638afc1ba3a59f7efff7fb4c836`를 별도 detached worktree에서 동일 interpreter로 실행해 아래 실패를 비교했다. enforcement/기대값을 완화하지 않았으며 이 실패들을 PASS로 계산하지 않는다.

- `tests/architecture/test_repository_architecture.py`: 양쪽 모두 3 failed / 13 passed / 5 skipped. 실패는 `test_immediate_agent__atomic__grammar`, `test_immediate_public__alias_reexport_and__duplicate_definition_zero`, `test_python_test_functions__across_repository__match_canonical_naming_grammar`. 기존 미등록 capability 파일, `require_mapping` 중복 public symbol, 기존 테스트 naming 위반이다. 경로별 위반 메시지 집합이 동일하며 새 위반은 없다.
- `tests/e2e/test_langgraph_real_production.py::test_google_reads_reach__terminal_through_actual__retrieval_and_mcp[SINGLE_BASELINE-GMAIL_READ-gmail_search_threads]`: 양쪽 모두 fake goal의 빈 constraints가 실제 schema의 minItems 1을 위반해 실패한다.
- 같은 테스트의 `[SINGLE_BASELINE-TASKS_READ-tasks_list_tasks]`: 양쪽 모두 실제 deterministic Task 답변과 예전 한국어 기대 문자열이 달라 실패한다. 위 두 실패는 `--maxfail=2`에서 중단했으므로 나머지 해당 Google 시나리오를 PASS로 주장하지 않는다.

통합 중 발견한 신규 실패는 수정 후 직접 영향 자동 테스트와 위 실제 GitHub READ 재실행으로 확인했다. 전체 repository 구조 Gate는 baseline 실패 때문에 green이 아니다. 3.1의 날짜 사실성·budget starvation·인물 해소는 여전히 INCOMPLETE이고 4/8은 PARKED다. Product 반영은 저장소 PR/승인 규칙을 따른다.
