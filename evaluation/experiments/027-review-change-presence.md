# 027. 변경 path의 값 존재 여부 보존

기준 `53842ae6`. 026은 네 대조에서 의미 개선을 보였으나, 제거된
`attendees`와 실제 JSON `null`을 같은 값으로 표시했다. 이전/현재
인자값의 존재를 `present`와 실제 `value`로 분리하는 것만 변경한다.
RequestIntent·Evidence·Plan·Prompt source·output schema·모델은
026과 같다. absent에는 `value`를 만들지 않는다. 일대일 route
매칭이 아니면 projection하지 않는 조건도 유지한다.

026의 수정 날짜·금지/미수정 날짜·금지 4개를 각 1회, 최대 4 LLM
호출로 직렬 비교한다. temp0/seed1729/동일 digest, Provider I/O 0.
모든 수정 issue가 해결되고 새 허위 finding이 없어야 하며, 미수정
ISSUE는 보존돼야 한다. 모델 설명에서도 삭제를 null 값이라고
잘못 확정하지 않아야 한다. 모든 Trial을 보존한다. 통과해도
compiled 순환과 다른 입력 반례 전에는 제품 채택하지 않는다.

결과와 채택 판단은 Trial 후 기록한다.

4회 모두 첫 structured inference 완료, repair/timeout 0. 수정 날짜·금지의
과거 issue 각 3개가 RESOLVED, 현재 finding 0. 미수정 두 입력의 issue
각 3개가 UNRESOLVED, 날짜/금지 위반 ISSUE 1개씩. 참석자 삭제는
`present:false`로 설명해 `null`과 구별했다. 평균 입력은 약 14.3k,
추가 출력은 해결 상태 근거 때문에 약 0.2~0.6k tokens다.
ignored 결과는 `evaluation/results/review-change-presence-20260917/`.
유력 후보로 제품 연결을 시도하되 compiled 순환 전 채택 완료로 보지 않는다.
