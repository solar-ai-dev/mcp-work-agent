# 040. 공통 corpus의 LangChain BM25 직접 검색과 제한된 질의 가설

기준 SHA `f40cc1ff54a392314c2a5e0a15224a484eff4435`, clean tree.
038의 업무별 소형 사전 후보 풀 순위 결과와 039의 현재 RU→합성 READ
결과는 보존한다. 이번 첫 단계는 **평가 전용 in-memory corpus 검색**이다.
제품 Query/Provider 접근과 섞지 않고 RU Source/Output을 수정하지 않는다.

## 사전 등록: corpus·조건·판정

`provider-snapshot-v8.json`의 모든 26 resource pack 및 동일 snapshot의
common distractor 전체를 합친다. 정답 Case pack만 선별하지 않는다.
각 원본 Resource를 `resource_type/resource_id/version`과 내용으로
중복 확인한 다음 제품 `normalize_segments`의 현재 텍스트 정규화·
message chunking을 적용한다. `ContextBudget.max_segments`를 전체
Segment 수보다 크게 주어 사전 Top-K 절단을 금지한다. 각 Segment가
LangChain `Document(page_content=실제 정규화 내용, metadata=출처·ID·
version·segment_id)` 하나다. pack 설명·Case 요청·Gold·정답 ID는
Document 본문에 넣지 않는다. 같은 snapshot의 동일 corpus와
전처리(`rag_retrieve_rerank._clean_terms`)를 모든 arm에 쓴다.
LangChain `BM25Retriever.from_documents`→`invoke`를 실제 호출하고
`rank_bm25` 기본 BM25Okapi 및 패키지 버전·corpus hash를 보존한다.
Top-K는 4와 12를 둘 다 본다. 이 결과는 **전체 fixture corpus를 이미
메모리에 가진** 검색이며 제품 API 후보 획득과 다르다.

고정 입력은 038의 여섯 원본 업무 × A/B/C/D 24개. A 원본과 B 의미
보존, C 도전, D 오인 방지를 별도로 집계한다. manifest의 target ID는
검색·재작성 모델 입력에 넣지 않고 평가에서만 사용한다. C는 Gold가
없으므로 적중률을 산출하지 않으며 D 4개 규칙형은 문서 반환만으로
정답 여부를 선언하지 않는다. 008의 이름 변경→승인, 023의 Gmail→Task
같은 복수 문서·사실 요구는 모두 남아야 충족으로 센다.

arm은 A=사용자 원문, B=원문만 입력받은 한 번의 평가 전용 LLM 호출이
작성한 검색용 재표현, C=A+B+그 호출에서 필요하다고 제안한 대안
최대 1개(총 3질의)의 BM25 결과를 RRF(k=60)로 병합·segment_id 중복
제거한 것이다. 질의 생성은 `qwen3.5:9b`, temperature 0, seed 1729,
각 입력 1회·최대 24 dispatch, 실패도 그대로 보존한다. 기본 요청도
실험 비교를 위해 호출하되 이것을 제품의 무조건 추가 호출 정책으로
해석하지 않는다. 모델에는 원문만 주며 자료 내용·Gold·정답 대응표는
주지 않는다. Rewrite/alternate는 검색 가설이지 사용자 정정이나 사실이
아니다. 요청한 이름·날짜·Source·금지를 바꾼 질의는 검색 적중과
별도로 의미 손실로 판정한다.

주요 측정은 확정 target resource와 **요구 사실을 담은 Segment**가
Top-K에 남는지, C가 중복 문서로 K를 채우지 않는지, Delta/Delta Plus·
2025/현재 자료를 혼동할 위험, 질의당 corpus 조회 수·LLM 호출·토큰·
지연이다. target이 반환돼도 충분성/최종 답변은 별도다. 라이브러리
미설치·직렬화·corpus 중복·선택 누락을 모델 호출 전 preflight로
검사한다. 실패 Trial을 성공 Trial로 대체하지 않는다.

## 유력 후보의 제품 연결 Gate

기본·B에서 같은 입력 원문 대비 필요한 내용 Top-K 보존이 늘고,
D의 잘못된 target 우선/명시 조건 손실이 없으며, 중복 조회 비용이
정당화될 때만 제품 Query의 **현재 frozen Route와 기존 후속 round**에
연결한다. 0건을 일괄 재조회하거나 기존 요청 literal을 코드가
첫 단어로 잘라내지 않는다. 실제 Provider Query materialization과
Query identity·페이지·예산·동일 API 인자 dedup을 먼저 확인한다.
READ 후 동일 후보 풀에서 현행 vs BM25 ranking을 paired 비교한다.
RU 공유 RequestIntent 계약이 필요하면 필요한 역할·consumer 요구를
분리해 기록하고 독립 검색 실험은 계속한다. 유력 후보가 없으면
제품 코드를 효과 없이 채택하지 않는다.

실행 결과·판정은 아래에 append한다.

