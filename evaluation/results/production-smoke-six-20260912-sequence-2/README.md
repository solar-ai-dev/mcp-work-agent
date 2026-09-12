# Production Smoke 6건 — 교정 후 공식 1회 검증

- Branch: `codex/issue-251-connected-contract`
- 실행 제품: `d8e6c77946aca6389096b5f55a9ce95e7755ebec`
- Graph: production compiled LangGraph
- Model: `qwen3.5:9b`
- Temperature / seed: `0.2 / 1729`
- LangSmith project / experiment: `google-work-agent-development` / `production-smoke-six-d8e6c779-20260912`
- 공식 Run: 6건, 각 1회
- rerun-to-pass: 0
- Provider WRITE / SEND: 0 / 0

## 구현 결과

### Case 1 — 대상 없는 일정

- Root cause: 일반 Connector-owned information overlap 검사와 `target_resource` identity 전용 검사가 겹쳐, 식별되지 않은 target 자체를 USER가 정해야 하는 정상 후보까지 OWNER_CONFLICT로 거절할 수 있었다.
- Producer: `request_understanding.detect_ambiguity` LLM candidate.
- Validator: `_validate_ambiguity_candidate`의 일반 overlap과 target-specific invariant.
- Consumer: `requires_confirmation` / `WAITING_CONFIRMATION` projection.
- 변경 파일: `detect_ambiguity.py`, 직접 회귀 테스트.
- Prompt 변경: 없음.
- Schema 변경: 없음.
- State 변경: 없음.
- Main Graph 변경: 없음.
- Tool Route 변경: 없음.
- Regression: 직접 검사에서는 `USER / target_resource` 정상 허용과 anchor·Connector-owned attribute 반대 조건을 모두 통과했다. Production에서는 OWNER_CONFLICT가 다시 발생했다. 안전 투영에는 missing field 값이 노출되지 않아, 새 Run의 후보가 정확히 `target_resource`였는지는 회수하지 못했다.

### Case 3 — Atlas cross-source Draft

- Root cause: source dependency가 확정 output보다 먼저 실행돼, `GMAIL_DRAFT / CREATE`를 만들기 위해 필요한 upstream 자료를 source owner가 typed input으로 받지 못했다.
- Producer: `identify_output_responsibilities`.
- Validator: 기존 output/source candidate validator 유지.
- Consumer: `identify_source_dependencies` → `merge_resource_responsibilities`.
- 변경 파일: Request Understanding 실행 순서, output projection, source dependency caller/Prompt/input contract, merge, 관련 테스트.
- Prompt 변경: source dependency 책임을 “확정 output을 만들기 위해 필요한 기존 source 판단”으로 정합화.
- Schema 변경: 기존 canonical `ResourceResponsibilitiesV1` 출력 shape는 유지; Prompt input contract에 확정 output projection을 연결.
- State 변경: Main State/RequestIntentV2 변경 없음.
- Main Graph 변경: 없음. Request Understanding 내부 순서만 변경.
- Tool Route 변경: 없음.
- Regression: Production에서 `GMAIL_DRAFT / CREATE`가 먼저 확정되고, source call input에 해당 output이 전달됐으며 `TASK`와 `CALENDAR_EVENT`가 `SOURCE_REQUIRED`로 보존됐다. 원래 누락 결함은 해소됐다. 다만 같은 LLM이 container인 `TASK_LIST`와 `CALENDAR`도 source로 과선택했고, 27 READ 후 Evidence 선택 전에 LLM budget이 소진됐다.

### Case 4 — Juniper 전체 제목

- Root cause: coverage 판단이 큰 `identify_goal` 호출에 묶여 `EXHAUSTIVE` 의미가 누락됐다.
- Producer: 새 atomic `request_understanding.identify_coverage_requirement`.
- Validator: `[] | ["EXHAUSTIVE"]`의 bounded owner-local schema.
- Consumer: deterministic normalizer → 기존 `ConstraintV1(kind=SCOPE, field=coverage_requirement)` → 기존 sufficiency guard.
- 변경 파일: coverage decision contract/caller/Prompt, Request Understanding graph 연결, base goal schema/Prompt 정리, manifest/input contract, LangSmith safe projection, 문서·테스트.
- Prompt 변경: coverage만 판정하는 atomic Prompt 추가; base goal Prompt에서 coverage 책임 제거.
- Schema 변경: base goal `request-goal-candidate-v16`; atomic `request-coverage-requirement-v1` 추가.
- State 변경: 새 Main State 없음. 기존 RequestIntentV2 constraint shape 재사용.
- Main Graph 변경: 없음.
- Tool Route 변경: 없음.
- Regression: atomic owner는 실제 Production에서 호출됐으나 9B output이 `[]`였다. 첫 페이지 20건과 `HAS_MORE`가 관측됐지만 기존 exhaustive guard가 활성화되지 않아 NEXT_PAGE 없이 20/26건을 전체라고 답했다.

