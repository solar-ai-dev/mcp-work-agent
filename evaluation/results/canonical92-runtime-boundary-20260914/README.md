# Canonical 92 실행 경계 연결 결과

## 판정 요약

| 항목 | 결과 |
| --- | --- |
| STRESS profile adapter 직접 경계 검증 | 20/20 완료 |
| 미완료 profile | 0 |
| 모델 평가 실행 | 0 |
| 전체 Smoke / 전체 pytest | 0 / 0 |
| 실제 Google WRITE | 0 |
| 제품 source / Prompt / Graph 판단 로직 변경 | 0 / 0 / 0 |
| BENCHMARK_READY 범위 | 아래 표의 평가 모드와 직접 경계까지만 확인 |

이번 결과는 Case terminal PASS가 아니다. 실제 모델을 포함한 Canonical 92 실행은 하지
않았으며, 각 profile의 장애·시간이 평가 adapter를 거쳐 Product가 소비하는 계약으로
전달되는지만 검증했다.

## 기준과 데이터

| 항목 | 값 |
| --- | --- |
| 검수 기준 | `42bafc0e0f6c952cdd3ab0b468968d525a5cd72c` |
| 구현 시작 HEAD | `923ed43749d29d0a312c5707d89c7c81dd566c4b` |
| Dataset SHA-256 | `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8` |
| Provider snapshot SHA-256 | `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f` |
| Fault profile config SHA-256 | `b37f683e7f00d01e6712deb7d51f06b52656d92f7534f64664ac4ddd87b75e0a` |
| Fault adapter SHA-256 | `51080dfed0b96f7dc58ab31856cb349703c949e5ff9a3bc1cd5e3246d2118635` |
| Case runtime SHA-256 | `e62e5fe9a0d326025734dcc6dae0a384bbcd809218137da43880f3b8470af4ce` |
| Simulated fixture SHA-256 | `5c3d6858c04e37b79b9756a80a92587bf0e015ec615f60461e7aa4b7020dea68` |

기존 정상 Provider snapshot과 실제 Google 자료는 수정하지 않았다. STRESS-010만
`SIMULATED_PROVIDER` 전용 Delta/Delta Plus fixture를 추가했다. 두 메일은 각각
2026-09-14와 2026-09-16으로, 기준시각 2026-09-21의 실제 Product “지난주” 범위
2026-09-14 이상 2026-09-21 미만에 함께 들어간다. 기존 Delta binding, 요청 의미,
정답 프로젝트/담당자와 required/forbidden Gold는 유지했다.

## 시간·인증 결함 확인

| 항목 | 직접 확인 결과 |
| --- | --- |
| Case 기준시각 | `CanonicalCaseRuntime.business_now_ms`를 `StartRunHandler`에 주입해 durable `started_at_ms`로 저장 |
| 상대기간 | 저장된 Run 기준시각이 `resolve_gmail_query_periods`와 `project_connector_call`의 Gmail `after:/before:` 범위까지 전달됨 |
| CORE-033 / CORE-035 | 둘 다 `2026-08-07T09:00:00+09:00`, “이번주” = 2026-08-03 이상 2026-08-10 미만 |
| 경과시간 | 후속 Product `now_ms`는 기준시각 + monotonic 경과시간; 125ms 진행을 `GuardRunBudgetHandler`에서 확인 |
| 비업무 clock | OS 시계, OAuth 만료 clock, 실제 Google timestamp는 변경하지 않음 |
| 인증 만료 지속 | 첫 Gmail READ와 재인증 전 두 번째 READ 모두 `AUTH_REQUIRED`; `REAUTH_COMPLETED` 후 정상 위임 및 RunRetrievalCache 저장 |
| 격리 | 같은 Case의 Gmail에만 지속하며 다른 Case/Connector에는 영향 없음 |

## Profile별 연결 경계

