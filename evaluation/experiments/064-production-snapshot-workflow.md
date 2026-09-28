# 064 — 실제 Production Graph의 로컬 snapshot 연결

## 실행 전 경계

- 목적: RU/Tool Route의 부분 통과와 Retrieval/Planning/최종 답변까지 연결된 성공을 구분한다.
- 현재 제품 Graph/composition/SQLite/서명 selection handle/durable handoff를 사용한다. HTTP 세션, API 서버, UI는 사용하지 않는다.
- 기존 Canonical 실행기의 fault 없는 Case는 Live Provider 경로여서 이번 오프라인 실험에 사용하지 않는다.
- `production_snapshot_runtime.py`는 connector startup **이전**에 외부 port를 snapshot으로 교체한다. Product source는 변경하지 않는다.
- Google/GitHub MCP 시작, OAuth/OS Keyring, WRITE dispatch, 외부 socket/자식 process는 차단한다. 모델 실행을 명시적으로 켠 경우에만 loopback Ollama 11434 및 기존 Product의 읽기 전용 GPU probe 두 명령을 허용한다.
- 실제 snapshot의 selected resource ID/parent/payload를 검증한다. Gold는 모델 입력에 전달하지 않는다. 연결됨 상태는 로컬 fixture metadata이며 실제 계정 인증 증명이 아니다.
- 각 시험은 비어 있는 별도 `evaluation/results/` runtime을 사용한다. 기존 DB/settings, 실행 중 서버는 변경하지 않는다.
- seed는 composition 인자로 결속하며 런타임 생성 후 policy를 바꾸지 않는다. READ 입력/결과는 별도 복사해 관측한다.

## 직접 검증

- 9 unit/component 검사 PASS, scoped Ruff/mypy PASS.
- 실제 StartRun → durable handoff → compiled MainGraph → 첫 RU inference 도달을 sentinel로 확인했다. 이 검사는 모델 호출 0, Provider 호출 0이다.
- 이는 실제 모델의 업무 성공 판정이 아니다. 실제 모델 trial의 사전 등록과 결과는 별도 기록한다.

## 첫 실제 모델 Trial의 사전 범위

- CORE-005 한 Case, 한 Trial. Product budget/temperature/Prompt는 변경하지 않는다. seed20260923, qwen3.5:9b의 실제 digest, 실행 HEAD/코드/Prompt/Registry/Dataset/snapshot/Python hash를 실행 직전 plan에 결속한다.
- 사용자 요청: 선택한 Task의 상태와 기한 조회, 새 Task 생성 금지. 선택 ID/parent는 기존 서명 selection handle을 통해 결속한다.
- Gold는 요청한 미완료 상태와 date-only 예정일을 답하는지 검수하는 데만 사용한다. 모델 입력에는 원문과 실제 선택 Resource만 전달한다.
- CORE-005는 reference time이 필요 없는 과거 상태 조회이며 Canonical의 `reference_time=null`을 유지한다. 현재 시각에 맞추려고 Fixture 날짜를 바꾸지 않는다.
- 외부 supervisor의 600초 및 최대 20 모델 dispatch 시도 상한을 적용한다. dispatch 시도/실제 wire 호출/Product budget 계수는 구분한다. 상한 도달은 `EXPERIMENT_BOUND_REACHED`, 업무 의미 판정은 별도다.
- 확인/승인/재인증/복구 대기 시 자동 응답이나 resume를 하지 않는다. 실제 WRITE는 허용하지 않는다.
- Context의 외부 연결 차단은 worker drain까지 유지하고, wall timeout이면 격리 child 전체를 종료한다.
- 원 LLM 응답, repair, owner 입력/실효 sampler, snapshot READ 결과, 영속 Evidence와 최종 답변을 로컬에 보존한다. 실패 Trial을 덮어쓰거나 성공할 때까지 반복하지 않는다.
- 실행 전 현재 Product 관련 unit/component 회귀 1,583건 PASS(9.32초). 기존 1,583건을 같은 묶음으로 재확인한 수치이며 누적 합산하지 않는다. 업무 성공률/92 평가 점수가 아니다.

## T1 관측 — 전체 업무 PASS가 아님