## 사전 점검과 기준선 (LLM 비교 전)

2026-09-18 preflight에서 snapshot SHA-256은
`59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`,
중복 제거 후 Resource는 103개, 제품 정규화 Segment는 106개였다.
공통 corpus fingerprint는
`ea67a56f7ba32f3e20a20e3fc9ab2576f4e5b02387918b64653160ee7f767b29`.
`langchain-community 0.4.1`, `langchain-core 1.6.0`,
`rank-bm25 0.2.2`, `numpy 2.2.6`을 평가용 로컬 venv에만 설치했다.
24개 입력 모두 `from_documents`→`invoke` preflight 및 A-arm을 실행했다.
기본·의미 동등 12/12의 지정 target이 원문 BM25 Top-4에 있었다.
D에서 target이 정해진 2/2도 Top-4에 있었다. 이는 **resource ID 발견**의
기준선일 뿐, 사실 추출·오인 방지·Provider 획득 성공률은 아니다.

LangChain BM25는 매칭 점수 0인 문서도 K를 채워 반환할 수 있음을
실제 실행에서 확인했다. B/C 비교 전에 동일 `BM25Okapi.get_scores`를
기록하도록 하며, 점수 0 이하 문서는 적중으로 세거나 C 병합에 넣지
않는다. `invoke`의 원래 반환 순위 자체는 그대로 보존한다.

## 사전 등록한 0건 이후 가설 진단

첫 재작성 비교에서 A 기본·동등 12/12 target Top-4, B 11/12,
C 12/12여서 상시 재작성/병합을 제품에 넣을 근거가 없다. 별도 조건은
**현재 Query의 0건이 실제 관측된 후**다. 기존 039 연결의 007 B와
008 A의 원문·첫 Query·0건을 고정하고, 007 D의 `Delta Plus`와
006 D의 `2025년 Atlas`를 오인 방지 대조로 둔다. 평가 전용 LLM은
원문·실패한 검색 표현·0건 사실만 보며 target ID/본문/Gold는 보지
않는다. `qwen3.5:9b` temperature 0 seed 1729, 각 입력 1회,
최대 4 dispatch. 더 넓은 **하나의 후보**만 만들되 정확한 다단어 이름과
연도는 유지하고, 설명적 문구를 정확 구절처럼 고정하지 않는다.
불확실하면 null을 허용한다. 합성 Gmail grammar를 공통 snapshot
Gmail 자료에 적용해 검색 결과를 기록한다. 실제 제품 Query round,
Provider READ·Evidence 연결과 동일하다고 주장하지 않는다.

채택 조건은 007 B/008 A에서 필요한 본문 후보가 늘고 007 D/006 D의
다른 대상·연도 혼동이 늘지 않는 것이다. 대안 `CHANGED` Query는
기존 KEYWORD에 AND로 붙이는 038 실패와 달리 대체해야 하며,
제품 적용 전에는 검색어의 정확/잠정 역할을 source-backed으로
검증하고 Query identity·예산·sufficiency consumer를 맞춰야 한다.

## 동일 corpus A/B/C 직접 검색 결과

`qwen3.5:9b` digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
공통 103 Resource/106 Segment, 동일 전처리·BM25 설정·Top-K에서
24/24 입력의 A/B/C가 완료됐다. 후보 corpus에 자료가 이미 있는
기본 A 6개와 동등 B 6개를 **동일 요청별 paired**로 비교했다.

| 검색 arm | 기본·동등 요청의 지정 target 전부 Top-4 | Top-12 | 확정 target이 있는 D 반례 Top-4 |
| --- | ---: | ---: | ---: |
| A 원문 | 12/12 | 12/12 | 2/2 |
| B 재작성 | 11/12 | 12/12 | 2/2 |
| C 원문+재작성+대안 병합 | 12/12 | 12/12 | 2/2 |

B의 유일한 Top-4 손실은 023 A의 Gmail 지연 메일이다. Task는
남았으므로 복수 Source 요구에서 메일 근거가 Context 밖으로 밀린
회귀다. C는 원문을 포함해 이를 복구했지만 12입력에서 추가
target 확보는 없었다. 24개 중 모델이 의미 있게 다른 대안을
제안한 것은 007 C의 1개뿐이며, 나머지는 원문+재작성 2질의다.
총 BM25 `invoke`는 49회(A 24, B 24, 추가 대안 1), LLM은
24회·input/output `3,605/752` token·Provider 지연 22.0초,
A/B 로컬 검색 측정 시간은 각각 합계 14.3/10.0ms다.
단순 요청에도 모델을 호출한 것은 실험 arm을 고정하기 위해서이며,
제품 비용 절감으로 계산하지 않는다. C의 후보 병합은 score>0
Segment만 대상으로 한다. C의 도전 집합은 Gold가 없고 D의
‘시작≠종료’·‘메일 지시≠승인’은 상위 Resource만으로 판정할 수 없어
업무 의미 성공률을 주장하지 않는다.

