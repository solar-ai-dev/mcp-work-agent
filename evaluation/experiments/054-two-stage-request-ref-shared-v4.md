# 054 — deterministic request ref + shared semantic State 비교

Issue: #287

## 범위

`span-bound v3`의 two-stage 구조와 두 번의 LLM 호출을 유지하면서 남은 두
representation 문제만 비교했다.

1. Stage 1은 원문 문자열을 다시 생성하지 않고 request-local token ID 범위를
   선택한다. Projection이 원문의 character offset으로 exact span을 복원한다.
2. 여러 WorkUnit에 공통으로 적용되는 Source·target·시간·수량·금지 조건을
   `shared_semantics`에 한 번 결속하고, 업무별 의미는 각 WorkUnit에 둔다.

규칙, few-shot, Node 수는 늘리지 않았다. `requested_effects`는 decomposition이
판단하지 않았고 relation schema와 Stage 2 Prompt도 v3 그대로 유지했다. Product
State/Schema/Prompt/Node/Edge는 변경하지 않은 evaluation-only 후보다.

고정 Core 24를 temperature 0, seed 20260920에서 1회 실행했다. Holdout/Stress,
Tool 선택, Query, Retrieval, Provider 연결은 사용하지 않았다.

## 결속

- Product SHA: `896e25eec48f7d4ebc0db3e983477a4b1206f8c0`
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Canonical authority SHA-256: `958bf846f3abba243f5b1f98f4962e53435a90b4149dc41855f50002a40f2189`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Stage 1 Prompt SHA-256: `4a9af6c51a6d46e724b39a7cb2a5ecad4867e9fbd0c18cc1bcd9ffc4c6ab9101`
- Stage 2 Prompt SHA-256: `8cc6f56afed02a76f028c67fffe58273ae0f5365863b7c7c6156e7351bee63cd`
- Raw result SHA-256: `61d5b853accf94218cb0f6f32eb6b5be955702471352208a7263b74c1ea4faf4`
- Review SHA-256: `ad0aa0a6f558a2cb38f60a4b8fcd3d6bd0dee40e7416ee0fedb8b51413995050`
- Corrected regrade file SHA-256: `a13e20a6451e5d4683c41a52949c6f36f89c9d33f930d42a79067155bce4db25`
- Provider READ/WRITE: `0/0`
- rerun-to-pass: `0`

## span-bound v3와 비교

| 후보 | PASS | PARTIAL | FAIL | exact span/ref | calls | tokens in/out | latency | 판단 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| span-bound v3 | 14 | 10 | 0 | 19/24 | 48 | 32,604 / 3,561 | 149,908ms | HOLD |
| request-ref + shared-state v4 | 5 | 18 | 1 | **24/24** | 48 | 97,261 / 6,691 | 288,676ms | **REJECT** |

request-local token ID를 고르는 방식은 CORE-021/026/037/040/046의 띄어쓰기
재생성 문제를 제거했다. identify schema, deterministic carry, final schema도 모두
`24/24`였다. exactness를 validator의 문자열 유사도 보정 없이 해결했다는 점은
유효하다.

하지만 shared/local optional field를 같은 Stage 1이 함께 분류하도록 하자
`SEMANTIC_REF_FIELD_POLLUTION`이 19개 Case에 발생했다. source·target·시간·수량·
금지 조건에 원문 span을 넣을 수 있다는 표현력은 생겼지만, 어떤 의미 축에 속하는지
판단하는 책임이 업무 경계 식별과 다시 섞였다. 입력 token catalog와 동적 schema로 인해
input token은 약 2.98배, LLM latency는 약 1.93배가 됐다.

## 공통 Source·조건 보존

복수 WorkUnit이 생성된 Case는 CORE-048 하나였다.

- 성공: 공통 메일·Task·Calendar Source를 `shared_semantics`에 한 번 결속했고 각
  WorkUnit에 문자열로 복제하지 않았다.
- 실패: 업무별 `2일 지연`, 일정 시간, target까지 shared로 과확장했다.
- 실패: 앞의 두 WorkUnit span에서 동작 술어가 빠져 요청한 결과를 완전하게 표현하지
  못했다.

CORE-037/056은 같은 target 또는 prohibition을 shared와 local 양쪽에 중복했다.
CORE-019/046/050은 독립 결과를 한 WorkUnit으로 합쳐 공통 State의 실제 적용 범위를
검증할 후보 자체를 잃었다. 따라서 공통 의미를 한 번 보존하는 representation은
가능함을 보였지만, 현재 owner가 shared와 local 적용 범위를 안정적으로 판정하지
못했다.

## 기존 성공 회귀와 Case 결과

v3 PASS 중 CORE-009/010/011/012/020/027/028/031/036/056/059의 11개가
PARTIAL로 회귀했다. 대부분 업무 의미가 사라진 것이 아니라 같은 원문 span을 잘못된
typed field에 추가 배치한 회귀다. v4 PASS는 CORE-001/006/041/051/054다.

| Case | 판정 | 이유 |
| --- | --- | --- |
| CORE-048 | FAIL | 공통 Source는 한 번 보존했지만 업무별 조건을 shared로 과확장하고 Task/Event 동작 술어를 누락했다. |
| CORE-050 | PARTIAL | `최종 의견 전달` target을 objective에서 누락하고 prohibition으로 오분류했다. |
| CORE-019/046 | PARTIAL | 여러 결과를 한 WorkUnit으로 합치고 action/source를 prohibition·quantity에 오분류했다. |
| CORE-037/056 | PARTIAL | shared/local에 동일 의미를 중복하고 다른 field에도 오분류했다. |
| 나머지 PARTIAL | PARTIAL | 정확한 원문 ref는 유지했지만 source/target/time/quantity/prohibition 경계가 오염됐다. |

relation 출력은 24개 모두 빈 배열이었다. 사용자 지시대로 이번 후보에서는 relation
type 선택을 채점하거나 최적화하지 않았다.

## 최초 divergence와 판단

최초 divergence는 Stage 1의 **shared/local semantic classification**이다. 안정적인
request ref를 만든 뒤 projection에서 깨진 것이 아니라, 모델이 업무 경계를 식별하는
동시에 모든 optional semantic axis와 적용 범위까지 분류하면서 잘못된 field에 ref를
배치했다.

`request-ref + shared-state v4`는 **REJECT**한다. Production flat baseline은 유지하고
decomposition 비교 기준도 `span-bound v3`로 유지한다.

- 유지할 근거: 생성 문자열 대신 request-local ref로 exact span을 결속하는 방식.
- 채택하지 않을 부분: Stage 1이 source/target/time/quantity/prohibition의 shared/local
  ownership까지 한꺼번에 생성하는 구조.
- 다음 relation 실험: WorkUnit 표현이 아직 안정되지 않았으므로 진행 근거가 없다.

이 결과는 작은 모델의 일반적 한계나 decomposition 자체의 실패로 단정하지 않는다.
현재 후보가 한 호출에 업무 경계 식별과 다섯 의미 축의 분류·scope 판단을 다시 결합한
계약 문제다.
