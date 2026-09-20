# 051 — two-stage semantic State 후보 비교

Issue: #287

## 범위

`two-stage v1`의 두 호출과 업무 경계 규칙은 유지하고 Stage 1/2 WorkUnit 표현에
다음 optional typed field만 추가했다.

```text
source_scopes
targets
temporal_constraints
quantity_constraints
prohibitions
requested_effects = ANSWER | DRAFT | SEND | CREATE | UPDATE | DELETE
```

모든 필드를 필수로 만들지 않았고, broad `metadata`/`hints` bucket을 추가하지 않았다.
Node 수, 호출 수, few-shot 수, relation kind(`PROVIDES_INPUT_TO`)는 바꾸지 않았다.
Product State/Schema/Prompt/Node/Edge도 변경하지 않은 evaluation-only 후보다.

고정 Core 24를 temperature 0, seed 20260920에서 후보당 1회 실행했다. Holdout/Stress,
Retrieval, Tool 선택, Provider 연결은 사용하지 않았다.

## 결속

- Product SHA: `c26267a9d54ebbedca20effe8c39fee57f291cee`
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Raw result SHA-256: `40ce83fb597ba889d96261833aa9667e0dfef6a2387d9bdfc303d865dc240d2a`
- Corrected regrade SHA-256: `bb88be3221d50b4b1ef037075e2fe2745bd85234ae19817f5bc5fc19172fdaae`
- Schema validity: Stage 1 `24/24`, Stage 2 `24/24`
- Stage 1 → Stage 2 exact typed carry: `10/24`
- LLM calls: `48`
- Tokens input/output: `44,323 / 5,952`
- LLM latency 합계: `237,659ms`
- Provider READ/WRITE: `0/0`
- rerun-to-pass: `0`

## corrected semantic evaluation

평가는 exact WorkUnit/Relation 개수가 아니라 Canonical의
`canonical_user_prompt`, `required_semantics`, `forbidden_semantics`로 수행했다.

| 후보 | PASS | PARTIAL | FAIL | calls | tokens in/out | latency | 판단 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| minimal v1 | 8 | 13 | 3 | 24 | 15,558 / 2,691 | 105,113ms | HOLD |
| two-stage v1 | 10 | 12 | 2 | 48 | 26,834 / 3,496 | 136,213ms | HOLD |
| two-stage semantic-state v1 | 7 | 9 | 8 | 48 | 44,323 / 5,952 | 237,659ms | **REJECT** |

## 무엇이 좋아졌고 무엇이 틀렸는가

Stage 1만 보면 Source·target·시간·금지 조건을 별도 필드에 담는 동작은 확인됐다.
`INTERNAL_STEP_PROMOTED`도 minimal v1의 10건에서 새 후보 1건으로 줄어 two-stage의
업무 경계 개선은 대부분 유지됐다. CORE-006/010/041에서는 이전 후보가 잃었던
명시적 금지를 보존했다. CORE-020은 상태를 확인하라는 요청을 완료 사실로
과확정하던 two-stage v1 오류를 고쳤다.

하지만 최종 후보는 다음 두 경계에서 더 크게 실패했다.

1. Stage 2가 Stage 1의 optional typed field를 다시 생성하도록 맡겨 `14/24`에서
   source/target/time/effect 중 하나 이상을 버렸다. objective 문자열에 일부가 남아도
   downstream이 소비할 typed State 전달은 실패다.
2. `requested_effects` enum을 Stage 1이 직접 판정하면서 `제안`, `정리`, `준비`를
   `DRAFT`로 오분류했다. 그 결과 two-stage v1의 effect 오류 1건이 새 후보에서
   6건으로 늘었다. 필드를 추가하는 것만으로 effect owner가 안정되지는 않았다.

최종 오류 집계는 다음과 같다.

- `TYPED_SEMANTIC_CARRY_DROPPED`: 14
- `EFFECT_CHANGED`: 6
- `SOURCE_SCOPE_DROPPED`: 3
- `EXPLICIT_PROHIBITION_DROPPED`: 3
- `FACT_OVERCLAIMED`: 2
- `REQUESTED_OUTCOME_MISSING`: 2
- `RELATION_MISSING`: 2
- 그 외: internal-step 1, temporal 1, planned-status 1, untyped relation 1

### Case별 비통과 사유

