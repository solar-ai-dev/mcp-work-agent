# 042. RU lexical role Typed State producer Gate

기준 SHA `9cfe70d0173b5b427601fb5e16558addc07eb7de`, 시작 working tree clean.
041의 Query Prompt/slot 변경과 별도 extra-call 분류는 기각된 조건으로
유지한다. 이번에는 **기존 RU identify_goal의 한 호출**에 lexical role
후보를 함께 출력하는 개발 스키마만 비교한다. Query 제품 Prompt/코드,
실제 Provider, BM25는 이 Gate 전에 변경·실행하지 않는다.

## 가설·계약과 비교 조건

현재 RequestGoal 슬롯은 `search_terms`/`business_concepts`를 보존하지만
검색 표현의 신뢰 역할을 구별하지 않는다. 후보 출력의 bounded
`lexical_roles`는 `{role, value}` 배열이다. 역할은 `EXACT_ENTITY`,
`EXACT_TITLE`, `EXPLORATORY`이고 원문 그대로의 span만 허용한다.
명시적 날짜/기간·시간·상태·Source는 기존 typed constraint 소유이며
lexical 배열에 중복하지 않는다. 사람/필요한 답·금지 지시도 lexical
검색어가 아니다. 기존 Goal/constraints/Source/Output 의미를 축소하거나
추가 실행 권한으로 해석하지 않는다. 처음에는 스키마 역할 설명만
추가하며 RU Prompt 본문·Source/Output 입력은 그대로 둔다. 검증된
provenance는 여전히 RU finalize의 책임이고 모델 span 선언 자체가
권위는 아니다.

고정 입력 12개: 007 A/B, 008 A/B, 010 A/B, 023 A/B,
Delta Plus(007 D), 2025 Atlas(006 D), 정확 제목 요청과 설명형 검색
요청(후자 둘은 평가용 합성 입력). 8개 A/B의 기존 Goal-only 출력은
039 저장 baseline을 재사용하고 D/합성은 같은 입력의 과거 paired
baseline이 없다고 표시한다. 합성 원문은 평가 결과에만 저장한다.
모델 `qwen3.5:9b` digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
temperature 0, seed 1729, 동일 RU Goal Prompt hash
`98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa`.
변수는 supplied output schema의 새 역할 필드 하나다. 첫 cohort는
입력당 첫 structured inference 1회, 최대 12 dispatch. 동일 요청의
새 Trial을 성공 Trial로 대체하지 않는다. 첫 cohort가 아래 Gate를
전부 넘으면 별도 12회 반복으로 일관성을 평가한다. Provider READ/WRITE
0. raw 출력·입출력 토큰·지연·실패는 ignored `evaluation/results/`에 저장한다.

Gate는 Schema-valid와 의미-valid를 분리한다. 모든 exact value가
현재 요청의 정확한 span이고, 다단어 `Delta Plus`를 `Delta`로
축소하지 않으며, `2025`는 lexical role이 아니라 기존 DATE로
남아야 한다. 007/008에서는 고유 대상과 메일 설명이 분리되고,
010의 메일 본문 명령·요약 지시, 023의 Action 날짜·시간·수량이
검색어로 섞이지 않아야 한다. 정확 제목은 `EXACT_TITLE`, 설명형
요청은 과잉 exact 없이 `EXPLORATORY`여야 한다. 기존 A/B Goal의
Source/Output 관련 의미에 명백한 누락·미요청 효과가 늘면 실패다.

이 Goal producer Gate를 넘은 경우에만 현재 RU의 나머지 호출에
전달할 projection과 finalized Typed State 계약을 후보 구현하고,
같은 입력의 Source/Output 회귀를 비교한다. 그 Gate까지 통과한 경우에만
Query owner의 deterministic initial materialization과 관측 실패 후
기존 Retrieval LLM 1회 expansion을 인접 READ에 연결한다. Query
연결 전에는 기존 039 A/B의 합성 Provider 결과를 제품 후보 효과로
계산하지 않는다. 후단 후보는 같은 요청·Route·Provider fixture에서
Resource/fact 확보, false SUFFICIENT, 성공 회귀, 호출·READ·토큰·
지연을 paired로 기록한다.

기각 조건: 이 역할 분리도 041처럼 장문 exact나 명시값 손실을
반복하면 Prompt 문구만 바꾸어 재시도하지 않는다. 비용만 늘고
Source/Output 또는 검색 정확도가 악화되면 활성 제품 코드를 채택하지
않는다.

## 결과