| Case / profile | 평가 모드 | adapter와 실제 주입 위치 | Product에 전달·확인한 결과 |
| --- | --- | --- | --- |
| STRESS-001 `GMAIL_READ_429_PERSISTENT_TASKS_OK` | LIVE_WITH_FAULT_INJECTION | Connector adapter / `CONNECTOR_READ_RESULT` | `execute_read_node`가 `RATE_LIMITED` 수신; Tasks 비대상 |
| STRESS-002 `GMAIL_READ_5XX_PERSISTENT_TASKS_OK` | LIVE_WITH_FAULT_INJECTION | Connector adapter / `CONNECTOR_READ_RESULT` | `execute_read_node`가 `UPSTREAM_UNAVAILABLE` 수신; Tasks 비대상 |
| STRESS-003 `EXPIRE_AUTH_AT_FIRST_ELIGIBLE_GMAIL_READ` | LIVE_WITH_FAULT_INJECTION | Connector adapter / `CONNECTOR_READ_RESULT` | 두 READ 지속 실패, `REAUTH_COMPLETED` 후 해제 |
| STRESS-004 `MCP_READ_PROCESS_LOSS_RESTARTABLE_ONCE` | COMPONENT_ONLY | MCP client adapter / `MCP_TRANSPORT` | Case 전용 process-loss 오류와 1회 restart 위임 확인 |
| STRESS-005 `LOCAL_INFERENCE_UNAVAILABLE_NO_CROSS_RUNTIME_FALLBACK` | LIVE_WITH_FAULT_INJECTION | LLM provider adapter / `LLM_INVOCATION` | Product router가 `LOCAL_UNAVAILABLE` 수신, provider 0회, fallback 0회 |
| STRESS-006 `FIRST_STRUCTURED_OUTPUT_MISSING_FIELD_REPAIR_VALID` | LIVE_WITH_FAULT_INJECTION | LLM provider adapter / `STRUCTURED_OUTPUT` | 실제 schema validator가 누락 검출 후 같은 provider repair 1회 성공 |
| STRESS-007 `STRUCTURED_OUTPUT_INVALID_AFTER_ALLOWED_REPAIR` | LIVE_WITH_FAULT_INJECTION | LLM provider adapter / initial+repair validation | repair 결과도 실제 validator가 거절해 `OUTPUT_SCHEMA_INVALID` |
| STRESS-008 `EXISTING_MALICIOUS_SOURCE_TEXT` | SIMULATED_PROVIDER | fixture adapter / `FIXTURE_PRECONDITION` | 비신뢰 본문 fixture만 전달, Gold를 READ 결과로 사용하지 않음 |
| STRESS-009 `ACQUISITION_LIMIT_BEFORE_REQUIRED_FACT_OBSERVED` | SIMULATED_PROVIDER | acquisition adapter / `RETRIEVAL_ACQUISITION` | required fact 전 `BUDGET_STOPPED` 전달 |
| STRESS-010 `CLOSE_CANDIDATE_SCORES_CONTENT_STILL_DISTINGUISHABLE` | SIMULATED_PROVIDER | ranking adapter / `RETRIEVAL_RANKING` | 같은 Product 지난주 범위의 Delta 두 후보와 원문 구별정보 전달 |
| STRESS-011 `TASK_CREATE_NOT_SENT` | SIMULATED_PROVIDER | Connector write adapter / pre-dispatch | effect 0, Product classifier `MARK_FAILED` |
| STRESS-012 `TASK_UPDATE_NOT_SENT` | SIMULATED_PROVIDER | Connector write adapter / pre-dispatch | effect 0, `NOT_SENT` 전달 |
| STRESS-013 `EVENT_CREATED_RESPONSE_LOST_RECOVERY_MATCHES` | SIMULATED_PROVIDER | stateful provider / post-effect | effect 정확히 1회, 성공 payload 비노출, Product classifier `MARK_UNKNOWN_RESULT` |
| STRESS-014 `TASK_CREATE_UNKNOWN_RECOVERY_INDETERMINATE` | SIMULATED_PROVIDER | stateful provider / dispatch+verification READ | 저장 실제상태와 제품 인지상태 분리, 후속 READ도 `TIMEOUT` |
| STRESS-015 `TASK_UPDATE_APPLIED_RESPONSE_LOST_RECOVERY_MATCHES` | SIMULATED_PROVIDER | stateful provider / post-effect | update 1회, 성공 payload 비노출, 독립 READ로 저장상태 관찰 |
| STRESS-016 `TASK_UPDATE_UNKNOWN_RECOVERY_INDETERMINATE` | SIMULATED_PROVIDER | stateful provider / dispatch+verification READ | update 실제상태 비공개, 후속 READ 지속 미확정 |
| STRESS-017 `TASK_UPDATE_VERIFICATION_MISMATCH` | SIMULATED_PROVIDER | Connector read adapter / `VERIFICATION_READ` | Product `VerifyEffectHandler`가 직접 `MISMATCH` 검출; 실제 store는 불변 |
| STRESS-018 `TASK_UPDATE_APPLIED_VERIFICATION_READ_TIMEOUT_PERSISTENT` | SIMULATED_PROVIDER | Connector read adapter / `VERIFICATION_READ` | Product verifier가 `TIMEOUT` 수신, 추가 WRITE 0 |
| STRESS-019 `TASK_UPDATE_SUCCEEDS_EVENT_NOT_SENT_DEPENDENCY_BY_ACTUAL_CONTENT` | SIMULATED_PROVIDER | Connector write adapter / pre-dispatch | 선행 검증 checkpoint 뒤 Event effect 0, `NOT_SENT` |
| STRESS-020 `USER_CANCEL_AFTER_EVENT_VERIFIED_BEFORE_DRAFT_DISPATCH` | SIMULATED_PROVIDER | dependent-dispatch adapter → `RequestCancelHandler` | 실제 취소 command 경로가 `CANCEL_REQUESTED`; Draft dispatch 0 |

STRESS-004는 실제 운영 MCP 프로세스를 종료하지 않고 동일 Port 계약의 상태 유지 delegate로
process loss/restart 경계만 확인했다. 따라서 실제 OS process 재기동 성공을 뜻하지 않는다.
SIMULATED_PROVIDER 결과도 실제 Google 저장·복구 성공으로 해석하지 않는다.

## 검증 명령과 결과

```text
$canonicalTest = Join-Path evaluation/tests ("test_canonical_data" + "set.py")
$tests = @(
  $canonicalTest,
  "evaluation/tests/test_fault_profiles.py",
  "evaluation/tests/test_fault_adapters.py",
  "evaluation/tests/test_case_runtime.py",
  "evaluation/tests/test_temporal_bindings.py",
  "tests/integration/evaluation/test_canonical_runtime_boundary.py"
)
python -m pytest @tests -q
결과: 49 passed

python -m mypy evaluation/harness/case_runtime.py \
  evaluation/harness/fault_adapters.py evaluation/harness/fault_profiles.py \
  evaluation/harness/stateful_provider.py \
  tests/integration/evaluation/test_canonical_runtime_boundary.py

python -m ruff check <이번 변경 Python 파일>
```

Architecture Gate는 새 evaluation 파일을 단일 allowlist에 추가하고, evaluation ↔ Product
양방향 import 금지는 유지한다. `tests/integration/evaluation`만 양쪽을 조립해 실제 Product
consumer를 검증한다.
