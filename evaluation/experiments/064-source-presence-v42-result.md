# 064 v42 — Source presence penalty 비교: REJECT

## 조건과 실제 실행

- 실행 HEAD `e9a09524f398b6e6f34b841fbdb239ed930fc32f`. 사전 기준은 `064-source-presence-v42-criteria.md`, runtime 근거는 `064-source-sampler-runtime-audit.md`다.
- Core005/009/017/049/059를 baseline와 후보 각각 1회, **신규 10회** 실행했다. 과거 5개 raw는 입력 출처/참고일 뿐 점수와 비용에 합산하지 않았다. baseline 재사용 계획은 첫 실행 전에 철회했다.
- 원래 Product Source Prompt 1.1.0, input/Schema/top-level format을 보존했다. v41 축소 Prompt는 사용하지 않았다. 후보의 변경은 `options.presence_penalty=0.0` 한 키다. baseline은 미전송이며 실제 모델 기본값 1.5가 소비됐다.
- qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, Ollama 0.34.0 / llama-server b10760, Source temperature 0.05, seed 20260923, ctx 16384, think=false, timeout 180초. 각 Case의 원 reference time/fault 및 Dataset/Fixture/input hash는 plan에 결속했다.
- 순서는 005 기본→0, 009 0→기본, 017 기본→0, 049 0→기본, 059 기본→0. 동시 모델 1, 실행 중 테스트/파일 편집 0. repair/retry/codec/Graph/업무 Provider 0.

## 결과: 구조 통과와 의미 통과를 분리

양쪽 모두 **5/5 strict VALIDATED**이며 10개 모두 첫 JSON과 validated 값이 같다. normalizer가 의미를 바꾼 것이 아니라 **Source FIRST에서 최초 차이**가 생겼다. 모든 Work binding은 `work-1`로 유지됐지만 다중 Work 검증은 아니다.

| Case | 신규 baseline | presence=0 후보 | Source-only 판정 |
| --- | --- | --- | --- |
| 005 선택 Task 상태·기한 | TASK/SINGULAR, 상태·기한 포함. 전체 fact inventory를 복사한 과잉 명세도 관측 | 출력 동일 | PASS → PASS |
| 009 메일·Task 기준 진행 상황 | 메일 이력은 있으나 TASK가 NOT_REQUIRED | 메일 내용과 Task notes/status/due를 실제 복구. TaskList identity/title 추가 | FAIL → PASS |
| 017 Task·Calendar로 새 Draft 준비 | 필요한 Task/Event 사실 유지, 새 Draft를 기존 Draft 조회 요구로도 오인 | 기존 오인 유지. Thread/Message/Attachment/Freebusy까지 필수 Source로 추가 | PARTIAL → PARTIAL, 과선정 악화 |
| 049 메일·Task·Calendar 확인 후 복수 CREATE | 명시한 세 Source의 사실 유지, 기존 Draft 등 과잉 요구 | 기존 오류 유지, Attachment/Freebusy 추가 | PARTIAL → PARTIAL, 과선정 악화 |
| 059 메일에 답장 | Thread/메시지 이력 보존 | **10개 Resource 모두 SOURCE_REQUIRED**. Task/Calendar/GitHub 등 무관한 Source를 필수화 | PASS → PARTIAL, 기존 성공 회귀 |

**2 PASS / 2 PARTIAL / 1 FAIL → 2 PASS / 3 PARTIAL / 0 FAIL**, 그러나 **REJECT**다. 009의 필요한 Task 근거는 회복했지만 기존 PASS 059가 회귀했고, 017/049도 같은 PARTIAL 구간 안에서 필수 조회 범위가 더 넓어졌다. FAIL 숫자 감소를 품질 채택 근거로 쓰지 않는다.

009의 TaskList를 개수만으로 과선정이라 감점했던 독립 초기 검수는 재대조 후 철회했다. 고정 기준은 정확한 Resource 개수를 Gold로 강제하지 않으며 정상 parent/container 경로를 허용한다. 필요한 메일·Task 사실과 범위/Work가 보존됐고 TaskList가 불필요하다고 확정할 근거가 없어 PASS로 판정했다. 보조 조회 비용 관측은 남긴다. 이는 실제 Tool Route/Provider 실행 성공 판정이 아니다.