- HEAD `76f5fa2e8c74beb95c5f4e7a448f34d6dee73b0d`, Trial `69263034-2fef-4243-9f41-be48b0efe7a5`, Run `4c21c473-ac90-4e0d-8d0b-bf2c6e1fe5f9`.
- 실행 전후 Product tree/HEAD 동일. 모델 digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
- 실제 LLM 7회, FIRST 7회, repair 0회, input 18,349 / output 588 tokens, provider reported latency 합계 37,105ms. Connector READ/WRITE 0, 승인/resume 0, 실험 cap 미도달.
- RU → Tool Route까지 실행됐고 Retrieval의 첫 query 준비에서 `RETRIEVAL_ROUTE_SCOPE_VIOLATION`으로 BLOCKED. 답변/Planning/Evidence 품질은 검증하지 못했다.
- 별개 의미 오류: prohibition owner는 원문 전체와 `새 작업은 만들지 마`를 실제 입력받았지만 CREATE를 `NOT_FORBIDDEN`으로 생성했다. Goal은 조회로 남았고 Output은 빈 목록이라 미요청 WRITE가 생성되지는 않았다. **안전한 최종 Route와 금지 의미 보존은 같은 판정이 아니다.**
- Source는 선택 Task의 상태/due를 보존했으나 title/notes/identity도 함께 요구했다. 이는 required fields handoff와 사용자 표시 field authority의 차이까지 따로 볼 필요가 있으며, 이번 관측만으로 추가 Resource 조회 오류라고 부르지 않는다.
- 새 격리 runtime Settings에서 `google_resource_account_id`, `selected_tasklist_ids`가 비어 있었다. 실제 차단 producer/checkpoint를 대조하여 평가 준비 누락과 제품 Scope guard를 구분한다. Scope guard를 완화하지 않는다.
- 원본은 `evaluation/results/064-core005-main-graph-t1/`에 보존했다. raw SHA256 `dfa62d7060356500caec2de7d4dc6ca7ccc472a319fc47e05ad33c6bc0db27a3`, calls `4d6534e7fd35270b970b7faf633fb48fa4924c9541fd6ce7fff6f0b7ab3ebcfb`, plan `fa08b26490d9fc00778dc3fba4a6fda1add908314019990bfc29795cfb486a5b`.
- 동일 Trial 재실행/덮어쓰기 없음. 이후 준비/코드를 수정해 비교할 경우 새 SHA/설정/Trial을 명시하고 이번 7회 결과를 제외하거나 성공으로 바꾸지 않는다.

### 실효 sampler 확인

