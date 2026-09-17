# 041. Query Planner의 exact 단서와 탐색 표현 분리

기준 SHA `925f5b19b1253df87aad2688c8c7d1190ad41c85`, 시작 working tree clean.
038의 span Schema/Prompt/역할 설명 Projection, 040의 상시 LLM rewrite와
0건 뒤 단일 prompt rewrite 실패를 재시도하지 않는다. BM25는 이번
첫 후보의 변수가 아니다. RU Source/Output 계약은 수정하지 않는다.

## 최초 손실과 개발 후보 계약

039의 실제 RU 첫 출력에서 007 B `search_terms`는
`Delta 포장 승인 검토 메일`, 008 A는 `Lumen 마이그레이션 승인 메일`이다.
두 값 모두 `subject`는 비어 있고 업무 설명이 섞여 있다. 현재
`_trusted_query_anchors`가 `search_terms` 전체를 exact anchor로
분류하고 `required_user_anchors.keyword_terms`와 동적 Schema
`KEYWORD.terms[].enum`에 그대로 제공한다. Planner의 첫 출력도
그 literal 전체이며 Gmail Builder는 단일 term을 인용 phrase로
materialize했다. 이 경계에서 **원문에 있는 검색 설명**이
**문서에 반드시 정확히 있어야 할 구절**로 승격됐다.

05 Retrieval의 현행 문장도 `search_terms`를 exact anchor에 포함하므로
아래는 제품 계약 변경을 포함하는 **비활성 개발 후보**다. 같은 Run의
`search_terms`/`business_concepts`는 요청 의미·후보 발견 단서로
유지하되, provenance만으로 문자열 전체를 exact title로 확정하지
않는다. `subject`/`search_criteria_subject`, 검증된 Resource/Participant,
날짜·상태·Source는 보호한다. 초기 Gmail에서는 검증된 exact lexical
anchor가 없고 `business_concepts`가 있을 때 기존 `CONCEPT` 탐색
표현을 선택하도록 기존 출력 계약의 경계를 검사한다. 새 동의어 사전,
사례별 keyword, 첫 단어 절단, 무조건 OR를 추가하지 않는다.
`CONCEPT`는 검색 가설이지 exact target의 변경이나 외부 사실이 아니다.

이 후보가 다단어 이름을 잃는다면 `search_terms`와 `subject`만으로는
요청의 exact target을 표현할 수 없다는 반증으로 판정한다. 그때
`KEYWORD`를 아무 단어로 강제하지 말고 Query owner-local typed 역할
표현 또는 RU owner와 공유 계약 협의가 필요하다.

## 사전 비교·예산·Gate

현재 제품 코드를 바꾸기 전, 기존 038 저장 Node 기준 입력과 같은
`006/007/008/010/015/023` 여섯 원본 요청을 사용한다. 기준 결과는
`query-node-baseline6.json`을 재사용한다. 모델
`qwen3.5:9b` digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
temperature 0, seed 1729, 현재 Prompt/Schema/Fixture, 후보 각 입력
한 번, 최대 6개 첫 dispatch와 기존 bounded repair를 보존한다.
Provider READ/WRITE 0. 첫 출력·검증/보충·materialized Query·호출·토큰·
지연과 실패를 모두 ignored 결과에 저장한다.

초기 Gate: 008의 좁은 phrase가 해소되고, 007/010/023 기존 성공의
대상·Route·금지 의미가 유지되며, 015 TASK Route 누락을 lexical 성공으로
오인하지 않는가. `CONCEPT`가 Delta Plus 같은 다단어 대상을 Delta로
축소하면 실패다. 이 Gate를 넘은 후보만 007 B와 반례의 실제 RU/Route
입력을 고정하고 Query→합성 Provider READ→Evidence→Sufficiency로
연결한다. 0건 후속은 실제 관측과 기존 CHANGED round에서만 시험한다.
검증 없는 `SUFFICIENT` status 변경이나 모든 0건 재시도는 하지 않는다.

