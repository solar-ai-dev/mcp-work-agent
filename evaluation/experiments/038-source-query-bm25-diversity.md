# 038. Source–Query 검색 다양화와 BM25 순위 비교

기준 SHA `fab514a2`, clean tree. 원본 Dataset·Provider snapshot·Gold는
변경하지 않는다. 036의 Source owner 교정은 합성 진단일 뿐이며, 037의
fact-kind 출력 후보는 복수 Source 누락으로 기각됐다. 이번에는 그 출력을
제품에 되살리지 않는다. 사용자 의미·권한·확정/미확정·원문을 보존하고,
순위와 후보 획득을 별도 축으로 측정한다.

## 고정 집합과 첫 비교 예산

파생 요청은 `evaluation/derived_queries/source-query-diversity-v1.json`에
원본 Case ID와 함께 고정한다. 원본 업무 6개(Atlas 006, Delta 007,
Ion 005, Lumen 008, Harbor 010, Kestrel 023), 업무당 기본 A/의미 동등 B/
도전 C/오인 방지 D의 24개 입력이다. B는 원본의 대상·출처·시간·금지·
요청 효과를 사전 검수했다. C는 확정 Gold가 아니라 발견/미발견 및 잘못된
확정 여부를 본다. D는 별도 대상 또는 미확정 사실을 실제 근거와 대조한다.
원본/변형을 독립 업무 수로 과장하지 않는다. 후보 결과를 보고 라벨·정답
ID를 바꾸지 않는다. 평가 필드와 대응 ID는 제품 LLM 입력에 주지 않는다.

첫 단계는 6개 pack의 실제 Provider snapshot Resource와 snapshot의 공통
방해 Resource 10개를 같은 버전으로 정규화해 만든 **고정 순위 진단 풀**이다.
이 풀은 실제 Query/READ 산출물로 주장하지 않는다. Pack별 고정 풀에서
Top-K=4, 동일 후보·동일 요청·동일 `RagScoringConfig`로 현행 substring
lexical 점수와 BM25 점수만 비교한다. Explicit Resource 강제 보존,
source anchor·temporal·participant 이유 점수는 바꾸지 않는다.

BM25 개발 후보는 기존 공백/구두점 전처리로 문서와 Query를 토큰화한다.
`k1=1.2`, `b=0.75`, `idf=log(1+(N-df+0.5)/(df+0.5))`, keyword 기여는
`keyword_max_score * raw/(raw+1.5)`로 제한한다. 이는 substring→token
일치 변화도 포함하므로 결과에서 전처리 효과를 별도 기록한다. 형태소·
문자 n-gram은 첫 A/B에 섞지 않는다. BM25는 선택 Resource·권한·출처·
충분성 판단을 대체하지 않는다.

비교 1은 A/B/C/D 24개 요청의 **원문만**으로 순위 민감도를 진단한다.
이 입력은 실제 RU State가 아니므로 제품 업무 성공률로 세지 않는다.
비교 2는 유력 후보에 한해 A/B의 변형 원문에서 현행 RU가 만든 실제 State와
현행 Query/READ의 후보 풀로 같은 A/B ranking을 paired 평가한다. B에
원본 A의 anchor·constraints를 끼워 넣지 않는다. C/D는 기본 성공률과
분리해 단계적으로 연결한다. Source 누락과 rank 누락을 분리하고, 풀에
필요 자료가 없는 경우 rank 실패로 세지 않는다.

1차 후보는 pure Python BM25, LLM/Provider 0회, Top-K=4로 전 입력 1회.
기록·직렬화 preflight 후 시작하고 실패 Trial도 저장한다. 채택 조건은
기본·B의 관련 근거 Top-K 보존 증가 또는 동일 보존에서 방해 자료 감소,
기존 성공·반박 자료·선택 Resource의 회귀 없음이다. C의 미발견은 단독
기각 사유가 아니고 D의 무관 자료 확정은 실패다. 후보 풀 전체가 K 안이면
순위 판별 불가로 표시한다. 유력한 경우에만 실제 RU/READ 인접 연결과
반복 1회를 직렬 수행하며, 매 수정마다 92개 E2E는 돌리지 않는다.

## 사전 등록한 추가 순위 진단

