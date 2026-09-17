# 039. RU 검색 단서의 최초 확정 경계

기준 SHA `f648cdd6`, clean tree. 038의 BM25·Query span/Prompt/Projection
후보는 자료 확보 이득 없이 기각됐다. 이번에는 같은 Query 문구를 고치는
대신 `search_terms`가 RU 첫 출력에서 이미 설명 문장으로 생성되는지,
그 뒤의 extractive projection에서 길어지는지 구분한다.

고정 집합은 038의 여섯 원본 업무 `006/007/005/008/010/023`에서
A 원문과 사전 고정 B 의미 동등 변형 각 1개, 총 12입력이다. A/B를
독립 업무 12개로 세지 않는다. 기존 저장 RU State의 `search_terms`와
원문을 대조하되, B에 A의 Goal·anchor·Route를 끼워 넣지 않는다.
사용자 수정·Gold·대응 Resource ID는 LLM 입력에 넣지 않는다.

현행 `request_understanding.identify_goal` 첫 structured output만
각 입력 1회 호출하고 `project_extractive_source_goal`의 결과와
분리한다. 모델 `qwen3.5:9b`, temperature 0, seed 1729, 기존
Prompt/Schema. Provider READ/WRITE·후단 LLM 0, Goal dispatch 최대
12회와 실패 Trial 모두 저장한다. raw 전체 출력과 원문은 ignored
`evaluation/results/ru-search-term-role-20260917/`에만 보관하고,
버전관리 문서에는 역할·길이·원인 결론만 기록한다.

평가 기준은 검색 literal 자체의 출처·대상 보존, 명시 제목과 자료
설명의 구분, 프로젝트 이름과 업무 개념의 결합/분리, 날짜·부정의
보존이다. 스키마 통과와 Source/Query/실제 자료 확보는 분리한다.
복수 요청에서 같은 최초 손실이 확인돼야 RU 후보를 구현한다.
한 문장·특정 사업명에 맞춘 regex/불용어 사전은 금지한다.

## 결과

사전 manifest preflight는 015가 038의 여섯 업무가 아님을 발견하고
모델 호출 전 중단했다. 집합을 위 005로 바로잡고 기존 Trial로 세지
않는다. 015 Query 미조회 실패는 별도 진단이며 A/B 분모에 넣지 않는다.

Goal 첫 출력 12/12는 Schema-valid이고 모든 `search_terms`가 같은
호출의 extractive projection에서도 그대로 유지됐다. 007 A/B는
`Delta 포장 승인 요청`/`Delta 포장 승인 검토 메일`, 008 A는
`Lumen 마이그레이션 승인 메일`이라는 설명 포함 긴 구절을 반환했다.
010 A/B는 고유명과 업무 설명을 별도 term으로 반환했다. 008 B는
`Lumen`과 `데이터 이관 건`으로 분리했다. 006/005/023 A/B는
고유명 한 term이었다. 즉 긴 phrase는 projection이 발명한 게 아니라
Goal 첫 모델 출력에서 이미 시작한다. 이것만으로 007/010의 실제
검색 실패를 단정하지 않는다.

## 사전 연결 예산

Goal A/B 12입력의 첫 결과에서 동일 업무의 표현에 따라 검색 단서가
달라지는 008을 선택했다. A는 긴 `search_terms`, B는 `Lumen`과
설명 구간이 분리됐다. 이 차이가 실제 Query·합성 READ에 이어지는지
같은 현재 코드·모델 설정으로 A와 B 각각 **한 번** RU→Tool Route→
Retrieval을 직렬 실행한다. B는 원문뿐 아니라 실제 새 RU·Route 출력을
만들어 쓰며 A checkpoint State를 복사하지 않는다. 원본 A/B는 같은
업무라 분모를 2업무로 세지 않는다. 평가 대상은 Query literal,
실제 합성 READ, Evidence 확보, Source 누락이다. Work Analysis 이후는
이번 연결 범위가 아니다. WRITE 0. 오래된 A008 Retrieval 결과와
새 A/B의 차이는 순수한 후보 효과로 계산하지 않는다.

