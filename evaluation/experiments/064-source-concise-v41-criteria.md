# 064 v41 — Source 설명 부담만 축소하는 FIRST 진단

## 가설과 과거 방법의 구분

v40에서 top-level format을 없애도 Source fact inventory 복사와 새 Output/기존 Source
혼동은 남았고 구조도 회귀했다. format 후보는 채택하지 않는다. 이번에는 현재 Source
지시문의 중첩된 절차·설명만 짧게 정리하고, 입력·출력 Schema·sampling·format·validator는
동일하게 유지한다. 지시문 길이가 원인이라는 결론은 아직 없으며 이를 검증하는 작은 진단이다.

003 sparse와 037 fact-bound는 짧은 설명과 출력 Schema를 함께 변경했다. v6/v7/v9는
needs/ref/map 표현, v10은 본문 schema, v22는 동일 instruction의 input 중복을 바꿨다.
001~064의 문서·보존 코드·남아 있는 raw에서는 Source 지시문만 전반 축소한 동일 조건
비교를 찾지 못했다. 003/037 raw는 현 로컬에 없어서 문서와 코드로만 대조했다.
이 차이는 실험을 정당화할 뿐 성공을 예측하거나 과거 실패를 취소하지 않는다.

사례별 문구·어휘·예시·새 규칙을 추가하지 않는다. 기존 원문 우선, Source 책임,
필요 사실/대상 범위/Work 귀속, 선택 identity, 새 결과와 기존 자료의 구분, closed set 및
revision 의미를 보존한다. Product Prompt·manifest·activation·Schema·State 변경은 0이다.

## 실행 전 고정 집합과 의미 기준

Canonical v8의 원문과 `evaluation_gold.required_semantics / forbidden_semantics`를
기준으로 검수한다. 정확한 Resource 개수나 한 가지 조회 경로를 새 Gold로 만들지 않는다.

| Case | frozen FIRST 원본 | 비교할 Source 의미 |
| --- | --- | --- |
| CORE-005 | v35 production | 선택 Task의 상태·기한, SINGULAR/해당 Work 유지. 다른 업무 사실·자료를 필수로 확장하는지 확인 |
| CORE-009 | connected-core8 production | 메일과 Task 양쪽의 진행 정보. baseline의 Task 누락이 회복되는지, 메일 보존 반례를 함께 확인 |
| CORE-017 | v35 work-span-codec-v35 | Task/Event 근거 유지. 새로 만들 Draft를 기존 Draft 조회로 요구하는 혼동을 줄이는지 확인 |
| CORE-049 | v35 work-span-codec-v35 | 메일/Task/Calendar 사실 보존. 새 Task/Event/Draft Output과 기존 자료의 역할을 구분하는지 확인 |
| CORE-059 | connected-core8-continuation production | 기존 답장 대상 Thread/Message 근거 유지. 불필요 Task/Calendar/Draft source 증가 여부를 control로 확인 |

기존 결과의 성공과 실패를 섞어 동일 입력에서 비교한다. 이 집합에 NO_FETCH_NEEDED
control이나 다중 Work binding 전수 검증은 없으므로 그 경계까지 일반화하지 않는다.
Thread/Message의 합리적인 대안은 허용한다. parent/보조 자료를 추가했다는 이유만으로
즉시 업무 FAIL로 처리하지 않고 필수/선택적/불필요와 실제 acquisition 미검증을 구분한다.
required_information의 capability 목록 일치도는 관측이지 자동 의미 채점 기준이 아니다.

## 예산·동일 조건·원 결과 보존

- 기존 FIRST 5개 baseline 재사용, 후보 각 1회: **신규 생성 최대 5회**, 직렬 1.
- 순서 005 → 009 → 017 → 049 → 059. 실패도 보존하며 성공까지 재실행하지 않는다.
- 모델 digest, Source temperature 0.05, seed 20260923, num_ctx 16384, think=false,
  timeout 180초, 실제 원문·Work·selected refs·Goal projection·reference time을 원 wire와 동일 유지.
- 기존 Product assembler/transport로 baseline wire hash의 완전 일치를 먼저 확인한다.
  후보 차이는 Source instruction 본문과 이를 정직하게 식별하는 candidate PromptRef/hash뿐이다.
  assembler의 입력 suffix, prompt body input/schema, top-level structured schema를 보존한다.
- raw/call/row hash, dataset/fixture hash, Case ID·reference time·fault profile,
  HEAD·runner·owner·validator·Prompt hash를 실행 전 plan에 결속한다.
- 신규/재사용 호출·토큰·시간을 분리한다. 동일 sampling이어도 재사용 baseline은 동시 paired
  성능 측정이 아니며 cache/load/장비 상태 차이를 인과적 속도 향상으로 보고하지 않는다.
- HTTP retry, schema repair, semantic revision, fence codec, Graph, 업무 Provider 호출 0.
  strict JSON → 기존 Schema → 기존 Source owner validator 결과를 그대로 기록한다.
- 실행 중 코드 수정·pytest·다른 모델 실행을 하지 않는다. RAM/VRAM/온도는 시작/종료에
  확인하고 자원이 부족하면 이미 완료한 Trial을 보존하고 추가 dispatch를 보류한다.

## 판단

구조와 의미를 분리해 각 Case의 이전/후 결과와 최초 차이를 기록한다. raw의 의미 판정은
UNREVIEWED로 두고 근거 기반 검수를 별도로 남긴다. 필수 Source/target/Work 손실이 생기면
그 실패를 더 짧은 토큰이나 더 높은 구조 점수로 상쇄하지 않는다.

5개가 개선돼도 반복 안정성·RU→Tool Route·Retrieval→Planning·업무 완료나 release
통과를 뜻하지 않는다. 유력할 때만 no-source/다중 Work 등의 반례와 실제 upstream 연결로
확장하며, 실패하면 이 축의 원 결과를 보존하고 실패 원인을 재분류한다. 전수 92를 먼저
실행하거나 같은 Prompt 축소에 Case 규칙을 계속 덧붙이지 않는다.

## 실행 전 도구 검증

단일 runner의 직접 검사 **89 PASS / 9.69초**, Ruff·mypy 및 실제 historical raw의 메모리
dry-plan 통과. 원 wire 재구성 5/5 일치와 기존 strict validation 5/5를 확인했다.
후보 source SHA-256은 `b073911a62c101e66c4812a9216df3cfd30ebe0cdeef8de17fa54d2c36237b5b`다.
이 준비 검증은 신규 모델·업무 Provider 호출 0이며 후보의 의미 개선 결과가 아니다.
