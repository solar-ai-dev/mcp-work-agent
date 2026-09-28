# 089 — 실제 upstream → Planning answer-choice → Main 종료 연결 사전 기준

## 목적과 선행 조건

088의 새 actual8 의미 검수와 공통 registry/routing 전달 정상 여부를 확인한 뒤에만
루트가 실행한다. fake8/8이나 과거 의미 점수만으로 승격하지 않는다. 이번 파일의 작성은
모델 실행이나 Product 채택이 아니다. 067 checkpoint·068 typed input·081~088 답변을
이번 Run에 주입하거나 기존 점수를 새 PASS로 승계하지 않는다.

새 Main Run의 사용자 원문 → RU → Tool Route → 실제 Retrieval → same-Run EvidenceStore
→ Planning → Supervisor → terminal을 기존 Product 경로로 통과시키는 최소 gate다.
Provider는 기존 snapshot adapter이며 외부 계정/Google/GitHub를 호출하지 않는다.

## 변경 경계

- `evaluate_production_snapshot_workflow.run_trial`의 admission/schedule/worker/drain,
  budget·선택 identity·권한·snapshot·WRITE 차단을 그대로 재사용한다.
- 새 평가 scope에서 `main.workflow.PlanningSubgraph` constructor만
  `AnswerChoicePlanningSubgraph(prompt_execution_scope=EVALUATION)`로 바꾼다.
  원 development composition은 그대로이며 다른 Agent의 scope·Prompt는 변경하지 않는다.
- 기존 `llm_provider_decorator`로 실제 Ollama leaf에 088의 invocation-local resolver를
  적용하고 기존 observer 바깥에서 PromptRef/input/schema/options/usage를 기록한다.
- 후보를 지원하지 않는 입력·기존 semantic repair·pending confirmation은 088 계약대로
  원 Product composer에 delegate한다. FACT 선택을 강제하지 않는다.
- `production_plan`은 재사용된 runner의 **기본 환경 계약**이다. 내부 `candidate=None`을
  실행 arm이 baseline이라는 뜻으로 쓰지 않는다. 상위 plan, active overlay, raw에
  `answer-choice-v088-main-v089`를 명시하고 실제 dispatch ref를 보존한다.
- 새 Product callback/State/Prompt/Node·Goal/Output 후보 중첩·checkpoint 수정은 없다.
  모델을 거치지 않고 기대 답변이나 선택 필드를 생성해 전달하지 않는다.

## 고정 범위와 실행 상한

CORE005 **한 Case, 신규 Trial 1회**, concurrency1. 후보 미도달·실패·상한·확인은 그대로
남긴다. 후보 도달 또는 PASS를 위한 재실행0. 기존 067 실패와 다른 Trial이며 덮어쓰지 않는다.

- 원 Canonical 원문·selected Task/parent·snapshot은 실행 전 case/dataset/fixture hash에 결속.
- 현재 Product SHA/tree, Prompt/Registry, Python, 후보/runner/기준문서 hash를 봉인.
- 기존 qwen3.5:9b 실제 digest, Ollama0.34.0, LOCAL_GPU, seed20260923 유지.
  temperature override 추가0, owner별 실제 Product sampler 유지, num_ctx16384/think=false.
- 기존 Run budget/repair 정책 유지. 별도 실험 최대20 actual wire/20 Provider dispatch attempt,
  외부 wall600초. FIRST·schema repair·semantic repair를 구분하고 실패도 전부 기록한다.
- 기준시각·current-Run selected ref는 실제 admission이 생성한다. 역사 067과 동일 input/wire의
  paired 비교라고 하지 않는다. 이번 runner는 시간·UUID를 의미상 같다고 덮어쓰지 않는다.
- 외부 Provider READ/WRITE/SEND0, snapshot READ는 실제 횟수와 arguments를 별도 기록.
  approval/resume0, 실제 Provider WRITE 경계는 계속 DENY.
- prepare는 metadata 조회만, generation0. `--execute-plan`은 봉인 hash 검증·exclusive claim
  이후 단일 child process에서만 실행한다. child와 worker 종료 전 isolation을 해제하지 않는다.

## 사전 판정과 실패 귀속

1. RU/Route에서 원문의 선택 Task 상태·기한 조회 및 새 Task 생성 금지가 보존되는지 본다.
   미요청 WRITE·조건 누락·불필요 미완료 필터가 생기면 upstream 실패로 따로 기록한다.
2. 실제 READ가 선택 Task/parent를 지키고 snapshot/Evidence가 현재 Run/handle/version으로
   Planning에 연결되는지 확인한다. 역사 snapshot map을 Planning State에 직접 넣지 않는다.
3. physical compose의 CHOICE_DISPATCH가 실제로 있었는지 확인한다. upstream 중단,
   deterministic formatter, catalog 없는 Product delegate는 후보 의미 PASS가 아니다.
4. 도달했다면 실제 PromptRef/first/repair/closed refs → materialized AnswerDraft가
   기존 validator/Supervisor/terminal에 전달되고 최종 답변에 보존되는지 본다.
5. 선택 Task의 미완료 상태와 date-only 기한을 보존한다. `needsAction`을 실제 업무 진행 중으로
   확대하지 않고, 없는 실행·완료를 주장하지 않는다. 답변 형태·FACT/PROSE를 정답으로 강제하지 않는다.
6. Runtime COMPLETED, 후보 구조 성공, 최종 답변 의미, 전체 RU/업무 성공을 구분한다.
   terminal 정답만으로 앞선 금지/Source 의미 실패를 없애지 않는다.
7. JSON raw는 UNREVIEWED를 유지하고 비민감 보고서에서 근거와 함께 수동 검수한다.
   end binding drift·환경오류는 성공 판정 대상이 아니다.

CORE001/004, 복합 Source, Calendar location, 완료/메모/정리 반례의 actual Main 성공은
이번 범위 밖이다. 088/085의 해당 진단을 이 한 Case 성공에 합산하지 않는다.
현재 결과는 Canonical92·일반화·전체 LangGraph 안정화·release activation 증거가 아니다.

## 실행 명령 (루트 검수·088 결과 확인 이후)

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_answer_choice_main --prepare evaluation/results/089-answer-choice-main-t1
.venv\Scripts\python.exe -m scripts.evaluate_answer_choice_main --execute-plan evaluation/results/089-answer-choice-main-t1/plan.json --plan-sha256 <prepare가 출력한 SHA256>
```