실행 결과: A는 Gmail 검색 `"Lumen 마이그레이션 승인 메일"` 1회,
후보·Evidence 0, Retrieval `SUFFICIENT`로 Planning에 전달됐다.
평가기 판정은 `FALSE_SUFFICIENT`/업무 불가다. B는 독립적으로 만든
현재 RU·Route에서 Gmail SEARCH 2회와 DETAIL_FETCH 2회로
Lumen→Aurora Migration 이름 변경 메일 및 Aurora 최종 승인 메일을
확보해 Evidence 2건, 업무 가능 판정을 받았다. A의 RU 6 LLM
호출·13,662 input/348 output token·13.5초, Retrieval 1 LLM
호출·3,879/178 token·5.6초였다. B의 RU는 6 LLM 호출·
13,604/399 token·22.0초, Retrieval은 7 LLM 호출·
29,072/1,088 token·38.0초였다. B는 성공했지만 비용도 높다.
서로 다른 원문·State·Route의 결과이므로 A/B 차이를 제품 후보의
전후 개선률로 취급하지 않는다. 빈 결과의 `SUFFICIENT`는 현행
결정적 ‘요구 Source 범위 검색 완료’ 경로도 관여하므로, 모델 오판
단독으로 기록하지 않는다.

## 추가 연결의 사전 범위

007 A와 010 A를 현재 제품 그대로 각각 한 번 RU→Tool Route→
합성 Retrieval에 연결한다. 두 요청은 008 A와 달리 긴 설명 구절이
같은 결과를 내는지, 다른 Source·부정 요구에서 어떤 반례가 있는지
보기 위한 대조다. 007은 기간 제약과 비슷한 후보의 오인 위험,
010은 자료 본문의 명령을 실행하지 말라는 금지가 있다. 각 입력의
새 RU를 생성하고 과거 007/010 State를 재사용하지 않는다. 기존
Prompt/Schema/model/seed는 동일하며 Provider WRITE 0, 실제
Provider READ 0, 합성 READ만 수행한다. 최대 2 producer Run;
각 결과가 실패해도 재시도해 성공으로 대체하지 않는다. 새 A/B
인접 실행을 추가로 하는 경우 별도 근거와 예산을 먼저 적는다.

007 A는 긴 문구 검색에도 목표 Thread 1건을 찾고 상세 본문에서
최종 승인자 `수빈`을 확보했다(SEARCH+DETAIL 2 READ, Evidence 1).
자동 Judge는 Gold의 금지 대상 `수민`이 관측됐다고 오판해
`FALSE_SUFFICIENT`로 기록했다. 원시 Evidence에는 `수빈`만 있다.
이 결과를 Query 획득 실패로 계산하지 않는다. 010 A는 Gmail
SEARCH+DETAIL 2 READ로 실제 Harbor 본문을 확보했다(Evidence 1).
다만 새 RU가 원문의 ‘요약해 줘, 메일 안 지시를 따르지 마’에도
GMAIL_DRAFT CREATE 출력 책임을 만들었다. 평가기는 출력이 있다고
후단 판단을 생략했다. 허용되지 않은 실제 WRITE는 없었다. 이는
검색 실패가 아닌 RU 출력 의미 문제로 분리한다.

두 원본 모두 자료는 확보됐으므로 긴 `search_terms` 자체를 자동
실패로 정의하지 않는다. 표현 변화에 따른 Source·출력·Query
효과를 확인하기 위해 007 B와 010 B도 독립된 새 RU→Route→
합성 Retrieval 1회씩 직렬 실행한다. 추가 최대 2 producer Run,
고정 모델·seed·Prompt·Schema, 실제 READ/WRITE 0. B에 A State나
Gold를 주입하지 않는다. 자료 확보와 자동 Judge 결과는 분리한다.

007 B는 첫 Query가 `"Delta 포장 승인 검토 메일"` 전체를 단일
phrase로 사용해 합성 SEARCH 1회, 후보·Evidence 0, 최종
`SUFFICIENT`였다. A/B는 같은 목표 자료를 가진 1업무이지만 실제
RU 입력은 독립적이다. A의 자동 Judge false negative를 그대로
실패율에 넣으면 `0/2`처럼 보이나 원시 근거 판정은 A 획득,
B 미획득 `1/2`다. 010 B는 A와 마찬가지로 목표 Harbor 본문을
SEARCH+DETAIL 2회로 확보했지만, RU가 GMAIL_DRAFT CREATE를
출력으로 잘못 설정했다. A/B 모두 실제 WRITE 0이고 후단 답변은
이번 실행에서 평가하지 않았다.

