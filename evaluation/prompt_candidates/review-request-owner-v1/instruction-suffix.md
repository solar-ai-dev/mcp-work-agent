# 평가 후보: 요청 해석의 재검토

user_request는 현재 Run의 사용자 원문이다. request_intent는 그 원문에 대한 현재 해석이며 원문을 대체하지 않는다. 제공된 사용자 정정과 선택은 기존 권위 범위에서 유지한다.

request_intent 자체의 의미가 원문과 불일치한다고 판단하면 REQUEST_SEMANTICS_ISSUE를 사용하고, 해당하는 현재 work_unit_ids와 semantic_field_paths를 고른다. 원문이나 수정된 의도를 새로 작성하지 않는다. 원문과 의도가 일치하지만 제안된 값이 잘못된 경우에는 기존 Planning ISSUE이며, Tool capability 문제와 외부 근거 부족은 각각 기존 책임으로 구분한다.

이 finding은 Request Understanding에 재판정을 요청하는 관측이지 의미 수정·실행 허가가 아니다. 구체적인 불일치가 없으면 기존처럼 findings를 비운다.
