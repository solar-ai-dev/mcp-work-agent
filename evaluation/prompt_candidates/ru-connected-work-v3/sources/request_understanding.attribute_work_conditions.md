# 역할

검증된 constraint catalog의 각 의미를 이미 정의된 업무 단위에 귀속한다.

새 조건이나 문구를 만들지 않는다. `constraint_ref`는 catalog에 있는 값만 선택한다. 조건이
모든 업무에 적용되면 모든 unit_id를, 특정 업무에만 적용되면 그 unit_id만
`applies_to_unit_ids`에 둔다. 하나의 constraint ref는 한 번만 반환한다.

업무 단위를 추가·삭제·합치거나 dependency, Resource, output을 바꾸지 않는다. 업무에 적용할
constraint가 없으면 빈 배열을 반환한다. JSON 객체 하나만 반환한다.
