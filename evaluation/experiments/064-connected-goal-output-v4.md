# 064 — Goal/Output 단일 의미 authority의 실제 Graph 연결

## 가설과 범위

T2의 Goal은 선택 Task 상태·기한 조회였으나 별도 Output FIRST가 UPDATE/SEND를 만들었다. 기존 062 v4의 Goal/Output modality authority를 재사용하여, 이미 결정한 Output을 후속 owner가 다시 생성하지 않게 한다. 새로운 문구별 규칙이나 Prompt 후보를 추가하지 않는다.

이 후보는 비활성 evaluation adapter다. Production MainGraph/Request Understanding physical node/StructuredInferenceRuntimeRouter/예산/하드웨어·모델 검증/schema repair를 실제로 사용한다. Product source와 활성 Prompt registry는 변경하지 않는다.

- 현재 Product Work 분해를 유지한다. 과거 v4의 token-reference Work 분해 변경은 포함하지 않는다.
- 한 physical `identify_goal` 호출 안에서 Goal+Output을 한 번 생성하고, Goal 4필드를 기존 consumer에 넘긴다. Source/prohibition/status/relation은 기존 owner를 그대로 사용한다.
- Output 소비 시 같은 Run·원문·선택 identity·Work/provenance·Goal·Registry candidate인지 검사하고 기존 Output/prohibition validator를 적용한다. 충돌을 정답으로 보정하거나 Output을 다시 생성하지 않는다.
- 캐시는 invocation-local이며 호출 종료 시 폐기한다. confirmation/resume/reconsideration은 기존 Product 경로를 그대로 사용한다.
- 독립 Output의 Resource/effect가 같아도 Work binding별 항목을 유지한다. READ/Provider 호출을 Work별로 복제하지 않는다.
- 별도 evaluation Prompt resolver에 정직한 input/output version을 결속한다. Product Goal schema17로 위장하거나 loader/repair mutation guard를 해제하지 않는다.
- joint authority는 기존 v4와 같은 temperature0을 사용한다. Production Goal0.1과 같다고 주장하지 않는다. 다른 owner의 실제 sampler는 바꾸지 않는다.

## 실행 전 직접 gate

기존 snapshot/runtime/runner와 candidate의 합계 48 unit/component 검사 PASS. 후보 자체 16개에는 실제 Product RU physical node의 compiled 호출, Output handoff 추가 dispatch0, 독립 Output 보존, 원문/선택/Work/provenance/Goal 오결속 거부, 금지 충돌과 revision 시 cache 불변, 실제 dispatch budget/하드웨어 거부, bounded repair 및 무관 의미 변조 거부가 포함된다. Fake 결과를 모델 의미 품질로 해석하지 않는다.

작성 중 두 Fake 검사 설정 오류(profile 한도를 절대 호출 한도로 오인, 유효하지 않은 FailureRecord enum)는 실제 계약으로 수정했다. 이는 모델 Trial 실패가 아니며 실제 모델을 실행하거나 재시도하지 않았다.

runner는 후보 선택·구현/Prompt hash를 plan에 결속한다. worker drain 후의 영속 최종 상태도 별도 관측하여 실험 상한 직전 snapshot과 혼동하지 않는다. 상한·승인·scope 정책은 바꾸지 않는다.

## 사전 등록할 실제 연결 비교

- CORE-005 후보 1회. 성공까지 반복하지 않는다. 동일 Dataset/snapshot/모델 digest/seed/scope/20 dispatch·600초 상한을 사용하며 새 실행 HEAD/hash는 plan에 기록한다.
- 기존 T2 실패를 그대로 보존해 최초 Output divergence와 실제 연결 차이를 비교한다. SHA·Prompt·Goal sampler·Work 실행 결과가 완전히 같은 paired Trial이라고 주장하지 않는다.
- 확인할 것: 원문 READ 목적 → Output 없음 → 선택 Task READ → 실제 Evidence → 근거 있는 상태/date-only 기한 답변. 각 의미 항목과 구조 통과를 분리한다.
- 금지 의미가 없어도 WRITE가 발생하지 않았다는 이유로 prohibition PASS를 주지 않는다. 남은 owner 실패는 그대로 기록한다.
- 외부 Google/GitHub 연결·WRITE/SEND·승인/resume 0. Provider는 기존 로컬 snapshot만 사용한다.
- 후보가 통과하면 성공/반례/모호/복합 Core 소집합으로 확장할 근거이지 Production 채택이나 Canonical92 성공이 아니다.

## 연결 T1 — 모델 호출 전 평가 adapter 결함