첫 후보는 기존 `search_terms` 슬롯과 top-level `lexical_roles`를
동시에 반환했다. 첫 호출 12/12 완료, 스키마·원문 span valid `11/12`,
그러나 역할 의미-valid는 `4/12`(Delta Plus, 2025 Atlas, 합성 정확
제목, 합성 설명 검색)였다. 007 A는 장문 설명을 EXACT_ENTITY로,
007 B는 Delta를 포함한 장문을 EXPLORATORY 하나로 뭉쳤다. 008 A는
`Lumen 마이그레이션`과 `승인 메일`을 둘 다 EXACT_ENTITY로,
008 B는 Lumen을 설명형 한 구절에 묻었다. 010 A는 Harbor를
EXPLORATORY에 묻고, 010 B는 답변 대상인 패치 업무를 탐색어에 넣었다.
023 A는 요청에 없는 `8 월 8 일 상태 점검`을 EXACT_TITLE로 만들어
span 검증도 실패했다. 023 B는 Output 일정의 상태 점검을 SOURCE
탐색어에 섞었다. Schema-valid `11/12`를 업무 의미 성공으로 세지
않는다. 추가된 Goal 한 호출당 모델 비용 합계는 12 dispatch,
input/output `33,104/2,024` tokens, provider latency `77,831ms`다.
동일 입력의 기존 039 baseline 8건에서 `search_terms`가 장문이던
007 A/B·008 A 중 2건은 새 schema에서도 올바른 역할로 분리되지
않았다. 기존 Source/Output LLM은 이 후보에서 실행하지 않았다.
후속 Query 연결과 반복 Trial로 확장하지 않는다.

### 두 번째 구조 후보 사전 선언

첫 후보는 기존 undifferentiated `search_terms`와 typed 역할을 **중복
출력**시켰다. 같은 긴 구절을 두 군데에 복사하는 경쟁을 없애는
구조 실험이다. 기존 Goal schema의 `constraints.search_terms`만
`constraints.lexical_terms[{role,value}]`로 **대체**한다. 원래
`business_concepts`, person, subject, period, status, Source/Output 책임은
그대로 둔다. RU Prompt의 해당 슬롯 설명만 새 출력 계약에 맞춰
교체하는 것은 schema와 불가분한 변경이다. Query Planner Prompt는
바꾸지 않는다. 모델은 여전히 기존 Goal 호출 한 번만 한다.

고정 12입력, 동일 모델·seed·Prompt 공통 부분·평가기, 입력당 1회
첫 호출, 최대 12 dispatch. 새 Goal raw 출력·용량·지연은 별도
ignored 결과에 보존한다. 평가기에서는 legacy Source/Output 입력
형태 확인용으로 lexical value들을 `search_terms`에 투영한 사본을
만들되 역할 raw를 버리지 않는다. 이 투영은 제품 채택이 아니다.
Gate는 첫 후보와 동일하고, 최소 007 A/B·008 A/B·Delta Plus·정확
제목에서 역할이 안정되어야 한다. 통과하지 못하면 Prompt 문구만
재수정하지 않고 RU 출력 책임 또는 모델 한계를 기록해 중단한다.

## 두 번째 후보 결과와 판정

`search_terms`를 역할 배열로 대체해도 첫 호출 12/12는 끝났지만,
스키마·원문 span valid `11/12`, 역할 의미-valid는 `3/12`(023 B,
합성 정확 제목, 합성 설명 요청)였다. 007 A/B는 `Delta`와 자료 설명을
나누지 못해 장문 전체를 EXPLORATORY로 냈다. 008 A도 `Lumen`이
설명에 묻혔고, 008 B는 사용자가 정확한 제목을 지정하지 않았는데
`Lumen 데이터 이관 건의 승인 안내`를 EXACT_TITLE로 승격했다. 010 A/B도
`Harbor`가 EXPLORATORY 안에 묻혔다. 023 A는 Kestrel exact를
놓쳤다. Delta Plus 반례에서는 `Delta Plus 포장 승인 건` 전체가
EXACT_ENTITY라 이름/설명의 경계가 틀렸다. 2025 Atlas 반례는
`2025 년 Atlas 출시 당시 출고일`을 lexical EXPLORATORY로 만들어
명시 연도를 중복·변형했고 span validator도 실패했다. 합성 정확 제목과
설명 요청은 각각 올바른 역할을 반환했지만, 성공한 두 합성 입력만으로
실제 요청의 공통 의미 보존을 주장하지 않는다.

