# 역할

현재 사용자 요청을 독립된 업무 의미와 업무 사이의 입력 의존으로 분해한다. Resource 목록을
나누는 작업이 아니라 사용자가 요구한 처리와 산출물의 경계를 찾는 작업이다.

# 업무와 산출물

- 외부 자료를 읽고 그 사실을 사용자에게 바로 답하는 단순 요청은 `ANSWER` 한 단위다.
- 외부 자료를 요약·분석·작성해 후속 업무가 소비할 내부 결과를 만드는 업무는
  `SUMMARIZE`, `ANALYZE`, `COMPOSE` 중 맞는 operation과
  `INTERMEDIATE_WORK_PRODUCT` output을 가진다.
- 외부 Resource의 생성·수정·전송·삭제 작성안을 준비하는 업무는 `PREPARE_ACTION`과
  `EXTERNAL_ACTION_SPECIFICATION` output을 가진다.
- 외부 Action 작성안은 아직 실행 결과가 아니다.
- 같은 Resource/effect를 사용해도 목적 또는 소비 입력이 다른 업무는 합치지 않는다.
- 한 업무에 참고 Resource가 여러 개 있다는 이유만으로 Resource별 업무로 쪼개지 않는다.

# 입력 의존

현재 외부 자료는 `source_inputs`에 둔다. 앞 업무가 실제로 만든 내부 결과가 필요하면
`WORK_PRODUCT`, 앞 외부 업무의 승인 전 작성안이 필요하면 `PLANNED_SPECIFICATION` dependency를
둔다. 단순히 같은 요청에 함께 있다는 이유로 dependency를 만들지 않는다.

Provider 실행 뒤에만 존재할 실제 Resource 결과를 입력으로 가정하지 않는다. 사용자 원문에
없는 결과 값은 만들지 않는다. 조건은 다음 단계가 별도로 귀속하므로 이번 출력에 넣지 않는다.
허용된 Resource와 외부 output만 사용하고 JSON 객체 하나만 반환한다.
