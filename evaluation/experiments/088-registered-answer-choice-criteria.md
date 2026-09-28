# 088 — 실제 등록된 추론 router와 compose 후보의 연결

## 원인·단일 연결 가설

084의 mode-first 후보는 고정된 lookup/완료 상태/정리 반례 6회에서 의미를 보존했다.
085의 무조건 적용은 미지원 Calendar 시각을 바꿔 기각했고, 087은 fact catalog가 없는
입력에 원 Product wire를 보존했다. 그러나 086 compiled replay는 주입 callable이므로
실제 Prompt 등록·budget·schema repair를 통과한 근거가 아니다.

이번은 새로운 의미 규칙 실험이 아니라 이 후보를 실제 Product inference router에
결속하는 하나의 연결 후보다. active Prompt/State/Node는 바꾸지 않는다.
평가 전용 Planning subclass, invocation-local EVALUATION resolver와 provider decorator를
사용한다. Product가 scripts를 import하거나 registry allowlist를 우회하지 않는다.

`Planning → current-Run store → registered assembly → actual router/Ollama → schema
validation/repair → deterministic materializer → compose validation → Answer/Supervisor projection`
을 검증한다. 실제 Main Graph, public Product API, DB terminal commit, Provider 조회,
Canonical92 또는 출시 성공과 구분한다. 실제 Supervisor projection은 사용하되
terminal intent 생성·terminal commit·Main route 실행은 이번 gate에서 실행하지 않는다.
086의 terminal 연결 근거를 새로운 실행 결과로 합산하지 않는다.

## 보존할 계약

- 요청과 승인 outline/Evidence는 역사 입력 그대로이며 snapshot은 private closure에만 둔다.
- FIRST의 catalog가 있으면 기존 083 ROLE와 084 mode-first union을 사용한다. 없으면 원
  PromptRef/schema/wire를 delegate한다. Task라는 이유로 FACT 모드를 강제하지 않는다.
- 기존 `COMPOSE_ANSWER_PROSE_INVALID` revision은 원 Product 경로를 사용한다.
- 다른 Run·version/hash 불일치 snapshot을 FACT 값으로 쓰지 않는다. Product가 snapshot
  누락을 기존 LLM 경로로 넘기는 현재 동작과 평가의 exact snapshot 선행조건을 구별한다.
- 실제 router의 hardware/model selection, dispatch budget, circuit, schema repair와 관측
  경계를 보존한다. 단위 테스트의 fake wire/가상 hardware는 실제 모델 trial과 구분한다.
- 실제 `assemble_prompt(EVALUATION)`는 Product 공통 문맥을 붙인다. 따라서 087의 수동
  system 문자열과 다르며 기존 084의 점수·응답을 새로운 연결 실행의 PASS로 승계하지 않는다.
- trace의 실제 PromptRef와 FIRST/repair ref를 보존한다. union을 answer-draft-v2로 위장하지 않는다.

## 사전 고정 검증 범위·예산

모델 실행 전 직접 반례에서 공통 schema validator의 실패 경로 과대보고를 확인했다.
유일한 declared oneOf branch의 answer 타입 오류에 aggregate `$`까지 붙어 정상인
evidence_refs 배열 삭제를 허용했다(21 PASS/1 RED). 이 기존 repair 계약 결함은 별도
최소 Product 수정으로 branch의 실제 오류만 보고하게 고친다. JSON 유효값·Prompt·
budget은 바꾸지 않는다. 본 후보와 비교 기준은 이 수정 이후 같은 Product SHA를 사용하고,
이 수정 전의 RED 및 이후 직접 회귀 결과를 별도로 보존한다. 신규 모델 trial은 아직0이다.

1. 먼저 모델 없는 직접 tests와 fake-wire compiled gate. FIRST/repair accounting, budget
   소진 0-dispatch, 등록/input 변조 거절, capability-none baseline 보존, FACT/PROSE 전달.
2. 통과 후 actual 9B를 한 번에 하나만 실행한다. 입력 4개 × 사전 고정 2회 = **8 FIRST**.
   순서는 CORE005 → completed → reformulation → Calendar, 두 번. 추가 rerun은 없다.
3. 각 trial에서 기존 Product bounded repair는 허용하되 별도 dispatch로 센다. 실험 상한은
   trial당 최대4 actual dispatch, timeout180초/호출, 전체1200초 이후 다음 dispatch를
   차단한다(진행 중 호출의 강제 취소 아님). Product 기본 Run 예산은 유지한다. 최초 결과와 repair 후
   결과를 분리한다. 상한 도달·예외도 보존하고 성공으로 대체하지 않는다.
   actual router의 RunBudget guard와 dispatch ledger를 확인하되, 이 component는
   durable DB budget CAS·schedule/claim/resume을 실행하지 않는다.
4. 모델은 qwen3.5:9b의 기존 sealed digest, seed20260923, num_ctx16384, think=false.
   temperature/presence override를 추가하지 않는다. 실제 runtime 설정과 wire를 기록한다.
5. 전송 input/schema/property order/hash와 SHA·Product/후보/manifest·fixture/역사 hash를
   실행 전에 봉인한다. 실행 중 변경하지 않는다. 상세 raw는 evaluation/results/088-*에만 둔다.

## 입력과 의미 기준

| 입력 | 출처 | 유지할 의미 |
| --- | --- | --- |
| CORE005 lookup | 067 실제 pre-Planning checkpoint, 084 입력 | 선택 Task의 미완료 상태와 date-only 기한. 요청의 제한 보존 |
| completed lookup | 084 synthetic control | 완료 상태와 메모; 없는 실행·추가 사실 주장 없음 |
| reformulation | 084 synthetic counterexample | 계정 발급·장비 수령 확인 항목을 정리하고 원문 문장 인용 금지 보존 |
| Calendar location | 065 synthetic input | 오전10~11시(2026-08-18 Asia/Seoul), 한빛회의실. 미지원 candidate는 기존 경로 |

mode·문장 모양·bullet 수를 정답으로 강제하지 않는다. 기존 기준의 의미 채점으로
PASS/PARTIAL/FAIL을 별도 검수한다. 구조 통과만으로 의미 PASS라 하지 않는다.
같은 seed의 2회는 환경 내 반복성 확인이며 일반화 또는 다양한 seed 안정성 증명이 아니다.

현재 Product와의 새 전체 비교가 아니라 기존 actual 결과의 역사 비교 및 새 연결 확인이다.
raw hash가 같은 역사 응답을 참고하되 SHA/assembly 차이를 명시한다. 085 Calendar FAIL을
지우지 않으며, 새 Calendar 결과가 실패하면 그대로 회귀/변동을 구분해 조사한다.

## 판단·다음 선택

등록/budget/repair/fact authority 손실이면 그 경계를 수정하고 모델을 추가 호출하지 않는다.
공통 assembly 적용 뒤 의미가 회귀하면 같은 Prompt 문구를 반복 강화하지 않고 첫 출력과
입력 차이를 분석한다. 연결과 의미가 모두 유지되면 실제 upstream/Main Graph 후보로 넓힌다.
어느 경우도 자동 Product activation, 전체 안정화 완료, 승인·Provider WRITE를 허용하지 않는다.

Provider READ/WRITE/SEND 0, 승인0, rerun-to-pass0. Canonical92/Gold/실제 데이터 변경0.
