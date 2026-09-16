# 016. 좁은 Goal inspector의 사용자 권위 계약 복원

기준 `2523f699` + 015의 격리된 개발 후보. 015는 요청↔Plan과 Evidence 판단을
분리했지만 Goal 개발 Prompt가 현행 Review Prompt의 두 기존 계약을 누락했다:
명시된 Preview 수정 path/value는 현재 사용자 권위이며, 이미 제공된 값·대상·
검증된 계산을 재질문하지 않는다. 이 계약만 Goal 개발 Prompt에 복원한다.
외부 Evidence arm, 출력 schema, 집계/라우팅, 제품 Prompt는 바꾸지 않는다.
이는 013의 기준시각 문구 반복이 아니라 015 후보의 책임 경계 정합화다.

023·028 실제 입력, WRONG_ACTION_DATE·FORBIDDEN_ATTENDEE 합성 입력에서
저장된 015 Goal 첫 출력과 새 후보 D를 각 1회 대조한다. 기존 Preview 수정
합성값 `사용자가 수정한 점검 제목`은 placeholder로 오해될 수 있어 평가기
오염으로 분류하고 성공률 분모에서 제외한다. 같은 구조의 명확한 사용자 수정값
`Kestrel 공급 지연 점검`으로 새 합성 입력을 만들고, 015 Goal A와 D를 각
1회 비교한다. 총 **6 신규 호출**, 9B 동일 digest/temp0/seed1729, 직렬.
입력 fingerprint와 모든 호출/실패/토큰/지연을 ignored result에 남긴다.
023 허위 finding, 028 불필요 확인, 명시 금지의 재질문이 남으면 Prompt 교정
반복을 중단하고 이 두 호출 Product 연결을 보류한다. WRITE/Provider READ는 없다.

## 결과

6회 모두 Schema 완료. 023 정상 Plan은 finding 0, 잘못된 날짜는 ISSUE,
참석자 금지 위반도 D에서 ISSUE로 개선됐다(015의 불필요 CONFIRMATION 대비).
하지만 실제 028은 여전히 빈 슬롯 확인과 생성 진행을 다시 묻는 CONFIRMATION,
명확한 사용자 Preview 수정은 A/D 모두 수정된 제목을 다시 확인하는
CONFIRMATION을 냈다. 이 값은 현재 명시적 수정이므로 재질문은 잘못이다.
따라서 Goal Prompt의 문구 보강을 **중단**하고 제품에 연결하지 않는다.
한 호출의 본질적 부담, 입력에서의 권위 표시 방식, Confirmation 판단의
책임 경계를 다시 검토한다. Evidence arm의 015 성과만으로 두 호출을 채택하지
않는다. 상세 원출력·fingerprint·비용은 ignored
`evaluation/results/review-goal-authority-20260916/result.json`에 보존했다.
