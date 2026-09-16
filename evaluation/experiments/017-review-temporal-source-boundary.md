# 017. Review의 Gmail 수신 metadata와 업무시각 분리

기준 `2523f699`. 013 기준시각 추가와 014 역할 필드 추가 모두 028의 Gmail
`Received` 날짜를 업무 날짜처럼 결합했고 023에는 허위 finding을 만들었다.
015/016의 책임 분리는 일부 증상을 줄였으나 사용자 확인 권위에서 반복 실패해
제품 채택하지 않았다. 최초 혼동 경계는 Retrieval normalized Gmail excerpt가
본문과 `Received` envelope를 같은 text에 직렬화하고, Review Goal 입력이
이를 요청의 EVENT_TIME과 함께 받는 데 있다. 실제 State의 metadata는 유지한다.

새 개발 후보는 RequestIntent의 기존 `temporal_axis=EVENT_TIME` 제약을
소비하는 Review 입력에 한해 Gmail Evidence의 **정확히 일치하는 정규화
envelope `Received: <locator.received_at>` 한 줄과 locator.received_at만**
Review Prompt Projection에서 제외한다. 본문·Subject·From·To·다른 날짜는
유지한다. 요청에 `MESSAGE_TIME` 등의 다른 시각축이 있거나
envelope가 예상 형식과 다르면 원본을 유지한다. 현재 Run 기준시각은 기존
projection에서 가져온다. 새 날짜 파서나 source 선택·보정 규칙은 없다.
입력 계약 후보는 격리된 개발 bundle에만 존재한다.

실제 고정 Review 입력 023/028에서 C1=metadata envelope만 제외,
C2=C1+current-Run 기준시각을 각 1회, 총 **4호출**로 먼저 비교한다.
두 실제 입력 모두 정상 Plan 허위 finding 없이 `내일=8/8`을 보존할 때만
2단계로 WRONG_ACTION_DATE, MISSING_EXTERNAL_MAIL, FORBIDDEN_ATTENDEE,
USER_PREVIEW_EDIT_CLEAR를 C2 각 1회 추가해 총 **최대 8호출**로 제한한다.
015/016의 합성 입력·저장 출력과 origin을 구별한다. 9B 동일 digest,
temperature0/seed1729, Prompt source/output schema는 현재 제품과 동일하다.
입력/fingerprint·호출/Schema/timeout·토큰/지연을 ignored result에 모두
남긴다. 한 번의 성공은 안정성 아님. Viewer/실제 Provider/WRITE·전체 E2E는
없다. C2가 위 기준에 실패하면 product projection/contract는 변경하지 않는다.

## 1·2단계 결과와 고정 반복 계획

1단계 4호출 모두 Schema 완료. C1은 023 정상 계획을 두 ISSUE로 잘못 판단,
028은 finding 0이었다. C2는 실제 저장 023·028 모두 finding 0이었다.
2단계 C2는 WRONG_ACTION_DATE의 날짜 오류와 FORBIDDEN_ATTENDEE의 금지
위반을 ISSUE로 발견했다. MISSING_EXTERNAL_MAIL은 EVIDENCE_GAP와 함께
내용 누락 ISSUE를 추가해 문제 주체를 완전히 분리하지 못했다. 수정된 사용자
Preview는 과거 제목 제약을 다시 우선하는 허위 ISSUE 두 건을 냈다. 기존
aggregate에 연결하면 023/028 PASS, 날짜/금지 REVISE, 메일 누락 RETRIEVE_MORE,
Preview 수정 허위 REVISE다. 이 단계는 수정 실행까지 연결한 것이 아니다.

단일 Trial로 활성화하지 않는다. **추가 비교는 실행 전에 고정**한다:
같은 실제 저장 Review 입력 023·028 각각에서 A(현행)와 C2를 교차 순서
각 2회, 총 8 신규 호출. 같은 arm·case의 입력 SHA-256이 Trial 간 동일해야
한다. 모델/digest/temp/seed/Prompt source/Schema 동일, RunBudget 독립,
합성 Provider를 다시 실행하지 않는다. 정상 023의 허위 finding 또는 028의
수신일→업무일 결합이 C2에서 재발하면 채택하지 않는다. A도 모두 보존하며
성공할 때까지 재실행하지 않는다. Preview 수정과 근거 부족의 잔여 결함은
별도 실패 family로 기록하고 해당 경로의 안정화 완료를 주장하지 않는다.

## 3단계 반복·채택 범위

