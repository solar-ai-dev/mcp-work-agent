# 053 — request span binding + closed typed relation 비교

Issue: #287

## 범위

`two-stage semantic-carry v2`의 두 호출, 업무 경계 규칙, optional typed field와
deterministic carry는 유지하고 052에서 확인한 두 계약만 바꿨다.

1. Stage 1은 생성형 `objective`를 출력하지 않고 각 WorkUnit 의미를 사용자 원문의
   exact `request_spans`에 결속한다. 최종 `objective`는 span을 결정적으로 이어 붙인
   projection이며 별도 LLM 재작성 결과가 아니다.
2. Stage 2 relation schema는 현재 Stage 1의 서로 다른 WorkUnit ID 조합만 허용한다.
   relation kind는 `CONSUMES_WORK_PRODUCT`와
   `CONSUMES_PLANNED_SPECIFICATION`으로 닫았다. 단일 WorkUnit이면 빈 relation만
   허용한다.

Node 수, LLM 호출 수, 업무 경계 규칙, few-shot 수는 늘리지 않았다. Product State/
Schema/Prompt/Node/Edge도 변경하지 않은 evaluation-only 후보다.

고정 Core 24를 temperature 0, seed 20260920에서 1회 실행했다. Holdout/Stress,
Retrieval, Tool 선택, Provider 연결은 사용하지 않았다.

## 결속

- Product SHA: `55d15785cdecf0e8e40ed669bb900a354ff014e9`
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Canonical authority SHA-256: `958bf846f3abba243f5b1f98f4962e53435a90b4149dc41855f50002a40f2189`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Stage 1 Prompt SHA-256: `95b59447141ac00328ebd5057f109af07d22b1c0739f4d8b88e2cd7764a40427`
- Stage 2 Prompt SHA-256: `8cc6f56afed02a76f028c67fffe58273ae0f5365863b7c7c6156e7351bee63cd`
- Raw result SHA-256: `cce6460c3cfd5c80755d6202c0798c258b35a41cd2aa28f115fff02275f635a3`
- Corrected regrade SHA-256: `696e21325f5374249a665c479d379dffae0a269f1100ad0afcd07dc9b715ad1a`
- Exact request span validity: `19/24`
- Stage 1 → final WorkUnit exact typed carry: `24/24`
- Closed typed relation/final decomposition validation: `24/24`
- LLM calls: `48`
- Tokens input/output: `32,604 / 3,561`
- LLM latency 합계: `149,908ms`
- Provider READ/WRITE: `0/0`
- rerun-to-pass: `0`

## semantic-carry v2와 비교

| 후보 | PASS | PARTIAL | FAIL | calls | tokens in/out | latency | 판단 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| semantic-carry v2 | 7 | 13 | 4 | 48 | 32,464 / 4,224 | 166,254ms | HOLD |
| span-bound typed-relation v3 | **14** | **10** | **0** | 48 | 32,604 / 3,561 | 149,908ms | **HOLD** |

| 오류 축 | semantic-carry v2 | span-bound v3 |
| --- | ---: | ---: |
| `INTERNAL_STEP_PROMOTED` | 0 | 0 |
| exact typed semantic carry | 24/24 | 24/24 |
| `SOURCE_SCOPE_DROPPED` | 0 | 2 |
| `EXPLICIT_PROHIBITION_DROPPED` | 0 | 0 |
| `EFFECT_CHANGED` | 2 | **0** |
| `FACT_OVERCLAIMED` | 2 | **0** |
| `RELATION_INVALID` | 12 | **0** |
| `RELATION_MISSING` | 1 | 2 |
| `TYPED_SEMANTIC_FIELD_POLLUTION` | 8 | **4** |
| `REQUEST_SPAN_INVALID` | N/A | 5 |

생성형 objective를 의미 권위에서 제거하자 CORE-011의 Draft→SEND, CORE-031의
Task CREATE→확정, CORE-019의 미확정 일정 확정, CORE-020의 미완료→완료 과장이 모두
사라졌다. closed endpoint schema로 self-relation과 이메일·Source 문자열 endpoint도
구조적으로 불가능해졌다.

## 남은 문제

### Exact span 생성

CORE-021/026/037/040/046은 모델이 `8월`, `10시`, `2일` 등을 `8 월`, `10 시`,
`2 일`로 정규화해 exact substring 검증에 실패했다. 의미는 유지됐지만 contract는
유효하지 않으므로 PARTIAL이다. Validator가 유사 문자열을 원문으로 보정하지 않았다.

### 공통 조건 귀속

CORE-048/050은 복수 WorkUnit을 만들면서 문장 앞의 공통 메일·Task·Calendar 범위를
첫 WorkUnit에만 결속했다. exact span 하나를 고르는 것만으로는 여러 업무에 걸친 공통
조건의 적용 범위를 표현하기 부족하다는 것이 새 first divergence다.

### Relation recall

Stage 2가 만든 relation은 전체 `0`개다. 따라서 다음은 구분해야 한다.

- endpoint/kind validity: `24/24` PASS. 잘못된 ID와 legacy kind는 schema상 불가능하다.
- relation 의미 recall: 미검증/부족. CORE-019/046이 두 산출물을 한 WorkUnit으로
  합쳐 typed relation을 만들 후보 쌍 자체가 없었다.
- CORE-048/050의 두 WorkUnit 사이에는 Canonical상 필수 산출물 소비 관계가 없어
  빈 relation이 정상이다.

즉 relation 계약은 안전하게 닫혔지만 두 typed kind를 모델이 올바르게 선택하는 능력은
이번 Trial에서 실제로 관찰되지 않았다.

### Case별 PARTIAL

| Case | 이유 |
| --- | --- |
| CORE-001 | `다시 확인해서`를 temporal constraint로 오분류했다. |
| CORE-019 | Event+Draft를 합쳐 planned specification relation을 표현하지 못했다. |
| CORE-021 | 날짜·시간 띄어쓰기를 바꿔 exact span에 실패했다. |
| CORE-026 | exact span 실패와 원문에 없는 prohibition=`없음`이 함께 발생했다. |
| CORE-037 | exact span 실패와 원문에 없는 target을 추가했다. |
| CORE-040 | `2일`을 `2 일`로 바꿔 exact span에 실패했다. |
| CORE-046 | Event+Draft 결합, exact span 실패, planned specification relation 누락. |
| CORE-048 | 공통 Source가 뒤 WorkUnit에 전달되지 않았다. |
| CORE-050 | 공통 Source가 뒤 WorkUnit에 전달되지 않았다. |
| CORE-051 | 원문에 없는 `사용자 (명시적 대상 미지정)` target을 추가했다. |

PASS는 CORE-006/009/010/011/012/020/027/028/031/036/041/054/056/059다.

## 판단

`span-bound typed-relation v3`는 **HOLD**다.

원문 span 결속은 생성형 objective의 effect/fact 변형을 제거했고 closed relation contract는
invalid endpoint를 제거했다. 두 계약 변경의 방향은 유효하다. 다만 Production 후보로
채택하려면 다음 두 표현 문제가 먼저 해결돼야 한다.

1. LLM이 원문 문자열을 다시 써서 exactness를 깨지 않도록 span을 문자열 생성이 아닌
   deterministic request-local reference로 선택하게 할 것.
2. 여러 WorkUnit에 적용되는 공통 Source·시간·금지 조건을 한 WorkUnit의 span에만
   귀속하지 않는 owner-local 표현을 검증할 것.

Relation kind 확장은 실제 typed edge가 생성되는 bounded Case에서 별도로 확인하기 전까지
채택 근거로 사용하지 않는다. Production flat baseline은 유지한다.