결과·채택 여부는 실행 후 같은 파일에 기록한다.

## 첫 후보 결과와 다음 구조 비교의 사전 경계

첫 후보(단순 `search_terms` exact 해제)는 6개 첫 호출 중 2개만
Node 의미-valid, 4개는 KEYWORD+CONCEPT를 함께 출력해
`QUERY_USER_CONSTRAINT_MISSING` 검증 실패였다. 4개 모두 한 번의
semantic revision 뒤에도 실패했다. 기준은 6개 중 첫 호출 5개
계약-valid, 1개 정책 보충이므로 명백한 회귀다. 008의 첫 모델 출력은
여전히 긴 KEYWORD와 별도 CONCEPT를 AND하려는 모양이었다.
`search_terms`를 prompt에서 exact라 부르지 않는 것만으로 기존
출력 책임이 바뀌지 않는다는 반증이다. 연결 실행으로 확장하지 않는다.

다음 후보는 문구 추가가 아니라 **supplied output schema의 허용 슬롯**을
분리한다. 검증된 `subject` 같은 exact lexical 값이 없는 Gmail Route에서
`search_terms` 전체는 한 `CONCEPT.concept`의 원래 탐색 목적이며,
`manifestations`만 Provider에 보내는 잠정 표현이다. 초기 `KEYWORD`
slot은 허용하지 않는다. 현재 Run의 provenance가 확인된 값만 이
목적에 사용하며 `business_concepts`는 여전히 충분성 의무다.
이렇게 하면 긴 설명 문구를 KEYWORD와 CONCEPT로 AND할 수 없다.
이는 05의 `CONCEPT`를 business_concepts에만 결합한 계약과 다르므로
채택 전 Owner 문서·후속 CHANGED·기존 checkpoint 호환성 검토가 필요하다.

동일 여섯 저장 입력에 1회씩(최대 6 첫 dispatch + 기존 bounded repair),
모델·Prompt·Schema base·시간/토큰 기록 조건은 첫 후보와 같다.
008의 `manifestations`에 Lumen 이름이 남는지, 007/010/023 기존 성공
Source와 이름이 빠지지 않는지, 015 TASK 실패가 별개로 유지되는지
검사한다. 008의 단일 개선만으로 제품 채택하지 않고 다단어 D와
007 B의 실제 producer 입력을 다음 Gate로 둔다.

두 번째 후보의 Node 계약 결과는 기준처럼 첫 의미-valid `5/6`, 정책
Calendar 보충 `1/6`이었다. 그러나 008은 `CONCEPT.concept`와
`manifestations[0]`이 모두 `Lumen 마이그레이션 승인 메일` 전체다.
007도 긴 설명을 그대로 manifestation으로 냈다. 즉 출력 kind를
바꿔도 Provider phrase가 달라지지 않았다. 015 TASK Route는 여전히
미선택으로 남는다. 동일 표현의 합성 READ를 추가 실행해 성공으로
포장하지 않는다. 이 후보도 제품 채택하지 않는다.

## 세 번째 후보의 사전 진단: 같은 호출의 typed lexical role

첫 둘의 반증은 `search_terms` 한 문자열 안의 **대상 이름과 자료 설명**을
현재 Schema가 따로 표현하지 못한다는 것이다. 다음은 별도 Agent나
제품 LLM 호출이 아니라, 같은 Query Planner 출력 계약에 넣을 수
있는 최소 owner-local 역할 슬롯이 유의미한지 확인하는 **평가 전용
독립 structured-call 진단**이다. 원문만 본 모델이 `exact_terms`와
`exploratory_terms`를 서로 다른 목록으로 낸다. exact는 현재 요청에
문자 그대로 나타난 사용자 지정 대상·제목만, exploratory는 자료
설명/업무 개념만 담는다. 원문에 없는 alias는 둘 다 허용하지 않는다.
원문 전체와 target ID/Gold/검색 문서는 모델에 넣지 않는다.