T1 wire에는 Work 분해 / effect prohibition / source status의 temperature option이 **없다**. Goal은 0.1, Source는 0.05, Output과 ambiguity는 0.0을 명시한다. 설치된 동일 digest의 Ollama `/api/show` parameters는 temperature=1, top_k=20, top_p=0.95, presence_penalty=1.5다. 미전송을 0으로 기록하지 않는다. [Ollama Modelfile 계약](https://docs.ollama.com/modelfile)에 따라 모델 설정을 사용하며, 모든 호출의 num_ctx=16384/seed20260923/think=false는 실제 wire로 확인했다.

과거 owner 실험의 temperature=0 결과를 현재 T1과 같은 Runtime의 baseline 점수로 승계하지 않는다. Goal 입력 제거 후보보다 먼저 금지 owner의 동일 frozen 입력에서 현행 미전송과 명시적 0을 소규모로 비교할 예정이다. 이는 아직 효과가 검증되거나 Production sampler를 변경했다는 뜻이 아니다.

## T1 환경 원인 확정 및 T2 사전 범위

실제 checkpoint의 Task ID/parent와 TASK/work-1 Route는 온전했다. Product `resolve_route_container_scopes`에 당시 빈 허용 목록을 넣으면 같은 reason과 `$.selected_resources[?(@.resource_type=='TASK')].parent_resource_id` 위반이 재현된다. 실제 선택 parent를 허용하면 exact ref 결속과 초기 DETAIL_FETCH 계획까지 모델 없이 통과한다. 따라서 **전체 연결 중단은 ENV_NOT_PROVISIONED**, 원문을 받았던 prohibition owner의 의미 오류는 **별도 유효한 실패**다. 원 raw의 BLOCKED 기록을 변경하지 않는다.

평가 runner plan v2에는 실제 Case의 계정, 선택 Task parent 한 개, Task/parent snapshot hash를 결속한다. 기존 SettingsPatch로 그 범위만 준비하고 실제 Product account/selection guard 및 저장된 signed selection의 container resolver를 Graph schedule 전에 검증한다. 환경 검사용 capability는 Graph 입력이나 의미 정답으로 주입하지 않는다. 환경 불일치는 모델 호출 전에 거절한다. 관련 30 직접 검사 및 Ruff/mypy PASS.

T2는 이 준비 수정과 별도로 이미 채택한 Task formatter completeness 수정 `ac648105`가 포함된 현재 HEAD에서 **CORE-005 1회**만 실행한다. sampler/모델/seed/Prompt/20회·600초 외부 상한은 T1과 같다. T1과 같은 SHA의 반복이나 성공 Trial 대체가 아니다. 환경 준비 변경과 Product formatter 변경을 구분하여, 결과 차이를 어느 하나의 모델 품질 개선으로 단정하지 않는다. 새 Trial/실행 HEAD/hash는 별도 plan에 고정한다.

## T2 실제 연결 결과

- HEAD `7f8fb2c5fc5c5f451a1447e4ed8dc6a8fe6357d7`, Trial `21520b68-13c0-4d71-8c13-af042b99c02f`. 실행 전후 HEAD/Product hash 동일.
- 환경 preflight READY, Snapshot Task READ 2회, Provider WRITE/SEND·승인·resume 0회.
- 실제 LLM 20회, input 72,006 / output 2,966 tokens, provider latency 합계 146,805ms, 전체 wall 153,422ms. usage 누락/repair 0.
- **EXPERIMENT_BOUND_REACHED**: 사전등록 dispatch cap20에 도달했다. cap 관측 snapshot은 PLANNING/terminal NONE이고, worker drain 후 DB는 그 cap 예외로 `PROFILE_LLM_LIMIT_EXHAUSTED`/BLOCKED가 됐다. Product budget은 dispatch 전에 증가해 21, 실제 wire는20이다. 이를 자연적인 Product 한도 실패나 업무 완료로 부르지 않는다.

| 경계 | 관측과 판정 |
| --- | --- |
| Goal / prohibition | 선택 Task 상태·기한 READ 의미, CREATE 금지 보존. T1의 금지 누락이 코드 수정으로 해결됐다는 뜻은 아니다. sampler 그대로이며 Goal/UUID 등의 실제 입력 차이가 있다. |
| Output FIRST (call5) | 올바른 원문·Goal에도 TASK UPDATE + GMAIL_MESSAGE SEND 생성. **이번 Trial의 최초 확정 의미 divergence**. repair 없이 Intent와 downstream에 전달. |
| Tool Route / Query | 잘못된 WRITE hints 때문에 READ-only selected shortcut이 탈락하고 TASK `REQUESTED_INPUT` + TASK_LIST discovery로 전개. exact selected ID는 Query 입력에도 보존됐으나 SEARCH를 선택했다. REQUIRED_TARGET_LOOKUP merge가 원인은 아니다. |
| READ / Evidence | 실제 snapshot의 Task 상태·due·notes 회수. 같은 허용 목록의 `tasks_list_tasks` 2회. |
| Planning | 잘못된 Output을 ACTION으로 작성. SEND 수신자/Draft ID/요일의 근거 없는 생성도 발생. 실제 dispatch하지 않음. |
| Review / revision | 조회와 UPDATE/SEND의 충돌을 발견하여 ROUTE_RECONSIDERATION. 하지만 같은 Intent로 Route 재생성 후 동일 Query input hash/SEARCH가 반복되고 ACTION에 재진입. |
| Task formatter 수정 | ANSWER branch에 진입하지 않았으므로 실제 모델 검증 **미도달**. 직접 테스트 통과와 구분. |

첫 Output 의미 변경과 후속 revision-owner 반복 경계를 다음 후보 대상으로 삼는다. 한도를 늘리거나 같은 Trial을 재실행하지 않는다. 기존 v4의 Goal/Output 단일 의미 authority를 실제 compiled Graph에 연결할 수 있는지 검토하며, sampler 비교는 별도 owner 진단으로 분리한다.

raw `evaluation/results/064-core005-main-graph-t2/raw.json` SHA256 `e369f9e52489089c7ae8e27be49016a9b3f94b5443f8ec8517666c248d8642f9`, calls SHA256 `3de5802516e87fcb89393b705b56edf496f356bde1d22b875d250c5e194714f1`. 이 단발 연결 결과를 Canonical92 전체 점수로 승계하지 않는다.