| Case | 판정 | 최초 의미 손실과 실제 결과 |
| --- | --- | --- |
| CORE-001 | PARTIAL | Stage 1이 다른 메일 검색 금지를 누락했고 Stage 2가 선택 메일 source/target도 버렸다. |
| CORE-009 | PARTIAL | 한 통합 답변은 유지했지만 Stage 2가 메일·Task source와 target을 버렸다. |
| CORE-019 | FAIL | Event CREATE + 안내 Draft를 DRAFT 하나로 축소하고 아직 확정할 수 없는 일정을 확정한다고 과장했다. relation도 없다. |
| CORE-020 | PARTIAL | 기존 완료 과확정은 고쳤지만 Stage 2가 Task·Calendar source와 수신자를 버렸다. |
| CORE-021 | FAIL | Source 확인을 독립 업무로 다시 승격하고 그 내부 업무를 DRAFT로 오분류했다. 범용 relation과 typed carry 손실도 생겼다. |
| CORE-026 | FAIL | 하나의 슬롯 제안 답변을 Gmail Draft로 오분류하고 source·시간 조건을 버렸다. |
| CORE-027 | PARTIAL | 가용 여부 답변은 유지했지만 일정 생성 금지를 누락하고 source·target을 버렸다. |
| CORE-028 | FAIL | Event CREATE 목적을 DRAFT로 오분류하고 source·target·시간을 버렸다. |
| CORE-031 | FAIL | 새 Task CREATE를 기존 Task UPDATE로 바꾸고 source·target·시간을 버렸다. |
| CORE-036 | PARTIAL | Stage 1은 source와 기한을 잡았지만 Stage 2는 CREATE만 남겼다. |
| CORE-037 | PARTIAL | Stage 1부터 Atlas 메일·인쇄소 슬롯 source를 구조화하지 않았다. |
| CORE-046 | PARTIAL | 두 산출물은 나눴지만 Stage 2가 source·target·시간을 버리고 planned-spec relation도 만들지 않았다. |
| CORE-048 | PARTIAL | 세 effect는 유지했지만 실행 완료처럼 표현했고 Stage 2가 source·target·시간을 버렸다. |
| CORE-050 | FAIL | Event CREATE effect를 누락했고 Task를 17:30까지 완료한다고 과확정했으며 typed carry도 실패했다. |
| CORE-051 | FAIL | 회의 준비 내용 정리 답변을 Gmail Draft로 오분류했다. |
| CORE-056 | FAIL | 사고 요약·대응 정리 답변을 Gmail Draft로 오분류했고 실제 실행 금지를 누락했다. |
| CORE-059 | PARTIAL | Stage 1은 Reply SEND를 맞췄지만 Stage 2가 SEND field를 버렸다. |

PASS는 CORE-006/010/011/012/040/041/054다. 이 중 CORE-006/010/041은 optional
금지 필드의 이득이 확인됐고, CORE-040은 source/target/effect까지 Stage 2에 정확히
전달됐다.

## Relation 관찰

이번 후보는 relation 구조를 변경하지 않았다.

- CORE-019: 두 효과를 한 WorkUnit으로 합쳐 relation을 만들 수 없었다.
- CORE-046: Event와 Draft를 나눴지만 relation은 0개였다.
- CORE-021: 내부 단계를 잘못 승격한 뒤 범용 `PROVIDES_INPUT_TO`를 만들었다.

따라서 relation State 실험으로 넘어갈 근거는 아직 부족하다. relation 이전에
Stage 1의 effect 의미와 Stage 1 → Stage 2 typed carry가 안정돼야 한다.

## 판단

`two-stage semantic-state v1`은 **REJECT**다. Production flat baseline은 유지하고,
corrected evaluation의 기준 후보도 `minimal v1`/`two-stage v1` HOLD 상태를 유지한다.

다음 후보를 만든다면 규칙이나 few-shot을 늘리지 않고 먼저 다음 두 책임을 분리해야
한다.

1. Stage 1이 확정한 optional typed 의미를 Stage 2 LLM이 재생성하지 않도록
   deterministic state carry 경계를 둔다.
2. decomposition owner가 자유롭게 effect를 재판정할지, 기존 RU의 validated effect
   authority를 참조할지 결정하고 같은 의미를 두 owner가 중복 판정하지 않게 한다.

이 두 경계를 검증하기 전에는 relation type 확장 실험을 진행하지 않는다.