고정 입력은 007 A/B, 008 A, 010 A/B, 023 A의 기존 성공·실패 6개와
Delta Plus/2025 Atlas D 두 합성 대조, 총 8개다. 각 입력 1회,
`qwen3.5:9b` temperature 0 seed 1729, 최대 8 dispatch. 원문 및
typed 출력은 ignored 결과에만 저장한다. 다단어 Delta Plus가 Delta로
축소되거나 2025 대상이 현재 Atlas로 혼동되면 실패다. 008은 Lumen
대상과 마이그레이션/승인 메일 설명이 분리되어야 다음 단계 가치가 있다.
이 진단만 성공해도 제품 성능 개선이 아니라, 기존 Query 계획 한 호출의
Schema/normalization으로 통합 가능한지 검토하는 Gate다. 통합하면
기존 6개 Node와 B/D 입력을 다시 비교하고 실제 READ 결과를 연결한다.

첫 8회 결과는 3개만 span validator를 통과했고 5개는 평가 하네스가
`ValueError`를 던져 원출력과 토큰을 잃었다. 008의 보존된 출력은
`Lumen`뿐 아니라 `마이그레이션`·`승인`·`메일`도 exact로 분류했다.
따라서 이 결과를 제품 후보의 성공으로 보지 않는다. 실패 Trial을
지우거나 PASS가 나올 때까지 재시도하지 않는다. 평가기 결함을 고친
뒤 **별도 진단 cohort**로 동일 8개를 한 번씩 실행하여 raw/비용을
보존한다. 두 cohort를 합쳐 성공률로 만들지 않고, 008의 역할 혼동과
다단어/연도 반례가 반복되는지만 본다. Provider READ는 실행하지 않는다.

별도 cohort의 raw 보존 결과도 span-valid `3/8`이었다. 008 A는 동일하게
`Lumen`·`마이그레이션`·`승인`·`메일`을 모두 exact로 냈다. Delta Plus
문구는 하나의 exact term으로 보존했으나, 006 D는 명시 연도를
`2025 년`으로 변형해 원문 span validator에 걸렸다. 023 A는 날짜·시각·
수량까지 lexical exact term으로 섞었다. 나머지 invalid 출력에도
실제 검색용이 아닌 사용자 금지·최종 답변 요구가 탐색어로 섞였다.
따라서 이 extra-call 역할 분류를 Query Planner에 앞세우지 않는다.
평가기 결함을 수정한 두 번째 cohort는 총 8 LLM dispatch,
input/output `1,553/555` tokens, provider latency 합계 `8,576ms`다.
첫 cohort의 raw가 소실된 5회 비용은 복원할 수 없으므로 총비용 합산에서
누락 사실을 표시한다. 성공 Trial 선택을 위한 재실행은 하지 않았다.

## 0건과 후속 consumer 경계

`assess_sufficiency._deterministic_source_sufficiency`는 Evidence가 없고
READ-only이며 required source의 **실행한 Query scope/pagination**이
complete/empty이면 즉시 `SUFFICIENT`를 반환한다. 이 경로에서는
`query_attempts`의 탐색 가설 역할을 받지 않고, Sufficiency LLM도
호출하지 않는다. LLM 경로의 입력도 Query Attempt 전체가 아니라
temporal projection과 read summary만 받아 exact 범위의 정상 미발견과
탐색 표현 하나의 실패를 구분할 근거가 없다. 039의 007 B/008 A
Evidence 0→`SUFFICIENT`는 이 차이와 정합한다. 반면 현행 단위 테스트는
정말로 범위가 끝난 empty READ를 정상 no-match로 닫는 계약을 명시한다
(`test_complete_empty_scope__when_exhausted__returns_bounded_no_match`).
두 계약 테스트를 재실행해 `2/2` PASS를 확인했다. 그러므로 이 shortcut을
일괄 제거하거나 모든 0건을 `NEEDS_MORE_DATA`로 바꾸지 않는다.

## 결론·다음 계약 요구