원 raw의 UNREVIEWED 및 business_success=NOT_EVALUATED를 덮어쓰지 않았다. 이 점수는 Source owner에 한정되며 RU→Tool Route, Canonical92, 최종 업무 성공률이 아니다. 실제 무관한 Provider 조회나 WRITE가 실행됐다고 주장하지 않는다.

## 실제 sampler와 비용

신규 dispatch UTC 12:18:05.320–12:19:41.747, 서버 완료 KST 21:18:19–21:19:55의 10개 로그를 순서/토큰/시각으로 대조했다. presence는 `1.5,0,0,1.5,1.5,0,0,1.5,1.5,0`으로 실제 소비됐다. 다른 sampling은 temp 0.05/top_k 20/top_p 0.95/repeat 1/frequency 0으로 같다. 이 대조는 client/server의 암호학적 task-ID 결속은 아니다.

| arm | 신규 calls | 입력 token | 출력 token | 보고 latency 합계 | wall 합계 | load 합계 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline 기본값 | 5 | 20,442 | 1,119 | 51,211ms | 51,404ms | 6,424ms |
| presence=0 | 5 | 20,442 | 1,660 | 58,292ms | 58,528ms | 20ms |

후보 출력 +541 token, 보고 latency +7,081ms. usage 누락 0. 첫 baseline 005의 cold load가 6,378ms이며 각 pair 두 번째 호출에는 prompt cache 효과가 있다. 작고 순서 의존적인 표본을 일반 속도 효과/p95/반복 안정성으로 해석하지 않는다. 신규 baseline 5개가 역사 raw와 같은 내용을 반환했어도 역사 Trial을 이번 반복 수에 더하지 않는다.

자원 snapshot: 시작 RAM 여유 19.92/31.71GiB, GPU 0/8,188MiB·45°C. 실행 중 관측 VRAM 6,385MiB·42%·64°C. 종료 RAM 여유 17.23GiB, VRAM 6,385MiB·0%·52°C. 순간 관측이며 전체 peak 측정은 아니다.

## 판단과 다음 경계

Product sampling/Prompt/Schema/State/Node/activation 변경 0, Provider WRITE/SEND 0. presence penalty가 모든 Source 실패의 원인이라는 가설은 지지되지 않았다. penalty 수치를 더 탐색하거나 v41 축소 지시에 얹지 않는다.

Source FIRST가 필요 사실 선택·Source 역할·범위를 함께 출력하는 경계를 기존 실패 후보와 다시 비교한다. 동일 판정을 반복 복사한 모양만으로 decoder 원인을 확정하지 않는다. 이전 sparse/key-map/family/needs/requirements 후보의 실패와 반례를 먼저 재사용하고, 근거가 다른 최소 책임/표현 후보만 선택한다. no-source, 다중 Work, UPDATE/DELETE, confirmation/revision, 실제 upstream/후속 Retrieval·Planning은 이번에 미검증이다.

## 재현 근거

- plan: `evaluation/results/064-source-presence-v42-plan/preregistered-plan.json`; object SHA256 `f069342b5d9473de48f4a907a4e9653fdabcbe39bfeca9734b149ca9a7c20307`, bytes SHA256 `24ea7f3f7629190bacea15fa75ca572ca19b243c6bc338f23b10842f7f4fe3ec`.
- raw: `evaluation/results/064-source-presence-v42-t1/raw.json`; SHA256 `f5b40bd0d4e36e0f7d9138d00d9d0bdd45cbebc5cd954a110ced1d3a50c6ee52`.
- `/api/version` response object SHA256 `6704625a5b8470777a49232fcb0aaece8f2a2865d3e196cf881d7840d443c541`.
- Dataset SHA256 `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`; Fixture SHA256 `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
- 로컬 server.log snapshot UTC `2026-09-28T12:20:50.975841Z`, 3,786,333 bytes, SHA256 `838980f37994191a086d32fdf37563bfa44461ab3a9d1697507ec24389ea9846`; parameter line 39048/39079/39111/39148/39182/39220/39259/39299/39339/39375. 전체 로그나 원문/비밀값은 게시하지 않는다.
- 상세 raw는 기존 ignore 정책에 따라 로컬 보존한다. 추적된 이 문서는 원격 검토용 비민감 요약이다.
