# Issue 251 회귀 복구 6개 Production Smoke

- 실행 제품 SHA: `a2bca16f98d80262c4fc28a6955a343174b0b906`
- 브랜치: `codex/issue-251-connected-contract`
- 실행 중 코드 변경: 없음
- 모델: `qwen3.5:9b` / digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature / seed: `0.0` / `null`
- Prompt binding: `request_understanding.identify_goal` `1.0.62` / `98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa`
- LangSmith: 제품 safe tracing만 사용, 자동 tracing 비활성
- 실제 source-page 상한: `50`

## 결론

6개 중 3개가 통과했다. 따라서 이번 회귀 복구는 종료 조건을 만족하지 않았다.

| Case | 결과 | Run 상태 | 확인 결과 |
| --- | --- | --- | --- |
| 대상 없는 일정 | FAIL | `WAITING_CONFIRMATION` → 같은 Run resume → `BLOCKED` | 확인 답변 뒤 `REQUEST_STATUS_PROVENANCE_MISMATCH`; Connector READ 0 |
| Selected Event | PASS | `COMPLETED / SUCCESS` | 선택한 `Atlas 인쇄소 슬롯`을 `calendar_get_event` 1회로 읽고 2026-08-13 14:00~15:00을 정확히 답변 |
| Atlas Draft | FAIL | `BLOCKED` | Calendar 23 + Task 22 + container discovery 2 = READ 47 후 `ROUND_VALIDATOR / RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID`; Preview 미도달 |
| Juniper 제목 전체 | PASS | `COMPLETED / SUCCESS` | Typed `EXHAUSTIVE` 유지, `gmail_search_threads` 2회, 26건, `EXHAUSTED`; 데이터셋 26개 제목과 누락·추가 없이 일치 |
| Atlas q19 | PASS | `COMPLETED / SUCCESS` | `gmail_search_threads` 1회 → `gmail_get_thread` 12회; Evidence에 8월 19일 오전·지민이 함께 존재하고 답변도 일치 |
| Quartz Draft | FAIL | `WAITING_CONFIRMATION` | `gmail_search_drafts` 1회 뒤 내부 UPDATE 계획은 생겼지만 요청 문장 포함 횟수 0; Review가 불필요한 추가 확인을 요청하여 `WAITING_APPROVAL` 미도달 |

## 실행·안전 조건

- 최초 Domain Run: `6`
- rerun-to-pass: `0`
- 정상 설계에 따른 같은 Run confirmation resume: `1` (대상 없는 일정)
- 승인: `0`
- execution attempt: `0`
- Provider WRITE/SEND audit event: `0`
- Domain Run 내부 Connector READ: `64`
- 실행 전 만료된 일회용 bootstrap 교환 1건은 Domain Run 생성 전 발생했으며 Smoke 재실행에 포함되지 않는다.

## Case별 Run / Trace

| Case | Run ID | LangSmith Trace |
| --- | --- | --- |
| 대상 없는 일정 | `bfce82a1-5615-4d14-b312-e0335df245f8` | initial `01a09c54-0ae1-7ee1-80bc-2b43d9d405be`, same-Run resume `01a09c54-83ff-7ae1-8e53-ad81499719c0` |
| Selected Event | `0cc583fd-5e97-4969-ad59-0b8bb327d615` | `01a09c54-ddbd-7ad2-a606-6b1d3182c085` |
| Atlas Draft | `7ba04bb1-a5bf-4a9a-ade1-4f49a5dacc0a` | `01a09c55-6bb8-7e20-bc83-5f923850949a` |
| Juniper 제목 전체 | `99a4e9d2-6e38-47a8-912d-86201bf421f6` | `01a09c57-49e4-7421-a3ad-1d90efce8731` |
| Atlas q19 | `837f2207-b1b2-46d4-9c33-fe41869474ea` | `01a09c59-6fe4-7172-99de-e5a890eb1198` |
| Quartz Draft | `38a732f3-6747-4388-99ee-a3e63006e6fa` | `01a09c5b-0d21-7972-872d-9fd0f64bb2dc` |

각 Trace에서 root와 node/LLM span을 확인했다. Connector에 도달한 5개 Case에는 tool span도 있다. 대상 없는 일정은 검증 단계에서 차단되어 tool span과 Connector READ가 모두 0이다.

## 판정 근거

- Juniper: checkpoint의 `coverage_requirement=EXHAUSTIVE`, `scope_complete=true`, `continuation_status=EXHAUSTED`, `observed_resource_count=26`; 최종 목록은 데이터셋 26개와 집합이 정확히 같다.
- Atlas q19: checkpoint `coverage=SUFFICIENT`, 상세조회 12회, durable Evidence 9건 중 1건에 최종 출고일·오전·담당자가 함께 존재한다.
- Atlas Draft: source/output 의미는 `TASK + CALENDAR_EVENT → GMAIL_DRAFT/CREATE`로 보존됐지만 후속 query plan의 `$.route_queries`가 round validator에서 거절됐다.
- Quartz: source/output 의미는 `GMAIL_DRAFT → UPDATE`로 보존됐지만 내부 Planning action의 body에 요청 문장이 들어가지 않았고 Review가 `CONFIRM`을 반환했다.

비밀키, OAuth 토큰, 불필요한 메일 원문과 Provider payload는 저장하지 않았다.
