# Production Smoke Test 6건 — 2026-09-12

실행 제품: `835b3aa471ecd1def5280dfd7dcfe4167a4977d4` · Graph: production compiled LangGraph · 모델: `qwen3.5:9b` (`0.2`, seed `1729`)

| Case | Business | Wait/Resume | Final Terminal | 최초 실패/도달 | LLM | READ | WRITE | SEND | Run | Trace |
|---|---|---|---|---|---:|---:|---:|---:|---|---|
| 대상 없는 일정 | FAIL | confirmation 미도달 / resume 0 | `BLOCKED` | request_understanding.detect_ambiguity post-inference validator | 7 | 0 | 0 | 0 | `3770d38d-3940-4a15-b18a-829590c5d7ff` | [Trace 1](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095cb-445a-7891-ada7-d358c5d394c2/run/01a095cb-445a-7891-ada7-d358c5d394c2), [Trace 2](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095cb-4482-72a3-8904-5b374ae8a7a5/run/01a095cb-4482-72a3-8904-5b374ae8a7a5) |
| Selected Event | PASS | 없음 | `COMPLETED` | 요청 업무 완료 | 9 | 1 | 0 | 0 | `ebc933b4-b36c-48bd-bc97-2834d7bf2d24` | [Trace 1](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095cc-c79c-79e2-9ca6-3d12361d1821/run/01a095cc-c79c-79e2-9ca6-3d12361d1821), [Trace 2](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095cc-c7c3-7553-9ec3-274733cae188/run/01a095cc-c7c3-7553-9ec3-274733cae188) |
| Atlas cross-source Draft | FAIL | 부당한 WAITING_CONFIRMATION / resume 0 | `WAITING_CONFIRMATION` | request_understanding.identify_source_dependencies LLM producer | 6 | 0 | 0 | 0 | `2958fb8e-bd14-4a27-baa1-bbdf9c810eed` | [Trace 1](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095d0-113f-7d60-a346-d71475b3693f/run/01a095d0-113f-7d60-a346-d71475b3693f), [Trace 2](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095d0-1166-7f62-8733-e04f263e5b5b/run/01a095d0-1166-7f62-8733-e04f263e5b5b) |
| Juniper 전체 제목 | FAIL | 없음 | `COMPLETED` | request_understanding.identify_goal LLM producer | 14 | 13 | 0 | 0 | `da40c498-4863-4fbd-90e8-87d439ae422a` | [Trace 1](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095cd-5e95-7c22-9fd5-071afb32adf5/run/01a095cd-5e95-7c22-9fd5-071afb32adf5), [Trace 2](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095cd-5eb8-7040-9276-d18d3eb03f7c/run/01a095cd-5eb8-7040-9276-d18d3eb03f7c) |
| Atlas q19 positive control | FAIL | 없음 | `COMPLETED / PARTIAL` | retrieval.plan_query initial semantic producer | 11 | 1 | 0 | 0 | `adeaf3c2-e871-4fbe-8897-d3f28dbeb6ae` | [Trace 1](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095ce-f42f-7600-a44d-65313d3714d8/run/01a095ce-f42f-7600-a44d-65313d3714d8), [Trace 2](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095ce-f455-7210-ae07-23868d7ad4e5/run/01a095ce-f455-7210-ae07-23868d7ad4e5) |
| Quartz Draft 수정 | PASS | WAITING_APPROVAL → same-Run 승인 1회 | `COMPLETED` | 요청 업무 완료 | 13 | 1 | 1 | 0 | `786b9c52-b311-42de-b8f6-88825158adb9` | [Trace 1](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095d0-7782-7742-9cba-4d49256e19e4/run/01a095d0-7782-7742-9cba-4d49256e19e4), [Trace 2](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095d0-77b2-7c12-b334-e87e7f217c54/run/01a095d0-77b2-7c12-b334-e87e7f217c54), [Trace 3](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095d1-53cb-7bc2-ae4f-11d19f1cd255/run/01a095d1-53cb-7bc2-ae4f-11d19f1cd255), [Trace 4](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095d1-55f4-7523-b59b-feb86aa6a454/run/01a095d1-55f4-7523-b59b-feb86aa6a454), [Trace 5](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a095d1-5613-7a92-a40b-f395212cfa15/run/01a095d1-5613-7a92-a40b-f395212cfa15) |

## FAIL 상세

### 대상 없는 일정

- 최초 실패: request_understanding.detect_ambiguity post-inference validator
- 기대: `{"ambiguity": "USER / target_resource", "lifecycle": "WAITING_CONFIRMATION → same-Run resume → Calendar READ → COMPLETED", "connector_reads_before_confirmation": 0}`
- 실제: `{"identify_goal": "CALENDAR_EVENT source dependency retained", "detect_ambiguity_input": {"selected_resource_count": 0, "resolved_resource_count": 0, "searchable_target_anchor_count": 0, "connector_owned_source_count": 1}, "llm_candidate": "USER / target_resource", "validator": "REQUEST_AMBIGUITY_RESOLUTION_OWNER_CONFLICT", "result": "올바른 LLM candidate가 validator에서 거절되어 BLOCKED"}`
- producer → validator → consumer: request_understanding.detect_ambiguity validation → REQUEST_AMBIGUITY_RESOLUTION_OWNER_CONFLICT → BLOCKED
- secondary failure: 없음
- 다음 수정 owner: detect_ambiguity post-inference semantic validator

