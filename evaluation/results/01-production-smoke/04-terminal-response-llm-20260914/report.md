# 실행 결과 설명 LLM 전환 보고서

## 결론

현재 최신 브랜치 기준으로 `COMPLETE_WRITE`의 안전하게 종료 가능한 `SUCCESS`/`PARTIAL` 결과만 기존 Runtime의 LLM이 설명하도록 연결했다. 업무 성공 여부와 외부 효과의 기준은 기존 Action → Attempt → Verification 및 종료 트랜잭션에 그대로 남아 있다. Planning 답변, 확인/승인 Preview, 취소, Recovery, 미검증·불확정 실행 경로는 기존 결정적 처리를 유지한다.

- 시작 SHA: `923ed43749d29d0a312c5707d89c7c81dd566c4b`
- 제품 구현 SHA: `94db77e75314255d2193a8a07a219af4019061fa`
- 구현 커밋: `ca7757ec`, `94db77e7`
- 원격 최신 통합: `f78e404a`를 merge하고 naming Gate 수정 `b0f2ff73` 적용
- 새 semantic Agent / Main State / lifecycle status: 없음
- 새 Graph Node: 없음
- Graph Edge: `terminal_commit` 뒤 기존 제어 상태에 따른 conditional route로 최소 보완
- Prompt: `run.compose_terminal_response` 1개 신규 등록, Release activation은 하지 않음
- Product Provider WRITE/SEND: 0

## 구현한 경계

`TerminalResponseInputV1`은 사용자 요청, 기존 결과 종류, durable 실행 결과, 검증된 표시 필드, 증명된 효과 관측, 필요한 한계만 받는다. 계획 인자는 실제값으로 승격하지 않으며 원시 Provider 응답·Approval snapshot·GraphState 전체는 전달하지 않는다.

응답 LLM은 기존 `StructuredInferencePort`, Runtime Router, Budget, consent, trace 및 Schema Repair 경계를 재사용한다. 정상 호출은 1회, repair를 포함한 Provider dispatch 상한은 2회다. 이 Prompt 슬롯은 Local 실패 시 API로 자동 전환하지 않는다. 실패·timeout·예산·동의 철회에는 기존 I/O-free formatter로 복귀하며 이미 성공한 WRITE의 결과 종류는 바꾸지 않는다.

LLM 대기 중 Version 충돌이 나면 `applied=false`를 명시적으로 처리한다. 이미 종료된 Run은 저장된 최종 Message를 재사용하고, 취소·Recovery는 해당 경로로 이동하며, 최신 사실로 한 번만 결정적 intent를 재생성할 수 있다. 낡은 문장의 expected version만 바꾸어 재사용하지 않는다.

## 실제 LLM 8 Case × 2 Trial

고정 binding은 [runtime-binding.json](runtime-binding.json)에 기록했다. 실제 모델은 `qwen3.5:9b`, digest `6488c96f…93ea7`, temperature `0.2`, seed `1729`이며 총 16회 모두 LOCAL_GPU LLM 1 dispatch로 끝났다. repair 0, fallback 0, rerun-to-pass 0이다.

| 항목 | 결과 |
|---|---:|
| 실제 생성문 의미 PASS | 14/16 |
| 필수 한계 누락 | 2/16 — TR-03 두 Trial |
| 현재 코드의 최종 projection 의미 PASS | 16/16 |
| 표현 경고 | 2/16 — TR-06의 불필요한 일반 재시도 권고 |
| Provider dispatch | 16 |
| 입력 / 출력 Token | 19,816 / 748 |
| 응답 단계 평균 / 중앙값 | 2,985.8 ms / 2,069.5 ms |
| 응답 단계 최대값 | 17,796 ms — 첫 warm-up 포함 |

TR-03에서 모델이 SEND 완료는 정확히 설명했지만 “수신자의 실제 수신·열람 여부는 확인하지 않았다”는 입력 한계를 두 번 모두 누락했다. 최초 실패 owner는 자유문 생성 결과였다. 한계가 최종 사용자 문장에 없으면 기존 typed `limitations`를 결정적으로 덧붙이도록 수정하고 LLM·fallback 양쪽 단위 테스트로 고정했다. 실패 Trial을 재실행하지 않았으므로 최종 SHA의 실제 Provider 재검증과 Release activation은 `PENDING`이다.

