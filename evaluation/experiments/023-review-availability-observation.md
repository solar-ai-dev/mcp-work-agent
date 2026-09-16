# 023. Review의 검증된 availability 소비 경계

기준 `53842ae6` 및 022의 세 Preview 입력 후보 기각. 현행 Review
초기·RECHECK Prompt는 FreeBusy Evidence의 `busy_intervals: []`는
받지만 Retrieval이 결정적으로 계산한 `availability_results`는 받지
않는다. 021 RECHECK와 022 materialized 후보의 허위 근거 부족 finding은
이를 모델이 재계산하도록 떠넘긴 경계일 수 있다. 단, availability가
외부 메일·Task 내용까지 보증하지는 않으며 빈 busy만으로 가용성을
확정하지 않는다. 비교에는 012 실제 연결 결과에서 Work Analysis가
소비한 `AvailableIntervalV1[]`만 사용한다. 합성 입력에 새 구간을
만들지 않는다.

후보 B는 기존 Review prompt input을 그대로 두고, 동일 current-Run
Retrieval artifact에서 검증된 `availability_results`를 하나의 optional
field로 제공한다. Prompt source, output schema, 모델, Evidence, Plan,
source statuses는 유지한다. source result가 없으면 필드를 생략한다.
개발 manifest의 입력 필드만 허용하고 제품 코드는 아직 변경하지 않는다.

고정 Node 비교는 다음 6개 입력을 A/B 각 1회, 총 최대 **12 LLM 호출**로
직렬 실행한다. 정상 023/028 초기 Goal, Preview 수정 023 초기 Goal,
메일 Evidence 부족 023 초기 Goal, 날짜·참석자 수정 후 RECHECK 2건.
후자 두 Plan은 021 실제 Planning 출력이고 RECHECK 입력도 저장된 그대로다.
정상·Preview·메일 부족은 021 저장된 실제/합성 입력의 origin을 구분한다.
각 label은 Prompt source/Schema/모델 digest/temperature0/seed1729,
Run budget과 입력 SHA를 고정한다. 원출력, failure/repair, 토큰·지연을
ignored result에 보존한다.

검토 기준: 정상 finding 0 유지, Preview의 사용자 수정 오판과 메일
부족의 잘못된 CONFIRM 악화 없음, 수정 후 RECHECK의 근거 없는
FreeBusy/Calendar 부족이 감소하면서 실제 메일·Task 부족을 숨기지 않음.
첫 결과가 유력해도 고정 반복·compiled 연결 전 제품 채택하지 않는다.
결과가 나쁘면 단순 field 추가를 반복하지 않고 Review의 evidence-status
판단 책임과 finding 출력 계약을 재검토한다. Provider READ/WRITE 0,
전체 92 실행 없음.

개발 bundle 첫 preflight는 이미 v2인 Goal input을 v3으로 잘못 올려
loader가 거절했다. 모델 dispatch 0, 제품/Domain Run 0. 지원 v2로
고친 뒤 계획한 12호출을 모두 보존했다. A의 정상 023/028은 finding 0,
B는 각각 2/3건 허위 ISSUE·EVIDENCE_GAP·CONFIRMATION을 생성했다.
Preview 023은 A 3→B 2 허위 finding, 메일 부족은 A의 EVIDENCE_GAP+
CONFIRMATION이 B에서 ISSUE+EVIDENCE_GAP로 바뀌었지만 올바른
Owner 분류를 증명하지 못했다. 날짜·참석자 수정 후 RECHECK도 B가
새 ROUTE_ISSUE/CONFIRMATION을 만들었다. 실제 availability를
전달했지만 정상 입력 회귀가 크므로 **제품 채택 기각**한다.
검증된 구간을 Prompt에 추가하는 것만으로 모델이 역할을 올바르게
해석한다고 가정할 수 없다.
