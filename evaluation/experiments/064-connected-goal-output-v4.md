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