## 0건 이후 단일 대체 가설 결과

실제 039의 007 B/008 A가 첫 SEARCH 0건이던 동일 저장 조회 표현을
재사용했다. D 두 입력은 과도하게 좁은 첫 구절을 만든 **합성 대조**다.
네 모델 출력 모두 Schema-valid였지만 첫 평가기 실행은 모델이
반환한 바깥 인용부호를 도구 literal로 거부해 3/4 `ValueError`였다.
이는 의미 모델 오답이 아닌 평가기 materialization 문제로 남긴다.
모델을 다시 부르지 않고 저장된 4출력만 바깥 인용부호 정규화 후
재생했다(`empty-four-replay.json`).

| 입력 | 후속 검색 표현 | 합성 공통 Gmail corpus 결과 | 판정 |
| --- | --- | --- | --- |
| 007 B 실제 0건 | `Delta 포장 승인` | 목표 Thread 1건 | 후보 확보 개선 |
| 008 A 실제 0건 | `Lumen 마이그레이션` | 0건 | 이름 변경 단서·최종 승인 근거 미확보 |
| 007 D 합성 0건 | `Delta Plus 포장 승인` | Delta Plus Thread 1건 | 다른 Delta로 축소하지 않음 |
| 006 D 합성 0건 | `2025 년 Atlas 출시` | 0건 | 연도 의미는 남았으나 띄어쓰기/표현으로 자료 미확보 |

후속 모델 4회·input/output `743/70` token·Provider 지연 1.91초,
합성 공통 corpus 검색 4회다. 원래 실패 Trial의 비용을 replay에서
숨기지 않는다. 실제 0건 두 입력의 목표 확보는 `1/2`, 합성 D
대조의 목표 확보는 `1/2`다. 이 비교는 **합성 공통 corpus에
이미 접근하는 검색**이지 039의 production Query→Provider READ
재실행이 아니다. 성공한 007도 Evidence 선택·충분성·후단까지
연결하지 않았으므로 업무 성공으로 세지 않는다.

## 판정·원인 경계·재시도 조건

| 실패 유형 | 시도 방법 | 조건·근거 | 결과·회귀 | 판단 | 재시도 조건 |
| --- | --- | --- | --- | --- | --- |
| 사전 corpus 순위 부족 가설 | 공통 corpus 직접 BM25 A/B/C | 103 Resource, 106 Segment, 24 요청 | A가 이미 지정 target 12/12 Top-4; B 023 A 복수 Source 손실, C 추가 확보 0 | 상시 재작성·BM25 제품 채택 기각 | 실제 READ의 동일 후보 풀에서 누락·방해가 재현될 때 |
| 긴 설명 구절의 실제 0건 | 관측 후 단일 대체 가설 | 039 실제 실패 2개, 합성 D 2개 | 007 B만 회복, 008 A 0; 006 D 0 | 제품 채택 보류 | 정확한 이름/잠정 설명의 신뢰 가능한 역할과 이름 변경·다중 근거 연결 표현이 준비될 때 |
| 0건인데 `SUFFICIENT` | 039 저장 Query Attempt·Sufficiency 코드 대조 | 한 Query의 scope/paging 완료와 요청 정보 충족이 다른 의미 | 007 B/008 A가 Evidence 0인데 후속 없이 Planning으로 전달 | 미해결 | 범위 완료·탐색 부족·정상 미발견을 같은 consumer에서 분리하고 반례로 검증할 때 |

공유 RU 계약을 이번 작업에서 바꾸지 않았다. Retrieval consumer가
필요로 하는 것은 `search_terms`를 다시 자르는 규칙이 아니라,
원래 사용자에게서 **정확히 지정된 대상·제목**과 그 대상을 찾기
위한 **잠정 검색 설명**의 출처·역할 구분이다. 008처럼 Source 내용에
관측된 이름 변경은 첫 가설만으로 확정하지 말고 근거 획득 후 다음
Query에 연결해야 한다. 이 요구를 RU 담당자와 계약 수준에서 협의하기
전에는 Retrieval에서 임의의 첫 단어·별칭·전체 business Source
강제를 추가하지 않는다.

이번 사이클의 제품 변경은 없다. 기존 RECHECK·안전 계약은 수정하지
않았다. 실제 Provider READ/WRITE, Query→READ→Evidence→충분성→후단,
Live backend/LangSmith, 전체 92개는 **미검증**이다. 새로운 유력
제품 후보가 없어 해당 비용과 권한을 쓰지 않았다. 원시 모델 출력,
실패와 재생 결과는 ignored
`evaluation/results/direct-bm25-20260918/`에 남긴다.
평가 스크립트 직접 영향 테스트 4개 PASS, 두 스크립트와 테스트의
Ruff format/check PASS다. 평가용 선택 패키지만 로컬 `.venv`에
설치했으며 제품 의존성·Prompt manifest·Canonical은 변경하지 않았다.