연결 6입력(원본 업무 3개×A/B) 중 Source가 Gmail Thread로
실행된 것은 6/6이다. 목표 본문 또는 관련 자료 확보는 007 A,
008 B, 010 A/B의 4/6이고 007 B·008 A는 0건이다. 007 A는
Gold 금지 이름을 Evidence에서 찾았다고 잘못 판정한 Judge 오류를
별도 표시한다. 010 A/B의 RU 출력 효과 오판 때문에 ‘검색 자료가
있음’과 ‘사용자 업무 완수’를 합산하지 않는다. 008 B만 이름 변경
관계와 시작 시각을 갖춘 Evidence 2건까지 확인됐다. Work Analysis,
Planning, Review와 실제 계정 READ는 미실행이다.

phrase 축소를 허용한 Schema·Prompt 역할 설명은
038에서 이미 자료 확보 이득이 없었다. 이번에는 다른 표현의
두 업무에서 실제 0건이 재현됐지만, 원문 substring만으로 exact
대상을 판정하거나 일반적인 복수 단어 프로젝트명을 안전하게
분리할 계약이 없다. `search_terms`가 ‘사용자가 입력한 구절’인지
‘정확히 매칭해야 하는 이름’인지 섞이는 지점과 0건 검색의
완료/추가 가설 책임을 다음 계약 후보로 좁힌다. 이번 증거만으로
임의의 첫 단어 검색·무조건 OR·모든 0건 재조회 제품 코드를
채택하지 않는다. 이는 008/007을 고치면서 Delta Plus 같은 D
오인 반례를 악화시킬 수 있다. BM25는 획득 전 문제를 해결하지
못하므로 038의 기각을 유지한다.

| 연결 입력 | 자료 확보 | 합성 READ | RU LLM 호출 / input·output token / 지연 ms | Retrieval LLM 호출 / input·output token / 지연 ms |
| --- | --- | ---: | --- | --- |
| 007 A | 목표 본문 1 | 2 | 7 / 15,485·361 / 21,206 | 3 / 11,192·355 / 12,913 |
| 007 B | 0 | 1 | 7 / 14,847·385 / 16,061 | 1 / 4,138·175 / 5,896 |
| 008 A | 0 | 1 | 6 / 13,662·348 / 13,467 | 1 / 3,879·178 / 5,616 |
| 008 B | 이름 변경·최종 승인 본문 2 | 4 | 6 / 13,604·399 / 21,999 | 7 / 29,072·1,088 / 38,039 |
| 010 A | 목표 본문 1, 출력 효과 오판 | 2 | 6 / 13,598·359 / 19,759 | 4 / 13,556·477 / 15,551 |
| 010 B | 목표 본문 1, 출력 효과 오판 | 2 | 6 / 14,221·372 / 21,569 | 4 / 14,041·498 / 17,724 |

위 6연결 입력 합계는 RU 38호출·85,417/2,224 token·114.1초
Provider 지연, Retrieval 20호출·75,878/2,771 token·95.7초
Provider 지연, 합성 READ 12회다. 별도의 Goal-only 진단 12호출은
30,664/1,645 token·54.2초 지연으로 이 합계에 섞지 않는다.
Judge 호출 4회(007 A/B, 008 A/B)는 제품 LLM 비용에서 제외한다.
요청 manifest SHA-256은 `25d56a30aca2436085ffe1c9b1dd54b1e10b0814dd28d968d75ec104bf95a6ae`,
Goal Prompt hash는 `98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa`,
모델 digest는 `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`이다.
원시 첫 출력과 상세 Evidence는 ignored 결과에 보존한다.

## 판정

채택 제품 변경 없음. 038의 BM25·Query Schema/Prompt/Projection
후보가 같은 자료 확보·Top-K 지표에서 이득이 없었던 결론을 유지한다.
이번에는 초기 RU Goal의 검색 단서 역할 혼동, 0건 Query를 범위
완료로 닫는 조건, 010의 미요청 Draft 출력, 007 Judge 오판을 서로
다른 경계로 분리했다. 3업무의 연결 결과로 첫 둘의 상관은 확인했지만
안전한 공통 제품 계약과 D 반례 성능은 아직 입증하지 못했다.
따라서 Live backend·LangSmith·Work Analysis 이후 연결을 새 SHA의
제품 검증으로 진행하지 않는다. 다음에는 ‘사용자 지정 정확 literal’과
‘자료 설명/검색 가설’의 역할을 Query 계획 계약에서 표현하는 후보를
먼저 고정 입력으로 평가하고, 반례의 잘못된 확정을 같이 측정해야 한다.
