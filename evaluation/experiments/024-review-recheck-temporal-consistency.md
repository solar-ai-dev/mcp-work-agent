# 024. 초기 Review와 RECHECK의 시간 역할 입력 일치

기준 `53842ae6`. 017의 제품 채택은 현재 Run의 `temporal_axis`가
`EVENT_TIME` 하나이고 정규화된 Gmail envelope를 정확히 확인하며
사용자 수정/confirmation이 없는 **초기** Goal inspector에만
Gmail `Received`를 Review Prompt에서 분리하고 Run 기준시각을 준다.
RECHECK는 같은 요청·Evidence여도 이 Projection을 적용하지 않는다.
021의 수정된 날짜·참석자 Plan에 대한 RECHECK 원입력에는 정확히 그
`Received` envelope가 남아 있다. 저장 Run 기준시각은 2026-08-07,
Gmail 수신 metadata는 그보다 뒤인 2026-09-07이라 역할 혼동 위험이
크다. 이 진단은 처음 없앤 날짜 혼동이 재검토에서 재발하는지 보는
것이지, 수신일·발신자·Task를 Case별로 숨기는 규칙을 만들려는 게 아니다.

후보 B는 017에서 채택한 동일한 검증 조건과 `_separate_gmail_receipt_metadata`
Projection을 RECHECK 입력에도 적용하고 `run_reference_time`을 추가한다.
State의 원본 Evidence·metadata는 그대로 보존하고, 본문·제목·발신자·
수신자 및 다른 날짜는 유지한다. `MESSAGE_TIME` 또는 혼합 축,
비정규화 envelope, Preview 수정·confirmation에는 적용하지 않는다.
Prompt source/output schema/모델은 현행과 같다. 개발 input contract만
optional 기준시각을 허용하며 제품 코드는 아직 바꾸지 않는다.

저장 021의 날짜 수정 후·금지 참석자 제거 후 RECHECK 2건을 A/B
각 1회, 총 최대 **4 LLM 호출**, temp0/seed1729/동일 digest, 고정
Evidence·Plan·Prompt·Schema로 교차 비교한다. baseline RECHECK
원출력도 별도 보존한다. 후보는 두 Plan에서 해결된 오류를 다시 지적하지
않고, 없는 근거/확인을 새로 만들지 않아야 유력하다. 같은 함수의
static 반례로 `MESSAGE_TIME`·혼합축/비정규화 envelope는 원본이
유지되는지도 검사한다. 단발 2건이 좋더라도 반복 및 compiled 순환
검증 전 제품 채택하지 않는다. Provider READ/WRITE·전체 92는 0.

4호출 모두 Schema 완료. static 반례 세 유형은 원본 입력을 유지했다.
하지만 B에서도 날짜 수정안은 외부 내용/정책이 없다는 허위 gap과
“실제 캘린더에 저장됐는지 확인” ISSUE를 만들었다. 참석자 수정안은
이미 제거된 초대 조건을 다시 ROUTE_ISSUE로, 아직 없는 공급업체
확정 연락을 gap·confirmation으로 만들었다. 기존 A와 다른 오류
문장으로 이동했을 뿐 수정 해결을 인정하지 못해 **제품 미채택**.
시간 역할 Projection만 확장하는 방법의 우선순위를 낮춘다.