1차 실행 후 코드를 확인한 결과 실제 RAG는 최대 24개를 통과시키고,
Evidence Selector의 LLM 입력은 최대 12개다. 앞서 고정한 Top-4는
좁은 Context에 대한 민감도 진단이지 production Top-K가 아니다.
따라서 원래 24개 요청·동일 후보·동일 정답을 유지하고 Top-12를 별도
진단으로 1회 실행한다. 1차 Top-4 수치를 이 결과로 교체하지 않는다.
원본 pack의 풀은 12~18 segment이므로 일부는 전부 Context에 들어가
순위 판별력이 없을 수 있다. 실제 READ에서 선택된 상위 24개가
어떤지와는 별개로 기록한다.

## 결과·결정

1차 rank-only 진단은 24/24 입력을 모두 저장했고 계산 오류 0이다.
원본 6업무에서 A/B 각 6입력, 확정 대상 각 8개다. Top-4 대상 보존은
현행·BM25 모두 A `8/8`, B `8/8`; Top-12도 양쪽 모두 A `8/8`,
B `8/8`로 **0%p 차이**다. D의 확정 대상 2개도 양쪽 모두
Top-4/12 `2/2`다. C에는 확정 Gold가 없으므로 적중률을 계산하지
않았다. Delta A/B에서 정확한 Delta thread는 현행 3위에서 BM25
1위로 바뀌었다. 그러나 같은 원본 업무의 변형 2개이며 근거 확보율
개선 2건으로 세지 않는다. C의 Atlas/Ion/Kestrel은 1위 Source가
바뀌어 독립적인 의미 판정 없이는 득실을 확정할 수 없다.

운영 Graph는 RAG Top-24, Evidence 선택 LLM 입력 최대 12개다.
이번 pool은 12~18 segment여서 Top-12에 모두 들어가는 업무도 있다.
Top-4는 작은 Context의 순위 스트레스 진단이고 production 경로의
근거 잔존율을 대체하지 못한다. 이번 비교는 원문 surrogate·합성 고정
pool이며 RU/Query/실제 READ/정보 충족/후단 성공은 측정하지 않았다.
READ 0, LLM 0, WRITE 0이며 토큰·Provider 지연도 0이다. 로컬
순위 계산 시간은 결과 JSON에 각 Trial별로 남겼고 서비스 지연과
직접 비교하지 않는다. 원시 결과는 ignored
`evaluation/results/bm25-diversity-20260917/rank-only*.json`이다.

이 결과만으로 BM25를 기본 순위기로 채택하지 않는다. 현재 관측된
개선은 한 업무의 선두 순위이고, 기본/의미 동등 요청의 작은 Context
보존·확보 이득은 0이다. Source 선택 / 후보 확보 / Top-K 보존 /
정보 충족 / 충분성 오류 / READ·LLM·토큰·지연 / 후단 사용은
계속 별도 축으로 기록한다.

## Query 재표현 진단의 고정 출발점

과거 동일 corpus의 Core-008 실제 RU/Route 입력에서 첫 Gmail Query는
`"Lumen 마이그레이션 승인 메일"`의 긴 phrase로 materialize돼 합성
READ 0건이었다. 이 기록은 이전 SHA의 producer 입력이므로 현재 Query
경로의 재현 증거가 아니다. 동일 저장 upstream과 동일 합성 Provider를
현재 checkout에 한 번 연결해, 첫 Query·무결과 이후 follow-up 진입·
실제 READ 수를 확인한다. 재현되면 route-bound 무결과를 기존 round에
넣고 최대 두 대안 가설이 필요한지 검토한다. 새 Query가 없는데
과거 조회 결과만 바꿔 붙이지 않는다. 사전 예산은 Retrieval LLM 최대
기존 Run budget, Provider는 합성 READ만, 재실행 1회다. 이 한 사례만
고치는 규칙은 채택하지 않고 다른 A/B·반례와 연결해 판단한다.

재현 결과, dependency만 후속 대상으로 바꾼 제품 후보는 실제로 두 번째
합성 READ를 실행했으나 최초 긴 KEYWORD를 유지하고 CONCEPT를 AND로
추가해 또 0건이었다. `1→4` provider dispatch, `1→2` READ,
`10.9→36.9`초 provider 지연, Evidence `0→0`이다. 이 후보는
Source 상세/탐색 Route 결속 자체는 고쳤지만 검색 표현의 최초 손실을
해결하지 못하므로 **기각하고 제품·Canonical diff에서 제거**했다.
원시 결과는 `query-008-current.json`과 `query-008-dependency-followup.json`이다.

