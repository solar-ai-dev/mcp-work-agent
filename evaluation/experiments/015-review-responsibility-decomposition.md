# 015. Review goal fit과 Evidence adequacy 책임 분리 후보

기준 SHA `2523f699` + 014 평가 코드. 013/014의 입력 필드 추가는 023 기존
성공을 깨고 028의 수신일↔업무일 결합을 해결하지 못했다. 현재 Prompt에는 이미
실행 전 Proposal과 ISSUE/EVIDENCE_GAP 구분이 있으므로 같은 문구를 반복하지
않는다. 가설은 한 호출이 요청↔Plan 적합성과 외부 Evidence 충분성을 함께
판정하면서 서로 다른 시간 권위를 섞는다는 것이다.

개발 후보는 Review의 기존 goal/evidence 책임을 별도 국소 판단 둘로 비교한다.
Goal arm은 request_intent + proposed planning_result + current-Run reference time
및 사용자 Preview 수정만 본다. 외부 Evidence는 주지 않는다. Evidence arm은
request_intent + proposed planning_result + selected Evidence/WorkAnalysis만 본다.
둘 다 기존 finding DTO로 출력하고, 이번 진단에서는 aggregate를 바꾸거나
정답 status를 보정하지 않는다. Prompt source·입력 계약은 격리된 개발 bundle에
만 존재한다. 실제 제품 slot/manifest/canonical은 결과 후 판단한다.

고정 입력은 014의 저장 SHA를 그대로 사용한다. 실제 023/028 두 건에서 각각
Goal/Evidence 1회, 합성 WRONG_ACTION_DATE와 USER_PREVIEW_EDIT에서 Goal 1회,
MISSING_EXTERNAL_MAIL에서 Evidence 1회, FORBIDDEN_ATTENDEE에서 Goal 1회:
총 **8 신규 호출**이다. 날짜 비적용 합성 입력은 014에서 오염이 확인되어
제외한다. A는 012/014에 저장된 첫 결과이며 B를 호출하지 않는다. 모델
9B 동일 digest·temperature 0·seed 1729, 출력 Schema 유지, Provider READ/WRITE
없음, 직렬 실행. 입력/fingerprint·모든 호출/실패·토큰/지연을 ignored result에
보존한다. Goal이 023 정상 Plan에 허위 문제를 내거나 Evidence가 실제로 없는
메일과 있는 메일을 구별하지 못하면 제품 결합을 하지 않는다. 두 호출로 비용이
늘어도 의미 개선이 충분하지 않으면 채택하지 않는다. 단일 Trial PASS는 안정성
근거가 아니다.

## 결과

평가 bundle 경로 구성 오류 2건을 provider 호출 전 고쳤다. 예정된 8호출은
모두 실행·Schema 완료, 합계 47,501 input / 1,343 output tokens, 호출 시간
51.8초였다. 실제 023은 Goal/Evidence 양쪽 finding 0, 028은 Evidence
finding 0이나 Goal이 이미 확정된 8/8 일정 생성에 불필요한 CONFIRMATION을
제기했다. 잘못된 Action 날짜는 Goal이 정확한 ISSUE로 잡았다. 실제 Gmail을
제거한 입력은 Evidence가 EVIDENCE_GAP로 구분했다. 그러나 Preview 수정은
Goal이 수정 제목을 placeholder로 보아 CONFIRMATION, 명시적 참석자 금지
위반도 금지를 ISSUE로 다루지 않고 다시 선택하라는 CONFIRMATION을 냈다.

따라서 **현 개발 후보는 채택하지 않는다**. 책임 분해 자체는 023과 실제
Evidence 유무에서 가능성을 보였지만, 이 Goal 후보의 개발 Prompt가 현행
Prompt의 검증된 사용자 수정 우선순위와 이미 제공된 값의 재질문 금지 계약을
충분히 옮기지 못한 상태다. 다음 한 차례는 누락된 기존 계약을 복원해 같은
입력과 합성 수정 대조에서 비교한다. 여전히 허위 Confirmation이 나오면
문구 추가를 멈추고 출력 책임/확인 권위 경계를 재검토한다. 새 두 호출은 현재
세 inspector의 첫 호출 비용을 최소 +1 늘리므로 품질 개선이 확인되지 않으면
호출 절감과 함께 채택할 수 없다. 023/028 외 실제 연결은 미검증이다. 상세는
ignored `evaluation/results/review-decomposition-20260916/result.json`에 보존했다.
