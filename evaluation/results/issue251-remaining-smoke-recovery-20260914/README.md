# Issue 251 남은 Production Smoke 결함 복구

- Start HEAD: `668bccfc0506d11491e11cbb78e81f3cf06cfcc9`
- 실행 제품 SHA: `6481327465ec05af3cad2a5c843abf1dbc32f3cc`
- 브랜치: `codex/issue-251-connected-contract`
- 모델: `qwen3.5:9b` / digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature / seed: `0.0` / `null`
- Prompt binding: `request_understanding.identify_goal` `1.0.62` / `98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa`
- 실제 source-page 상한: `50`
- LangSmith: 제품 safe tracing만 사용, 자동 tracing 비활성

## 결론

확정 결함 3건의 owner-local 수정을 구현했다. Atlas Draft와 Quartz Draft는 수정 후 최초 Production Smoke에서 정확한 Preview와 `WAITING_APPROVAL`에 도달했다. 대상 없는 Calendar는 기존 provenance mismatch는 제거됐지만, 확인값을 `RESOURCE/title`로 보존한 뒤에도 ambiguity owner가 이를 검색 가능한 target anchor로 인정하지 않아 다시 `WAITING_CONFIRMATION`이 됐다.

단발 조건에 따라 Calendar를 재실행하거나 두 번째 확인에 답하지 않았다. 실패 3건이 모두 통과하지 않았으므로 최종 6개 Smoke도 실행하지 않았다.

| Case | 원인 | 수정 owner | 수정 내용 | 단발 결과 |
| --- | --- | --- | --- | --- |
| 대상 없는 Calendar | confirmation resume가 unrelated source/status owner를 재호출해 current-Run provenance와 충돌 | Request Understanding confirmation resume | 기존 goal, responsibilities, source status와 provenance를 보존하고 base goal call 1회에서 확인값만 결합 | FAIL — provenance 오류는 사라졌으나 `RESOURCE/title`이 searchable anchor로 계산되지 않아 두 번째 `WAITING_CONFIRMATION` |
| Atlas Draft | 같은 의미의 LLM 출력 variance가 source anchor를 수신자/Draft 쪽으로 바꾸어 Calendar 0건·Evidence 0건 후 실행 불가능한 follow-up을 생성 | Task+Calendar Draft source-term projection | 원문에 실제 존재하는 typed `business_concepts`의 Task/Calendar source-bound term만 복구해 초기 query, Evidence 선택, payload가 같은 capability-local authority를 사용 | PASS — READ 47/50, 정확한 Task 2건과 Calendar Event 1건의 Draft Preview, `WAITING_APPROVAL` |
| Quartz Draft | authoritative snapshot을 결속한 뒤 LLM patch가 no-op이 되면서 exact edit literal 유실 | GMAIL_DRAFT/UPDATE argument materialization | original request의 quoted literal이 typed RESOURCE notes와 completion condition에도 동시에 존재하는 단일 값일 때만 snapshot body에 1회 append | PASS — 기존 Draft 필드 보존, exact literal 1회, `WAITING_APPROVAL` |

## Atlas PASS/FAIL 최초 divergence

기존 PASS와 FAIL은 같은 제품 코드·모델 digest·temperature·Prompt와 같은 `TASK + CALENDAR_EVENT → GMAIL_DRAFT/CREATE` 책임을 사용했다. 최초 의미 차이는 Request Understanding의 LLM constraint 값이었다.

- PASS: source를 식별하는 search term이 남아 Calendar에서 관련 Event를 회수했다.
- FAIL: search term이 수신자와 Gmail Draft 쪽으로 바뀌어 23개 Calendar 조회 결과가 0건이었다.
- 47 READ 뒤 최초 후행 차이: PASS는 Task 2건 + Event 1건을 SUPPORTS로 선택해 SUFFICIENT가 됐고, FAIL은 후보를 모두 제외해 Evidence 0건이 된 뒤 필수 route를 빠뜨린 follow-up query가 `ROUND_VALIDATOR`에서 거절됐다.

남은 budget은 3회뿐이고 성공 자료가 있던 Calendar는 전체 순회 중 12번째였으므로 follow-up candidate만 바꾸는 방식으로는 같은 50 상한 안에서 안전하게 복구할 수 없었다. 따라서 공통 Request Understanding이나 q19/Juniper를 바꾸지 않고 Task+Calendar Draft capability의 기존 source-term authority를 최소 보강했다. Juniper `EXHAUSTIVE → NEXT_PAGE`와 q19 `non-EXHAUSTIVE + CANDIDATE_DETAIL_REQUIRED → DETAIL_FETCH` 불변식은 직접 테스트로 고정했다.

## Calendar의 새 최초 실패

재개 Trace에서 `identify_goal`은 기존 source status/provenance와 responsibilities를 보존했고 `RESOURCE/title` 확인값도 추가했다. 하지만 뒤의 `detect_ambiguity` projection은 `searchable_target_anchor_count=0`, `resolved_resource_count=0`으로 계산했고 LLM도 `missing_fields=[target_resource]`를 다시 반환했다.

현재 searchable target contract는 `search_terms`, `subject`, `search_criteria_subject`만 인정한다. `title`을 전역 anchor로 추가하거나 confirmation의 `target_resource`를 어느 canonical 검색 필드로 materialize할지는 제품 의미 선택이므로 이번 단발 결과 뒤 추가 수정하지 않았다.

## 변경 경계

- Prompt 변경: 없음
- Schema / State / Node / Edge 계약 변경: 없음
- validator 완화: 없음
- budget / round / retry 변경: 없음
- 새 LLM 호출: 없음; Calendar resume의 호출은 5개 owner 재실행에서 base goal 1개로 감소
- 추가 자율 수정: 없음
- 판단이 필요해 수정하지 않은 항목: Calendar confirmation target의 canonical searchable field mapping

## 검증

- 직접 pytest: `174 passed`
  - Request Understanding + node/budget: 107
  - Draft Planning/Task+Calendar materialization: 15
  - Retrieval + q19/Juniper plan invariants: 52
- Ruff: 통과
- mypy: 변경 source 6개 통과 (`misc`의 기존 TypedDict overwrite 진단 제외)
- 실패 3 Case Production Smoke: 각 1회, rerun-to-pass 0
- 승인 클릭: 0
- Approval record: 0
- execution attempt: 0
- Provider WRITE/SEND audit event: 0
- 최종 6 Smoke: 미실행(Calendar 단발 실패로 선행 조건 불충족)

## Run / LangSmith

| Case | Run ID | Trace | root / node / LLM / tool |
| --- | --- | --- | --- |
| 대상 없는 Calendar initial | `a1b40bf0-2081-4f55-8000-ab2424a24fc9` | `01a09c8b-0099-7080-8905-4396fe38bfb9` | 1 / 6 / 6 / 0 |
| 같은 Run confirmation resume | 위와 같음 | `01a09c8b-7d00-7800-9ea3-66f203a6c3d1` | 1 / 6 / 2 / 0 |
| Atlas Draft | `62382bb4-4ad3-44e6-b23b-2fcd5c292ae2` | `01a09c8c-ce68-7741-ace7-9ddbf6a37898` | 1 / 36 / 8 / 47 |
| Quartz Draft | `440b05f8-5be4-48dd-a568-c23fa483a7a6` | `01a09c8d-be40-7473-8114-6dc03470c50f` | 1 / 36 / 14 / 1 |

Calendar는 Connector 진입 전에 다시 확인을 요청했으므로 tool span과 Connector READ가 0이다. 비밀키, OAuth 토큰, 불필요한 Provider 원문은 저장하지 않았다.