## 공식 Smoke 결과

| Case | Business | Terminal | 최초 잘못된 의미 / terminal blocker | LLM | READ | WRITE | SEND | Run | Trace |
|---|---|---|---|---:|---:|---:|---:|---|---|
| 대상 없는 일정 | FAIL | `BLOCKED` | `detect_ambiguity` OWNER_CONFLICT / 동일 | 8 | 0 | 0 | 0 | `2f807447-ce02-4b26-a9ee-49fb93d2115b` | [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095f4-fe2c-7d41-901a-138a19313137/run/01a095f4-fe2c-7d41-901a-138a19313137) |
| Selected Event | FAIL | `BLOCKED` | `identify_output_responsibilities`: 불필요한 `GMAIL_MESSAGE / SEND` / `plan_query` route scope | 9 | 0 | 0 | 0 | `d7dd3cd2-d45a-4019-bc8f-fb234bad3301` | [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095f6-662e-7443-82fd-eb727afe16f8/run/01a095f6-662e-7443-82fd-eb727afe16f8) |
| Atlas cross-source Draft | FAIL | `BLOCKED` | `identify_source_dependencies`: container 과선택 / `select_evidence` LLM budget | 20 | 27 | 0 | 0 | `d512f949-780d-4ab2-b674-9d421797445d` | [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095f7-40f4-7190-9be4-8f1cc270b054/run/01a095f7-40f4-7190-9be4-8f1cc270b054) |
| Juniper 전체 제목 | FAIL | `COMPLETED / SUCCESS` | atomic coverage output `[]` / 허위 전체 완료 | 15 | 13 | 0 | 0 | `3e9b60c5-9c37-4bc2-9eac-ada8b9cfc845` | [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095fb-1e6f-72b2-b986-91db97ae8fc0/run/01a095fb-1e6f-72b2-b986-91db97ae8fc0) |
| Atlas q19 positive control | FAIL | `BLOCKED` | `plan_query`: `CONCEPT` 중복 candidate / output schema invalid | 9 | 0 | 0 | 0 | `eebae2d9-5336-4abb-9a70-c9c5ce3f0ae3` | [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095fd-0177-7992-97c3-a5a561f3ecee/run/01a095fd-0177-7992-97c3-a5a561f3ecee) |
| Quartz Draft 수정 | FAIL | `RECOVERY_REQUIRED` | coverage `EXHAUSTIVE` 오판 / `compose_arguments_per_output_route` binding | 11 | 1 | 0 | 0 | `f3e96b3d-fa5a-4fc0-ae6d-45aafe4ad2b2` | [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095fe-ff84-7611-9ab8-d6683c5b4ba4/run/01a095fe-ff84-7611-9ab8-d6683c5b4ba4) |

## 핵심 관측

- Business PASS / FAIL: `0 / 6`.
- LangSmith root: `6 / 6`; 종료 후 원격 상태는 Case 4만 success, 나머지는 error.
- LLM / Connector READ: `72 / 41`.
- Source page / detail: `29 / 12`.
- Provider WRITE / SEND: `0 / 0`.
- 새 atomic coverage projection: 6건 모두 Trace에서 확인.
- Case 1은 initial + bounded revision 모두 `USER`, missing field 1개였지만 안전 투영 정책상 field 값은 감춰졌다.
- Case 2는 selected Resource 1개와 resolved count 1을 인식했지만, output owner가 요청하지 않은 SEND를 만들었고 `$.route_queries[].detail_candidate_ref`에서 route scope validation이 실패했다.
- Case 3은 `TASK`, `CALENDAR_EVENT` source와 `GMAIL_DRAFT / CREATE`, SEND 금지를 보존했다. 추가 container source 과선택과 LLM budget 소진이 남았다.
- Case 4는 첫 페이지 20건, `has_next_page=true`, collection continuation `HAS_MORE`, NEXT_PAGE 0, 최종 제목 20건이었다.
- Case 5는 initial candidate가 `KEYWORD / ANY + CONCEPT + CONCEPT`였고, `$.route_queries[0].search_spec.constraints` post-inference validation에서 거절됐다.
- Case 6은 Draft 1건 READ와 Evidence 1건, sufficiency `SUFFICIENT`까지 갔으나 planning argument binding에서 실패해 Action/Preview/WAITING_APPROVAL에 도달하지 못했다.

## 자동 검증

- 관련 Request Understanding, Retrieval, Prompt runtime, architecture, LangSmith projection, budget, component/integration: `871 passed`.
- Ruff: 통과.
- 직접 영향 source mypy: 통과.
- 전체 `mypy src tests`: 저장소 기존 범위에서 `81 errors / 24 files`; 이번 변경 밖 baseline을 수정하지 않았다.
- `git diff --check`: 통과.

상세 원문 Prompt/completion, Provider payload, Resource identity, credential은 저장하지 않았다. 각 JSON에는 판정에 필요한 safe projection만 기록했다.
