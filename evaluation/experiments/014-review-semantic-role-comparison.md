# 014. Review 의미 역할 Projection 비교

기준 `2523f699`, 작업 브랜치 `codex/issue-251-connected-contract`. 012/013의
실제 첫 Review 입력과 출력은 재사용한다. 013의 `run_reference_time` 단독
Projection은 023 회귀와 028의 수신일→업무일 오결합으로 기각됐다. 이번 가설은
시각 하나가 아니라 **기존 값의 역할**을 좁게 전달하면 Review가 제안 Plan과
자료의 출처·시간을 덜 혼동한다는 것이다. Prompt source·출력 schema·모델은
유지한다. `review_semantic_context` 하나에 current-Run 기준시각, Review의
실행 전 단계, 기존 Evidence locator의 metadata timestamp와 선택 excerpt의
출처만 투영한다. 새 시간 해석기·요청 문구 분기·정답 disposition 보정은 없다.
후보 입력 계약은 격리된 개발 bundle v2에서만 허용한다.

고정 비교 입력은 023 정상 Plan, 028 상대 날짜/일반적 설명 Plan의 **실제 저장
입력 2건**, 그리고 동일 저장 입력에서 사전 변형한 합성 대조 5건이다:
023의 Action 날짜 오류, 023의 Gmail Evidence와 그 WorkFact 제거(실제 근거
부족), 023의 사용자 Preview 수정(기존 Plan title을 수정값으로 변경),
023의 명시적 참석자 초대 금지에도 참석자를 넣은 Plan, 023의 날짜 비적용
Task 제안. 합성 입력은 생산자 실행 결과가 아니며 실제
연결 성공률에 섞지 않는다. 합성 변형은 A/B에 동일 적용한다. 외부 내용은
Prompt에 비신뢰 Evidence로만 들어가고 평가 기대값은 주입하지 않는다.

조건: 9B 동일 digest, temperature 0, seed 1729, current Prompt source와
output schema. 실제 두 건의 A 첫 structured output은 012에 저장된 것을
재사용한다. 새 합성 다섯 건은 A/B 각 1회, 실제 두 건은 B 각 1회로 총 **12
신규 호출**을 상한으로 고정한다. 직렬 실행하고 timeout·Schema/repair·모든
출력을 보존한다. 원본/변형 입력 SHA-256을 남긴다. 첫 structured output과
모델 raw completion은 구분한다. 중단 조건은 정합한 입력 구성 실패, 모델
digest 변경, Prompt 계약 불일치 또는 안전 경계 위반이다. 후보가 실제 입력의
공통 오류를 줄이면서 정상·반례의 의미 회귀가 없을 때만 제품 연결을 검토한다.
단일 Trial로 안정성을 선언하지 않는다. WRITE·Provider READ·전체 E2E는 없다.

결과 전에는 제품 Review Node와 canonical/manifest를 바꾸지 않는다.

## 결과

사전 지정한 신규 12호출을 모두 직렬 실행했다. 모두 첫 structured inference
Schema는 통과했고 timeout은 없었다. 132,726 input / 6,696 output tokens,
총 호출 경과 201.4초다. 실제 023의 저장 A는 finding 0이었으나 B는 실행 전
Preview를 ‘아직 미실행’ ISSUE와 EVIDENCE_GAP로 오판했다. 실제 028의 저장 A는
`내일=9/8` 오판과 허위 EVIDENCE_GAP; B는 `내일=8/8` 계산은 했지만 수신일
9/7과 업무일 8/8을 논리적 모순으로 묶고 Gmail 날짜를 기준으로 바꾸라고 했다.

합성 대조에서는 잘못된 Action 날짜를 A/B 모두 발견했으나 둘 다 10:00–10:30을
1시간 또는 24시간 30분으로 오계산했다. 외부 메일을 제거한 입력에서 A는
EVIDENCE_GAP, B는 ISSUE로 분류했고 두 Arm 모두 불필요한 CONFIRMATION을
추가했다. 사용자 Preview 수정은 A/B 모두 원래 요청 제목을 재요구하는
허위 ISSUE를 냈다. 명시적 참석자 금지 위반은 A/B 모두 올바르게 발견했다.
날짜 비적용 Task 합성 입력은 기존 `required_information`의 8/8 여유 시간과
WorkAnalysis의 DATE fact를 제거하지 못한 **평가 입력 오염**이었다. 그 Trial은
원출력을 보존하되 의미 성공/실패 분모에서 제외한다.

판정: 이 **역할 필드 추가 형태**는 기각한다. 역할 표현 방법 전체를 영구
기각하지 않지만 같은 입력에 필드를 더 붙이는 재시도는 우선하지 않는다.
기존 Prompt가 이미 실행 전 단계와 ISSUE/EVIDENCE_GAP를 설명함에도 오류가
반복됐으므로 Review 한 호출의 판단 책임 분해를 다음 가설로 본다. 상세 입력,
fingerprint, 각 A/B 첫 출력·토큰·지연은 ignored
`evaluation/results/review-semantic-roles-20260916/result.json`에 있다. 실제
생산자 입력은 023/028 두 건뿐이고 합성 대조는 연결 성능이 아니다.