고정 A/C2 각 2회, 8호출을 모두 보존했다. 같은 case·arm 입력 fingerprint는
Trial 사이 동일했다. 023은 A/C2 모두 finding 0, 028은 A가 두 번 동일한
`내일=9/8` ISSUE와 허위 EVIDENCE_GAP를 냈고 C2는 두 번 finding 0이었다.
Model·Prompt source·output schema는 같고, 입력 차이는 EVENT_TIME Gmail
수신 envelope의 Review-only 분리 및 current-Run reference time이다. C2의
입력 토큰은 각 A보다 33개 적었다. 3단계 86,028/1,180 input/output tokens,
호출 경과 36.0초지만 동일 Prompt 캐시 영향이 커 latency 독립 측정이나
대규모 반복 신뢰성으로 해석하지 않는다.

**제한적 채택 후보**: 정상화된 Gmail 수신 envelope가 정확히 식별되고
RequestIntent 시간축이 `EVENT_TIME` 하나이며 사용자 Preview 수정·현재
confirmation이 없는 초기 goal/evidence Review만 C2 입력을 사용한다. 실제
Gmail State의 metadata와 본문은 변경하지 않는다. `MESSAGE_TIME` 또는 혼합
시간축, 변경·확인·RECHECK 입력은 기존 투영을 유지한다. 이는 Case ID/문장
규칙이 아니라 현재 판단에 불필요한 source metadata 축을 좁히는 것이다.
사용자 수정에서 옛 title 권위가 남는 문제와 실제 Evidence 부족 시 과잉
ISSUE는 해결되지 않았으므로 Review 전체 안정화로 표시하지 않는다. 채택
후에는 실제 producer→Review input의 동등성, 직접 영향 테스트, Canonical,
Prompt manifest와 인접 routing/repair를 확인해야 한다. 상세는 ignored
`evaluation/results/review-temporal-source-20260916/` 세 결과에만 있다.

## 제품 연결 확인 계획

05/06/15과 Prompt input contract/manifest 및 Review projection이 정합한
후 직접 영향 테스트를 먼저 실행한다. 그다음 021/023/028을 각각 **1 Trial**만
현재 RU→Tool Route의 실제 출력에서 시작해 합성 Provider READ→Work Analysis
→Planning→Review로 직렬 연결한다. 앞선 저장 입력과 새 Evidence fingerprint가
다르면 paired 효과라고 주장하지 않는다. Goal inspector의 실제 Prompt input에
조건부 Run 기준시각이 존재하고 Gmail `Received` envelope가 본문과 분리됐는지,
첫 structured output과 aggregate disposition, 더 필요한 조회/수정/확인
신호를 확인한다. Review가 REVISE/RETRIEVE_MORE면 해당 Owner가 실제로
재진입했는지 확인하지 않은 이상 수정 경로 성공으로 세지 않는다.
021은 이전 false gap 경향을 보는 별도 입력이지 023/028과 같은 의미의
반복이 아니다. 실제 Provider/WRITE/최종 응답/전체 92는 실행하지 않는다.

## 현재 producer 연결 결과

고정 계획대로 021/023/028 각 1 Trial, 현행 RU→합성 Provider READ→
Work Analysis→Planning→Review를 직렬 실행했다. 연결 조회는 19 READ,
Retrieval 구간 12 LLM 호출, 577.4초였으며 Provider WRITE는 0이다.
021은 Planning `OUTPUT_SCHEMA_INVALID`로 Review까지 못 갔다. 023은
Review Goal prompt가 Run 기준시각을 받았고 Gmail 수신 envelope는 보지
않았으며 finding 0/PASS였다. 028도 동일한 투영을 받았고 `내일=8/8`을
보존했지만, FreeBusy `busy_intervals: []`와 09:00–09:30 Plan에도 슬롯을
재확인하라는 ISSUE, 참석자 `[]`에도 메일 발신자 회사 주소를 요구하는
EVIDENCE_GAP를 생성하여 최종 CONFIRM으로 갔다. 수신일→업무일 혼동은
이 입력에서 재발하지 않았지만 별도의 실행 전/근거 충분성 혼동이 남는다.
이 결과는 새 producer Evidence이므로 저장 입력의 A/C2 순수 비교 분모에
합치지 않는다. 조회·Work Analysis·Planning의 새 출력도 함께 달랐다.
평가기의 요약 `node_processing_correct_count=0/3`은 세 경우 모두
`DOWNSTREAM_OUTPUT_NOT_EVALUATED`라는 분류 때문이며 의미 오답 3건이
아니다. 023만 Goal 판단이 의미 검증됐고, 021은 호출/Schema 실패,
028은 모델 원판단 오류다. `REVISE`/`RETRIEVE_MORE` 후 실제 수정과
RECHECK는 이 연결에서 발생·검증되지 않았다. 원출력은 ignored
`evaluation/results/review-temporal-connected-20260916/`에 있다.

제한 채택 제품 SHA는 `b68d3939`다. 이 SHA는 Review 전체 안정화나
수정 경로의 의미 성공을 증명하지 않는다. 직접 영향 테스트 58개 통과,
Prompt source hash 유지·input contract v2 반영을 확인했다.