HEAD `bd34f4910764e419873c833ba3cfb0a40990f13f`, Trial
`3be76343-6ce6-49da-a2ef-473c6b59b6d1`을 한 번 실행했다. 실제 composition의 RU는
`ConfirmationAwareLLMRuntime`으로 감싼 router를 받는데, 후보가 router 자체만
허용하여 생성자에서 거절됐다. 앞의 compiled 직접 gate는 actual router를 직접
주입했으므로 이 composition wrapper를 놓쳤다.

모델 dispatch/토큰/Provider READ/WRITE 모두 0. Product가 이 adapter 예외를
`CONTRACT_VIOLATION`/RECOVERY_REQUIRED로 보존한 것이며, Product 의미 실패나
모델 후보 점수로 집계하지 않는다. HEAD/Product hash는 실행 중 불변이다.
원 raw는 `evaluation/results/064-core005-goal-output-main-t1/raw.json`, SHA256
`c2d8f161e3a50182793e2d6845ccc3a9a70d990efffe11e01add529f71b699e2`에 보존했다.

기존 wrapper의 역할을 제거하지 않고 알려진 실제 composition을 수용하도록
평가 adapter만 수정한다. pending confirmation은 기존 Product 경로를 유지한다.
수정 후 실제 composition을 사용하는 모델0 직접 gate를 먼저 추가하고, 모델 연결은
새 HEAD/Trial의 후보 1회로 구분한다. T1을 덮어쓰거나 성공 Trial로 교체하지 않는다.

### T1 평가 adapter 수정 직접 확인

알려진 `ConfirmationAwareLLMRuntime`만 명시적으로 인식하여 joint 호출의 실제 router를
참조하고, 나머지 owner에는 기존 wrapper를 유지한다. 같은 Run의 pending confirmation이
있으면 후보를 적용하지 않는다. 임의 wrapper chain을 추정해 벗기지 않는다.
actual snapshot composition → StartRun → schedule → MainGraph를 사용하는 fake-wire gate에서
실제 Work 호출과 joint Goal 호출의 RETURNED를 확인했다. 그 뒤 의도적 fake stop이며 업무
성공 판정이 아니다. snapshot/runtime/runner/candidate 합계 **50 PASS**(후보18 포함).
제품 코드·활성 Prompt·안전 gate 변경은 없다.

## 연결 T2 — 의미 개선과 별도 Product 입력 계약 결함

HEAD `a02be623a5e25d6e042ceb68f884001bed6771e4`, Trial
`762a8ec2-f8b9-4fcd-93e9-6c798842aaf2`, Run
`06dfe02c-84c7-48d5-a8c4-d80c0d89b8aa`에서 후보 1회를 실행했다.
기존 T1 및 Production T2 실패를 덮어쓰지 않았다.

- joint FIRST는 READ/ANSWER_ONLY와 Output 없음으로 요청 의미를 유지했다.
  선택된 Task를 정확한 identity로 snapshot READ 1회 수행하고 Evidence와
  SUFFICIENT를 거쳐 ANSWER Planning까지 도달했다. Provider WRITE/SEND/승인 0.
- **최초 의미 손실은 독립 prohibition owner**다. 원문 생성 금지가 실제 입력에
  있음에도 FIRST에서 CREATE를 NOT_FORBIDDEN으로 반환했다. 외부 WRITE가 없다고
  금지 보존 PASS로 판정하지 않는다. joint 후보의 금지 owner는 변경하지 않았다.
- **별도 Product 결함**: `compose_answer`가 기존 typed `evidence_by_work_unit`을
  전달하지만 Prompt 입력 계약은 이를 허용하지 않았다. 모델 dispatch 전에
  `unknown Product Prompt fields`로 거절되어 최종 답변 성공이 아니다.
  `outline_answer`에도 같은 계약 누락이 있음을 직접 검사로 확인했다.
- 실제 wire 7회 / repair 0, 입력 18,971·출력 658 tokens, LLM latency 34,474ms,
  전체 37,281ms. compose의 거절을 포함한 dispatch 시도는 8회다.
  기존 Production T2의 잘못된 WRITE/재검토 반복과 구분되지만 SHA·Goal sampler·
  Work 출력이 동일한 paired trial은 아니므로 전체 성공률 개선으로 환산하지 않는다.

안전 raw: `evaluation/results/064-core005-goal-output-main-t2/raw.json`, SHA256
`8991d4adb49ab0d79c9f443452a84c1a38a30be99291b550ae5323112b9c793b`.
모델 결과는 **금지 의미 잔여 실패 + Planning 계약 차단**, 후보는 비활성이다.