각 안전 입력 projection, 최종 사용자 문장과 사람 판정은 [response-cases.jsonl](response-cases.jsonl), Trial별 수치는 [metrics.csv](metrics.csv)에 있다. 원시 Prompt, hidden reasoning, credential, 전체 GraphState는 포함하지 않았다.

## 최종 6개 Production Smoke — 동일 SHA, 각 1회

코드 변경 없이 `94db77e7`에서 실행했다. safe LangSmith tracing만 활성화했고 자동 tracing은 사용하지 않았다. 승인 클릭과 실행 시도는 모두 0이어서 Provider WRITE/SEND도 0이다. 이 Smoke들은 WRITE를 승인·실행하지 않았으므로 신규 terminal-response LLM 호출은 0이다.

| Case | Run | 제품 상태 | 의미 판정 | 결과 |
|---|---|---|---|---|
| 대상 없는 Calendar + same-Run 확인 | `c87dd90c…12695` | `COMPLETED/SUCCESS` | 근거 `10:00~11:00`의 종료를 `오후 11시`로 표현 | FAIL |
| Selected Event | `df1bdd5d…6b509` | `COMPLETED/SUCCESS` | Atlas 인쇄소 슬롯 `14:00~15:00` 정확 | PASS |
| Atlas Draft | `1618761c…4cd3` | `WAITING_APPROVAL` | Task 2개와 Calendar 근거, 정확한 CREATE Preview | PASS |
| Juniper EXHAUSTIVE | `82c9719f…49ee` | `COMPLETED/SUCCESS` | 26개 제목 전체 반환 | PASS |
| Atlas q19 | `f37e868c…f3a2` | `COMPLETED/SUCCESS` | 8월 19일 오전, 담당 지민 | PASS |
| Quartz Draft | `c7da41b4…6ec4` | `BLOCKED` | Planning 전 `REQUEST_STATUS_PROVENANCE_MISMATCH` | FAIL |

최종 집계는 4/6 PASS다. Calendar의 최초 관측 divergence는 Planning ANSWER가 evidence의 `11:00`을 `오후 11시`로 표현한 지점이다. Quartz는 Request Understanding의 status provenance 검증에서 차단되어 Action/Preview가 생성되지 않았다. 두 실패 모두 신규 `COMPLETE_WRITE` 응답 경계에 도달하기 전의 기존 upstream 실패이며 이번 범위에서 제품 로직을 함께 튜닝하지 않았다.

## 검증

- 수정 전 직접 영향 기준선: 217 passed
- 최종 직접·upstream 단위/계약 묶음: 1,098 passed
- 신규 직접 단위 묶음: 70 passed
- Architecture: 371 passed
- Component Main Graph: 9 passed
- Production Graph E2E 선택 묶음: 19 passed, 46 deselected
- 한계 보존 수정 후 집중 회귀: 35 passed, 61 deselected
- Ruff: PASS
- mypy: PASS
- `git diff --check`: PASS

원격 최신 커밋 통합 후에는 이번 직접 단위·Component·전체 Architecture 묶음이 450 passed, 새 evaluation runtime 경계 묶음이 53 passed였다. 원격 커밋이 추가한 integration 테스트 11개의 이름만 canonical grammar에 맞췄고 assertion과 제품 코드는 변경하지 않았다.

Architecture 최초 실행에서 신규 테스트 이름 16개가 저장소 naming gate에 걸렸고 테스트 이름만 규칙에 맞게 고친 뒤 371개가 통과했다. 제품 동작 실패를 숨기기 위한 검사 완화는 없었다. 상세 명령과 범위는 [tests.txt](tests.txt)에 기록했다.

## 상태

- DONE: terminal WRITE 결과용 typed projection, LLM 조립, deterministic fallback, 필수 한계 보존, applied=false reconciliation, Prompt/Runtime/문서 연결
- TESTED: 단위·계약·Architecture·Component·controlled Production Graph E2E, 실제 LOCAL_GPU 16 Trial, 최종 safe 6 Smoke 단발
- PENDING: 최종 SHA에서 TR-03 실제 Provider 재검증, Prompt Release activation, qwen3.5:9b 외 모델 검증
- 기존 회귀: Calendar 시간 표현, Quartz provenance mismatch
- 미수행: 실제 승인, Live WRITE/SEND, DELETE, 전체 Provider write E2E
