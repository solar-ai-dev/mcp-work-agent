현재 요청에 필요한 기존 자료를 source_candidates에서 선택한다.
사용자 원문과 선택 identity가 기준이며, 새로 만들 결과와 읽어야 하는 자료는 다르다.
source_reads 객체에는 필요한 Resource 이름만 key로 쓰고, 각 자료에서 필요한 정보,
대상 범위(target_scope), 적용 WorkUnit을 기록한다. 특정 기존 대상은 SINGULAR,
조건에 맞는 조회는 CRITERIA다. 필요하지 않은 Resource key는 생략한다.
Tool/Query/Output/실행 여부는 결정하지 않는다. 지정된 JSON 객체만 반환한다.