기존 Goal 의미도 고정되지 않았다. 039의 008 A/B 첫 출력에는 없던
`additional_constraints.scheduled_date`(A)와 `title`(B)이 이 후보에
생겼다. 이는 자료 본문의 시작 시각을 사용자가 요청한 Action 날짜로,
설명형 문구를 정확 제목으로 혼동할 위험이다. Goal Producer Gate에서
이미 실패했으므로 Source/Output atomic LLM을 실행하지 않았고,
Source/Output 회귀 없음이라고 판정하지 않는다. 다른 두 후보의
Source/Output 성공 사례를 끼워 넣지도 않는다.

두 번째 후보 12 dispatch의 input/output은 `32,180/1,806` tokens,
provider latency 합계 `60,249ms`다. 동일 8개 A/B 요청의 저장
039 baseline Goal 첫 호출과 비교하면, baseline `8` dispatch,
`20,194/1,158` tokens, `33,385ms`; 병렬 후보 `8` dispatch,
`22,090/1,571` tokens, `60,547ms`; 대체 후보 `8` dispatch,
`21,474/1,301` tokens, `42,991ms`다. 모델·seed·RU Goal Prompt
공통 부분·요청은 같지만 스키마 후보가 다르고, 작은 표본의 latency
차이는 안정적 성능 추정치가 아니다. D·합성 네 입력에는 같은 입력의
과거 Goal baseline이 없어 이 paired 비용 합계에 넣지 않는다.

**제품 미채택.** 두 설계 모두 기존 RU 호출 수를 늘리지 않았으나,
실제 업무 입력에서 exact/exploratory를 안정적으로 보존하지 못했다.
반복 Trial, RU finalize Typed State 채택, deterministic initial Query,
관측 실패 후 Retrieval LLM expansion, Query→합성 READ, Evidence와
Sufficiency 연결은 Gate 미통과로 실행하지 않았다. 따라서 후보의
Resource/fact 확보율·false SUFFICIENT·READ 비용 분모는 없다.
기준 039의 연결 6입력 중 자료 확보 `4/6`, 007 B/008 A는 `0/2`라는
기존 관측만 유지한다. 이 수치를 새 후보의 검색 개선률로 오인하지
않는다.

| 실패 유형 | 방법 | 조건·근거 | 결과·회귀 | 판단 | 재시도 조건 |
| --- | --- | --- | --- | --- | --- |
| 긴 검색 구절의 exact/탐색 역할 혼동 | 기존 `search_terms`와 역할 병렬 출력 | RU Goal 동일 호출·12입력 | 의미-valid 4/12, 023 A 가짜 exact 제목 | 기각 | 역할 중복이 아닌 출력 책임 검토 |
| 같은 역할 혼동 | `search_terms`를 typed 역할로 대체 | RU Goal 동일 호출·12입력 | 의미-valid 3/12, 008 B 가짜 exact 제목·실행 필드 혼입 | 기각 | RU 책임 분해 또는 다른 모델/계약의 독립 근거 |

다음 선택은 Prompt 표현을 세 번째로 바꾸는 것이 아니다. Goal이
검색 단서뿐 아니라 업무 완료 조건과 실행값을 동시에 생성하는
출력 책임이 이 역할 구분을 방해하는지, Source/Output의 현재 분해와
함께 먼저 재검토해야 한다. 현행 모델·계약에서 신뢰 가능한 Typed
lexical role이 없으면 Query를 결정적으로 생성할 권위도 없다.

고정 요청 manifest SHA-256은
`25d56a30aca2436085ffe1c9b1dd54b1e10b0814dd28d968d75ec104bf95a6ae`.
병렬 후보 Prompt/Schema hash는
`98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa` /
`412e7fa5eb756e1a71c5a6d44fa54aa12ee02096606202313db33ca4a6cf75e5`.
대체 후보는
`9ed796816a199b5d87091a2c49cbc3503f9120d446edd9ebd3c6b172b3372752` /
`88103e121571418b6da813adfa5e6ff1724ec5ef25c22fd64b56f1ed9023808d`.
상세 raw 출력은 ignored
`evaluation/results/ru-lexical-role-20260918/goal-first12.json` 및
`goal-replacement12.json`에 있다. 평가 스크립트는 raw·실패·비용을
저장했고, `ruff check`/format check 및 기존 RU Goal 단위 테스트
`99/99`가 통과했다. 이는 제품 의미 개선 검증이 아니라 현재 제품의
정적·계약 회귀 확인이다.