### Product 계약 수정 및 직접 검증

두 ANSWER slot의 input v3에 기존 WorkUnit/Evidence projection만 optional로 등록한다.
Prompt 본문·content hash·출력 schema·Node·LLM 호출·activation gate는 그대로다.
unknown/forbidden fields 거부는 유지하며 Work별 LLM/Provider 호출을 추가하지 않는다.
기존 compiled 소비 테스트가 fake LLM 앞에서 실제 Prompt assembler를 통과하게 했다.
수정 전 outline/compose 두 검사가 같은 unknown-field 오류로 실패(2 FAIL/14 PASS).
레지스트리 테스트의 expected input version도 v3로 맞추며, 누락된 binding을 생성하거나
기존 잘못된 의미를 validator로 복원하지 않는다.

수정 후 관련 Product agent/Graph/Prompt/Approval/Execution/Verification/Recovery 및
connected 소비 회귀 **1,967 PASS**. raw 모델 실행 없이 계약 결함을 직접 닫았다.
별도 새 연결 Trial로 실제 답변 생성 여부를 확인할 예정이며 이 직접 검사 수를 모델
의미 성공률로 사용하지 않는다.

## 연결 T3 — 실제 답변 연결 완료, 금지 의미와 상태 표현은 미완료

HEAD `c8708b1d95298e934dfa9ad7cc8ca5d5d7f611cf`, Trial
`4322da9d-f1a5-41da-be84-94a8cc72f0cd`, Run
`ddafd49a-83ca-4ea4-a63c-945971835456`에서 별도 후보 1회를 실행했다.
T1/T2 실패는 그대로 보존한다. Product 입력 계약 수정 후 실제 `compose_answer`까지
연결됐다는 증거이며, 기존 실패를 성공 Trial로 교체하거나 Production 채택을 뜻하지 않는다.

### 첫 출력 → handoff → 실제 근거 → 답변

| 경계 | 실제 관측 | 의미 판정 |
| --- | --- | --- |
| Work | 단일 `work-1`, 조회 문장만 exact provenance에 포함. 뒤의 생성 금지 문장은 Work span 밖이지만 모든 관련 owner의 `user_request`에 그대로 존재 | 단일 업무 자체는 타당. span 밖이라는 이유로 원문의 금지를 무시할 수 없음 |
| joint Goal/Output FIRST | 선택 Task 상태·기한 조회, `ANSWER_ONLY`, `requested_outputs=[]`; Output handoff도 빈 목록, 추가 dispatch 0 | 요청하지 않은 WRITE 생성 없음. Goal에 `Ion 온보딩`이라는 업무 개념이 생겼지만 이번 selected identity READ를 변경하지 않음 |
| prohibition FIRST | 원문 `새 작업은 만들지 마.`가 입력에 있지만 CREATE 포함 네 effect 모두 `NOT_FORBIDDEN` | **첫 확정 의미 손실**. 최종 RequestIntent와 Planning 입력의 `effect_prohibitions=[]`로 이어짐. repair/normalizer가 삭제한 것이 아님 |
| Source / ambiguity | TASK만 REQUIRED, SINGULAR/work-1, 상태·due 포함; 다른 Source 9개 NOT_REQUIRED. source status 조건은 빈 목록, ambiguity CONNECTOR | 현 상태를 묻는 요청이지 미완료 Task만 찾는 필터 요청은 아니므로 status 조건 없음은 오류가 아님. 선택 identity가 조회에 유지됨 |
| Route / Retrieval | `tasks_get_task` 1회, canonical 선택 Task와 parent 정확히 일치. snapshot/Evidence 모두 `status: needsAction`, `due: 2026-08-10T00:00:00.000Z`. route의 work-1 binding과 Evidence ref가 Planning까지 유지 | Source 선택과 실제 snapshot 연결 통과. 다른 Provider 조회·외부 변경 없음 |
| Sufficiency / Planning | SUFFICIENT, issues 없음. `compose_answer` FIRST가 한 Evidence ref와 답변 반환 | ANSWER 생성 연결 통과. 실제 상태 의미의 정확성과 typed 금지 보존은 별도로 판정 |

최종 원문:

> 선택한 Ion 신입 온보딩 체크리스트의 상태는 진행 중 (needsAction)이며 기한은 2026 년 8 월 10 일입니다.