### Atlas cross-source Draft

- 최초 실패: request_understanding.identify_source_dependencies LLM producer
- 기대: `{"source_reads": ["TASK", "CALENDAR_EVENT"], "outputs": ["GMAIL_DRAFT / CREATE"], "forbidden_effects": ["SEND"], "terminal": "WAITING_APPROVAL → same-Run approval → COMPLETED"}`
- 실제: `{"candidate_set": ["TASK", "CALENDAR_EVENT"], "source_dependency_decisions": ["TASK / SOURCE_NOT_REQUIRED", "CALENDAR_EVENT / SOURCE_NOT_REQUIRED"], "outputs": ["GMAIL_DRAFT / CREATE"], "forbidden_effects": ["SEND"], "downstream": "source_reads=[] 이후 USER / target_resource로 WAITING_CONFIRMATION"}`
- producer → validator → consumer: request_understanding.identify_source_dependencies → source_reads=[] 이후 USER / target_resource로 WAITING_CONFIRMATION → WAITING_CONFIRMATION
- secondary failure: detect_ambiguity가 유실된 source 책임을 바탕으로 USER / target_resource 생성
- 다음 수정 owner: identify_source_dependencies role-decision producer

### Juniper 전체 제목

- 최초 실패: request_understanding.identify_goal LLM producer
- 기대: `{"coverage_requirement": "collection 전체 범위", "pagination": "has_next_page=true이면 전체 완료 아님", "expected_title_count": 26}`
- 실제: `{"coverage_requirement": "누락", "initial_query": "SEARCH; KEYWORD/ANY; validator PASS", "first_page": {"result_count": 20, "has_next_page": true}, "follow_up": "DETAIL_FETCH 12회; NEXT_PAGE 0회", "sufficiency": "LLM SUFFICIENT; collection guard 미적용", "answer": "20건만 반환하면서 전체를 확인했다고 표현"}`
- producer → validator → consumer: request_understanding.identify_goal coverage semantics → 후단 결과 → COMPLETED
- secondary failure: assess_sufficiency가 has_next_page=true 상태를 SUFFICIENT로 종료
- 다음 수정 owner: identify_goal coverage 의미 생성 및 sufficiency collection guard 연결

### Atlas q19 positive control

- 최초 실패: retrieval.plan_query initial semantic producer
- 기대: `{"constraint_rule": "한 hypothesis에서 CONCEPT <= 1", "business_answer": "최종 출고 8월 19일 오전, 담당 지민"}`
- 실제: `{"request_intent": "GMAIL_THREAD + GMAIL_MESSAGE source; ambiguity CONNECTOR", "initial_candidate": "SEARCH; KEYWORD/ANY + CONCEPT×1 + STATUS_SCOPE", "duplicate_constraint_kind": false, "validator": "PASS", "connector": "정상 0건, has_next_page=false", "revision": "CHANGED candidate 2회 검토, 실행 가능한 새 effective query 없음", "answer": "Atlas 메일을 찾지 못했다고 응답"}`
- producer → validator → consumer: retrieval.plan_query query coverage → PASS → COMPLETED
- secondary failure: bounded follow-up이 새 실행 query를 만들지 못해 PARTIAL 종료
- 다음 수정 owner: plan_query initial/follow-up query coverage 품질 (raw literal은 미기록)

## Summary

- Business PASS: 2 / 6
- Business FAIL: 4 / 6
- Official Runs: 6
- new-Run rerun-to-pass: 0
- Confirmation resumes: 0
- Approval resumes: 1
- qwen3.5:9b: 6
- 4B fallback: 0
- LLM calls: 60
- Connector READ: 16
- Provider SEND: 0
- Provider WRITE: 1 (Quartz의 승인된 UPDATE)
- Unexpected Provider WRITE: 0
- LangSmith root traces: 6 / 6 cases (root records 15)
- Product execution SHA: `835b3aa471ecd1def5280dfd7dcfe4167a4977d4`
- Result commit SHA: 이 파일을 포함하는 Git commit (최종 보고에서 정확한 SHA 제공)
- Local/Upstream/Remote: 결과 commit에서 일치 여부 재확인
- Working tree: 결과 commit 후 재확인

상세 LangSmith payload 대신 노드 순서·typed semantic 결과·validator·호출 수만 `traces/`에 보존했습니다. 인증정보, raw Provider payload, 메일 원문, 검색 literal, Resource identity 값은 포함하지 않았습니다.