다음 비교는 initial Query에서 검증된 사용자 검색 문구를 통째로
Provider phrase로 고정하는 계약이 과한지 본다. 현재 runtime schema는
`required_user_anchors.keyword_terms`의 전체 문자열만 KEYWORD 값으로
허용하지만, 후단 semantic validator는 현재 Run anchor의 포함 문자열을
허용한다. 이 차이를 하나의 계약 후보로 비교한다. 검증된 원문 내 연속
span만 허용하고 새 alias·사용자 사실을 만들지 않는다. 모델에게 특정
단어를 강제하지 않는다. 사전 Node 집합은 저장 upstream의 Core
006/007/008/010/015/023 6개, 현재 9B digest·temperature 0·seed
1729, 기준/후보 각각 1회, Provider READ 0, 최대 12 첫 dispatch와
bounded repair만. 첫 모델 출력·Schema 통과·사용자 의미·Query 범위와
호출 비용을 분리한다. 기존 성공 006/007/010/023의 과잉 완화·잘못된
대상 확정을 회귀로 본다. 유력하면 008 Query→합성 READ를 연결하고,
여전히 0건이면 먼저 검색 literal 계약과 Source 내용 대응을 다시 본다.

Schema-only 후보 6건은 기준과 동일하게 Node 계약 판정 `5/6` 첫
의미 유효, 1건 policy 결정 보충이었다. Core-008의 실제 materialized
Query도 긴 phrase 그대로였고 합성 READ 0건이다. 따라서 Schema 허용
확대만으로는 획득 이득이 없었다. 다음 후보는 같은 span-허용 Schema에
원문 내 검색 구간과 명시적 제목의 역할 차이를 Prompt 입력 계약으로
설명한다. 이 단계의 변인은 Prompt이며, 기준 6건·Schema-only 6건
원시 결과와 별도 결과로 둔다. 동일 저장 upstream 6건 1회씩, 최대
6개 첫 dispatch와 bounded repair, Provider READ 0; 이후 유력하면
006/007/008/010의 합성 연결을 각각 1회 직렬 확인한다. 후보 첫
출력 전부 기록하도록 평가기 저장 경로를 보완했다. 특정 단어·Source
강제나 원문 밖 확장어는 제품에 추가하지 않는다.

Schema+Prompt 후보에서도 Core-008은 긴 phrase를 유지했다. Core-023은
첫 출력에서 정책 Calendar Route 누락이 기준보다 커졌지만 결정적 보충
후 출력은 검증됐다. 같은 문구 접근을 반복하지 않고, 기존 State의
`search_terms`(탐색 설명)와 `subject`(명시 제목) 역할이 Query의
`required_user_anchors.keyword_terms`에서 합쳐지는 경계를 비교한다.
다음 후보는 현재 값·provenance를 그대로 두고 `keyword_roles`라는
작은 Projection에 기존 필드 역할만 나타낸다. 새 anchor나 동의어를
생성하지 않으며 validator의 current-run span 검증을 유지한다.
동일 Node 6입력 1회, 유력 시 008 합성 READ 1회, 실패도 저장한다.

필드 역할 Projection 후보도 첫 Node 계약 판정은 기준과 동일한 `5/6`
첫 의미-valid, 1건 정책 보충이었다. 008의 첫 KEYWORD는 여전히
`Lumen 마이그레이션 승인 메일` 전체였다. `match_mode`만 `PHRASE→ANY`로
바뀌었으나 단일 여러 단어 term은 Gmail Builder가 그대로 인용한 하나의
phrase가 된다. 해당 QUERY의 합성 READ 이득은 없다. 007도 긴 설명
literal을 유지했고, 023은 정책 Calendar 세 route를 첫 출력에서
빠뜨려 보충 의존도가 증가했다. 검색 표현·근거 확보가 개선되지 않아
Schema/Prompt/Projection 제품 후보를 모두 기각한다. 같은 Prompt
문구·필드 투영을 다시 반복하지 않는다. 다음 방법은 RU가 `search_terms`에
무슨 의미를 확정했는지, Query가 한 가설에서 Source 발견 단서를 몇
개 표현할 수 있는지, Source/Route가 누락되는지를 함께 살펴야 한다.
이는 이번 후보의 성능이라고 가정하지 않는다.

## 이번 사이클 판정과 재시도 조건

