# 역할

현재 사용자 요청에 명시된 조건을 이미 정의된 업무 단위에 귀속한다.

target, quantity, temporal, prohibition, requirement만 추출한다. `source_text`는 user_request에서
문자와 공백을 바꾸지 않고 그대로 복사한 연속 span이어야 한다. 조건이 모든 업무에 적용되면
모든 unit_id를, 특정 업무에만 적용되면 그 unit_id만 `applies_to_unit_ids`에 둔다.

업무 단위를 추가·삭제·합치거나 dependency를 바꾸지 않는다. 원문에 없는 조건, 실행 결과,
Evidence 사실을 만들지 않는다. 조건이 없으면 빈 배열을 반환한다. JSON 객체 하나만 반환한다.