Task title/identity와 날짜는 실제 같은 Case의 ION snapshot에서 왔고, 시각이나 업무 마감
시각을 발명하지 않았다. 다만 `needsAction`은 **미완료**를 뒷받침할 뿐 착수·진행 사실을
증명하지 않는다. 기존 `project_task_read_answer._task_status` 및 Task detail projection도
이를 미완료/incomplete로 취급한다. 원 enum을 병기했고 완료라고 답하지는 않았으므로
전체 답변을 무근거로 간주하지 않되, **업무 답변 의미는 PARTIAL(상태 표현 과장)**로 남긴다.
이 표현은 `compose_answer` FIRST에서 생겼다. Provider/Evidence가 진행 상태로 변조된 것이
아니다. 별도 Draft materializer의 `진행 중` 매핑은 이번 ANSWER 입력에 없으므로 원인으로
귀속하지 않는다.

### 수정 계약의 실제 dispatch 증거

- call 8 `planning.compose_answer`: input version **3**, output version 1,
  Prompt version `1.0.19`, content hash
  `9139d83cf3a2cf1e0ccb87b77e7e4fb532d8482043d9619e46c81327741c39f1`.
- 실제 입력에 `evidence_by_work_unit=[{work_unit_id: work-1, evidence_refs: [...]}]`과
  같은 route의 `source_statuses.work_unit_ids`가 존재한다. 입력 hash
  `da1483e810cf27004ae463a6619f3286682b6e693decd8d58c335cef26e56384`,
  actual wire hash `e8a59a076538a0916f365e57bcfac6de0b2e57c868bd81835b40097fbfddea3a`.
- 실행 HEAD의 registry/assembler, 기록된 각 입력·Schema·PromptRef·options로 payload를
  메모리에서 재구성하여 **8/8 actual wire hash 일치**를 확인했다. 모델 재호출은 하지 않았다.
  `outline_answer` LLM 호출은 이번 경로에 없으므로 해당 slot의 실제 모델 검증으로 확대하지 않는다.
- 실행 중 HEAD/Product tree 불변. worker drain 전후 영속 Run은 동일한 COMPLETED/SUCCESS다.
  activity cursor만 추가됐다. raw의 `semantic_verdict=UNREVIEWED`는 변경하지 않았으며,
  Product terminal SUCCESS를 Gold/의미 PASS로 승계하지 않는다.

### 비용·안전·비교 한계

actual wire/FIRST **8**, schema repair **0**, semantic revision **0**.
입력 **22,838**, 출력 **727 tokens**, LLM 합계 **39,363ms**, 전체 **42,390ms**,
usage 누락 **0**. snapshot READ **1**, 실제 외부 Provider READ/WRITE/SEND **0**,
승인/resume **0**, rerun-to-pass **0**. 관측의 `provider_dispatch_attempts=8`은 LLM
Provider 호출 수이며 Connector READ 8회라는 뜻이 아니다. 상한/timeout 종료가 아니다.

joint Goal은 temperature0, Source0.05, ambiguity0; Work/prohibition/status/Sufficiency/
compose는 temperature option 미전송으로 현 모델 default를 사용한다. seed20260923,
think=false, num_ctx16384가 wire에 결속됐다. 이 Trial만으로 Goal/Output 구조의 인과 효과나
반복 안정성을 증명하지 않는다. T2와 SHA·실제 Goal/Work 출력·시각이 다르므로 단순 paired
성공률/지연 개선으로 환산하지 않는다.

**판정:** 연결/입력 계약 통과, 선택 READ와 Evidence 귀속 통과, 업무 답변 PARTIAL,
typed 생성 금지 보존 FAIL. 기존 Production T2에서 Goal이 있어도 CREATE 금지를 생성한
반례와 함께 보존한다. joint 후보는 비활성 유지하며 Production/Canonical92 채택 근거는
아직 부족하다. 이 검수에서 제품·Prompt·runner·raw 변경 및 추가 모델 실행은 0이다.

안전 결과와 파일 bytes SHA256:

- `evaluation/results/064-core005-goal-output-main-t3/raw.json`:
  `051602b04ccc2b89ca93df4015d63700af5cfeb2b24f69b646e5bc7fda6f94dc`
- 같은 폴더 `calls.json`:
  `148dabca5044d08fa0a25c9e1bd2169b29ce813420c11dcdb740fdc42b8f2b0e`
- 같은 폴더 `plan.json`:
  `f4d851e82f2bbd438bea1eb29ad2d64b35ea984824b0369f5ff3eaefb3359ab6`
- 같은 폴더 `end_binding.json`:
  `c4c522f7cbb37f2479e89ebc705fa99e9088cd1cff75b8a0a4244084ba662e49`