이번 후보는 **제품 미채택**이다. 같은 6개 저장 Node 입력에서 기준
첫 semantic-valid `5/6`, 정책 보충 `1/6`, `6` LLM dispatch,
`31,908/2,217` input/output tokens, `68,226ms` provider latency였다.
단순 exact 해제는 첫 semantic-valid `2/6`, 실패 `4/6`,
`10` dispatch, `56,688/3,606` tokens, `112,523ms`로 회귀했다.
CONCEPT slot 구조 후보는 첫 semantic-valid `5/6`와 정책 보충 `1/6`,
`6` dispatch, `32,054/2,256` tokens, `64,798ms`였으나 두 실패
요청에서 Provider 구절이 여전히 장문 그대로라 정보 확보 개선이 없다.
후보 READ는 실행하지 않았으므로 first-hit/zero-hit, 사실 확보율,
Evidence/Sufficiency의 후보 전후 분모를 만들지 않는다. 기준 039의
007 B/008 A 합성 READ는 2/2 zero-hit이고 업무 근거 확보 `0/2`다.

최초 역할 손실은 RU Goal 첫 출력에서 이미 시작한다(039). 현행
RequestIntent에는 `search_terms`가 **정확 제목·고유 대상·잠정 설명 중
어느 역할인지** 표시되지 않고, 007 B/008 A의 `subject`는 비어 있다.
Query는 현행 `subject`/Participant/Resource/시간·상태를 보존할 수
있으나, `search_terms`의 하위 구절을 exact로 승격하거나 버릴 권한은
없다. RU Owner와 협의할 최소 계약 요구는 원문 span/provenance와
Route/대상이 결합된 **검증된 exact lexical identity 또는 title**과,
별도로 교체 가능한 **탐색 표현**의 역할 구분이다. 미확정 역할은
미확정으로 남겨야 하며 business_concepts·첫 토큰·동의어로 exact를
발명하지 않는다. 이 정보가 공급되면 Query Owner가 기존 KEYWORD/
CONCEPT 및 CHANGED delta에 투영하고, `SUFFICIENT` consumer에는
실제 검증한 scope와 탐색 가설의 소진 여부만 bounded 전달하는 후보를
같은 007 B/008 A·Delta Plus·2025 Atlas·성공 입력에서 평가한다.

015 TASK Route 미선택은 별도 route/query selection 실패다. 이번
lexical 후보로 개선되지 않았고, TASK 무조건 READ 보정도 하지 않았다.
BM25는 040의 공통 corpus 원문 `12/12`, 매번 rewrite `11/12` 결과를
유지한다. 이번에는 동일 실제 READ 후보 풀이 없어서 제품 reranking
비교를 새로 하지 않았다. LangSmith·실제 계정 Provider 검증은 제품
후보가 Gate를 넘지 못해 수행하지 않았으며, 이전 SHA Trace를 새
후보의 검증으로 재사용하지 않는다.

| 실패 유형 | 시도 방법 | 조건·근거 | 결과·회귀 | 판단 | 재시도 조건 |
| --- | --- | --- | --- | --- | --- |
| 설명어가 exact phrase로 승격 | `search_terms` exact 해제 | 동일 Node 6입력 | 4/6 anchor validator 실패, 호출 10 | 기각 | 역할이 검증된 입력/출력 계약 |
| 설명어가 exact phrase로 승격 | `CONCEPT` slot 분리 | 동일 Node 6입력 | 5/6 첫 valid이나 긴 phrase 지속 | 기각 | manifestation 역할을 신뢰 가능하게 구분 |
| 정확 대상/탐색어 혼동 | extra-call typed lexical role | 8입력 두 별도 cohort | 각 3/8 span-valid, 008 의미 혼동 | 기각 | RU provenance/role 개선 또는 다른 구조 증거 |
| 0건 false `SUFFICIENT` | shortcut 제거 여부 진단 | 저장 007 B/008 A와 no-match 테스트 | 정상 미발견을 구별할 역할 부재 | 보류 | Query scope/가설 역할을 consumer에 전달 |