| 집합 | 원본 업무/변형 | 현행 Top-4 대상 보존 | BM25 Top-4 | Top-12 | 판단 |
| --- | ---: | ---: | ---: | ---: | --- |
| A 기본 | 6/6 | 8/8 | 8/8 | 양쪽 8/8 | 획득/선별 개선 0%p |
| B 의미 동등 | 6/6 | 8/8 | 8/8 | 양쪽 8/8 | 획득/선별 개선 0%p |
| C 도전 | 6/6 | Gold 없음 | Gold 없음 | Gold 없음 | 1위 변경 3/6, 정오 미판정 |
| D 반례 | 6/6 | 확정 대상 2/2 | 2/2 | 양쪽 2/2 | 나머지 4개는 금지 확정 여부 미판정 |

이 수치는 source-backed **고정 진단 풀**과 raw-text surrogate의 순위다.
실제 RU·Query·READ 결과의 후보 확보율, Evidence Selector의 정보
충족률, 후단 업무 성공률이 아니다. production RAG Top-24와 LLM Context
12 중 작은 4를 따로 본 진단이다. 원본 6업무를 24업무로 계산하지 않는다.

Query Node 저장 입력 6개에 기준/Schema-only/Schema+Prompt/
Schema+Prompt+필드 역할 후보를 각 1회씩 직렬 실행했다. 각 arm은
`5/6` 첫 출력 route·계약 판정, 1건 정책 route 결정 보충이다.
**이 지표는 검색어의 의미 정확도나 자료 확보율이 아니다.** 015의
TASK 누락도 route 진단의 “선택한 route 계약 유효”로 가려지므로
별도 실패다. 008의 실제 합성 연결은 기준·Schema-only 모두
Gmail 검색 1회, 결과 0, Evidence 0이었다. 필드 역할 후보의 첫
KEYWORD도 동일 긴 문구였으며 단일 term의 `ANY`는 Builder에서
인용 phrase가 되어 획득 개선을 기대할 수 없다. 새 Prompt 후보가
실제 source-backed 의미 성능을 개선했다는 증거가 없고 023의 첫
policy omission이 커져 모두 기각했다.

초기 순위 후보 구현은 검증 후 활성 제품 모듈에서 제거하고
`evaluation/bm25_rank_candidate.py`로 격리했다. 이 비활성 구현과
앞서 제품 모듈 안에서 실행한 동일 BM25 후보의 24개 순위 ID는 Top-4와 Top-12에서 모두 동일하게
재현됐다(`0/24` 차이). 평가용 Query Node runner는 성공한 첫
structured output도 ignored 결과에 저장하도록 개선했다. 원시
결과는 로컬 ignored `evaluation/results/bm25-diversity-20260917/`에
남아 있으며 원문·Resource 본문을 commit하지 않는다.

**제품 채택 없음.** 확인된 공통 경계는 긴 `search_terms`를 검색용
정확 phrase로 소비하는 문제와 필수 상세 Source의 미조회가 discovery
Route의 빈 결과와 후속 Query에 연결되지 않는 문제다. 이 두 문제를
단일 Prompt 문구나 route 재진입만으로 덮으면 비용만 늘었다. 다음
방법은 RU가 `search_terms`를 검색 가설/정확 literal 중 무엇으로
확정했는지 검증하고, 구조적으로 대안 Query의 identity·실효 조건·
Provider materialization과 실제 후보 확보를 함께 비교해야 한다.
015의 TASK route 미조회도 별도 실패로 남긴다.

034와 015를 같은 검색어 문제로 합치지 않는다. 034 저장 Run은
`required_information`의 Task item 사실 owner가 TASK_LIST에 결속된
RU Source 문제였고, 036에서 Source owner만 바꾼 합성 paired 입력은
기존 Query도 Task Evidence를 확보했다. 015의 현재 저장 RU에는 TASK
business Route가 있지만 이번 기준 Node 첫 출력은 CALENDAR_EVENT와
CALENDAR_FREEBUSY만 선택했다. 이는 Source가 있으나 Query가 누락한
다른 경계다. 이번 후보는 그 출력도 바꾸지 못했다. TASK Route가
있다는 이유만으로 전 요청에 Task READ를 강제하지 않는다.

이번 실험의 실제 Provider READ·Live backend·LangSmith 원격 Trace·
Work Analysis/Planning/Review 연결 검증은 하지 않았다. 합성 READ는
008 기준 1회, dependency-only 후보 2회, Schema-only 1회이며,
Provider WRITE는 0이다. Node arm의 LLM dispatch는 기준 6,
Schema-only 6, Schema+Prompt 6, 필드 역할 6으로 총 24회(1회씩
고정); 각 arm의 token/latency는 ignored 결과의 `summary`에
보존한다. 호출 지연 변동만으로 개선을 주장하지 않는다.
