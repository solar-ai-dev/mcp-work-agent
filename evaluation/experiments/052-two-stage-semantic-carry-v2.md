# 052 — two-stage deterministic semantic carry 후보 비교

Issue: #287

## 범위

`two-stage semantic-state v1`의 두 호출과 업무 경계 규칙은 유지하면서 다음 두
책임만 바꿨다.

1. Stage 1의 optional typed 의미를 Stage 2가 재생성하지 않는다. Stage 1 결과를
   `result_id → unit_id`로만 바꾸어 결정적으로 WorkUnit에 투영한다.
2. decomposition schema에서 `requested_effects`를 제거했다. Effect 판정은 기존
   Request Understanding semantic owner의 책임으로 남긴다.

Stage 2 LLM은 기존 `PROVIDES_INPUT_TO` relation만 생성한다. Node 수, LLM 호출 수,
업무 경계 규칙, few-shot, relation kind는 늘리지 않았다. Product State/Schema/Prompt/
Node/Edge도 변경하지 않은 evaluation-only 후보다.

고정 Core 24를 temperature 0, seed 20260920에서 후보당 1회 실행했다. Holdout/Stress,
Retrieval, Tool 선택, Provider 연결은 사용하지 않았다.

## 결속

- Product SHA: `f76b2edc07d1a5c90e4af26a8949f854d4c2931d`
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Canonical authority SHA-256: `958bf846f3abba243f5b1f98f4962e53435a90b4149dc41855f50002a40f2189`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Stage 1 Prompt SHA-256: `3e938a6fc4980050836dd4647af202d291cc91152137ad930ea4073168aac98f`
- Stage 2 Prompt SHA-256: `280bb55a1160df9397e2d1b27a7c590bc9a04ff9100c0000342d3097882fb248`
- Raw result SHA-256: `50b4d0defd6e03c1a35445894d0394561b05b3d479f9e78aa13bb0ef341a80c6`
- Corrected regrade SHA-256: `b3ef3a192eef7a3f4a78d2c5071e7d8b5a922d1ce51ba6539ea11c7e200dd397`
- Stage 1 schema validity: `24/24`
- Stage 1 → final WorkUnit exact typed carry: `24/24`
- Final decomposition semantic validation: `12/24`
- LLM calls: `48`
- Tokens input/output: `32,464 / 4,224`
- LLM latency 합계: `166,254ms`
- Provider READ/WRITE: `0/0`
- rerun-to-pass: `0`

## corrected semantic evaluation

평가는 exact WorkUnit/Relation 개수가 아니라 Canonical의
`canonical_user_prompt`, `required_semantics`, `forbidden_semantics`로 수행했다.

| 후보 | PASS | PARTIAL | FAIL | calls | tokens in/out | latency | 판단 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| minimal v1 | 8 | 13 | 3 | 24 | 15,558 / 2,691 | 105,113ms | HOLD |
| two-stage v1 | 10 | 12 | 2 | 48 | 26,834 / 3,496 | 136,213ms | HOLD |
| two-stage semantic-state v1 | 7 | 9 | 8 | 48 | 44,323 / 5,952 | 237,659ms | REJECT |
| two-stage semantic-carry v2 | 7 | 13 | 4 | 48 | 32,464 / 4,224 | 166,254ms | **HOLD** |

요청한 오류 축의 비교는 다음과 같다. `typed semantic carry`는 optional typed State가
있던 두 후보에서만 비교한다.

| 오류 축 | minimal v1 | two-stage v1 | semantic-state v1 | semantic-carry v2 |
| --- | ---: | ---: | ---: | ---: |
| `INTERNAL_STEP_PROMOTED` | 10 | 0 | 1 | **0** |
| exact typed semantic carry | N/A | N/A | 10/24 | **24/24** |
| `SOURCE_SCOPE_DROPPED` | 0 | 5 | 3 | **0** |
| `EXPLICIT_PROHIBITION_DROPPED` | 5 | 5 | 3 | **0** |
| `EFFECT_CHANGED` | 2 | 1 | 6 | 2 |
| `FACT_OVERCLAIMED` | 0 | 1 | 2 | 2 |

`requested_effects` enum을 제거해 decomposition이 effect authority를 중복 소유하는
문제는 없어졌다. 다만 자유 문자열 `objective` 자체가 CORE-011과 CORE-031에서
effect를 바꿨으므로 `EFFECT_CHANGED`가 0이 된 것은 아니다. 이는 effect field carry
문제가 아니라 Stage 1 objective의 의미 변경이다.

## 무엇이 좋아졌고 무엇이 틀렸는가

목표했던 두 경계는 개선됐다.

- Stage 1의 optional typed 의미가 final WorkUnit까지 `24/24` 정확히 유지됐다.
- Source 범위와 명시적 금지의 drop은 각각 `0`건이다.
- two-stage의 업무 경계 개선도 유지되어 내부 조회·분석 단계를 독립 업무로 승격한
  Case는 `0`건이다.
- decomposition이 `requested_effects` enum을 만들지 않으므로 기존 RU effect owner와
  authority가 중복되지 않는다.

반면 다음 문제가 남았다.

- Stage 2 relation-only LLM이 12개 Case에서 self-relation 또는 WorkUnit이 아닌
  source/target 문자열을 endpoint로 사용했다. 이 때문에 final semantic validation은
  `12/24`다.
- CORE-011은 Draft를 SEND로, CORE-031은 Task CREATE를 인계 확정으로 바꿨다.
- CORE-019는 필요한 확인 전 워크숍 일정을 확정했다고 과장했고, CORE-020은 미완료
  Task를 완료로 과확정했다.
- optional field가 그대로 전달되는 만큼 Stage 1의 잘못된 typed 배치도 보존됐다.
  8개 Case에서 금지 없음 표식, 금지 문장의 temporal 중복, `한 번에`의 temporal
  오분류가 있었다.

### Case별 비통과 사유

| Case | 판정 | 최초 의미 손실과 실제 결과 |
| --- | --- | --- |
| CORE-001 | PARTIAL | 선택 메일 범위와 검색 금지는 보존했지만 금지를 temporal에도 중복하고 self-relation을 만들었다. |
| CORE-011 | FAIL | Draft 작성 요청을 초안 작성 후 발송하는 SEND 의미로 바꿨다. |
| CORE-012 | PARTIAL | Task·Calendar 근거와 Draft 의미는 보존했지만 self-relation을 만들었다. |
| CORE-019 | FAIL | 소요시간 확인 없이 일정을 확정한다고 과장했고 planned specification relation도 만들지 못했다. |
| CORE-020 | FAIL | 미완료 여부를 확인해야 하는 Task를 완료로 과확정하고 수신자 주소를 relation endpoint로 썼다. |
| CORE-021 | PARTIAL | 내부 단계 승격은 막았지만 원문에 없는 포괄 금지와 self-relation을 추가했다. |
| CORE-027 | PARTIAL | 가용시간 답변과 일정 생성 금지는 보존했지만 self-relation을 만들었다. |
| CORE-031 | FAIL | 새 Task CREATE를 인계 작업 확정으로 바꾸고 원문에 없는 금지 없음 표식과 self-relation을 추가했다. |
| CORE-036 | PARTIAL | 메일·Calendar와 월요일 기한은 보존했지만 self-relation을 만들었다. |
| CORE-037 | PARTIAL | Task UPDATE와 Source·기한은 보존했지만 금지 없음 표식과 self-relation을 추가했다. |
| CORE-040 | PARTIAL | Task 메모 UPDATE는 보존했지만 Source/target 문자열을 relation endpoint로 사용했다. |
| CORE-041 | PARTIAL | 세 Source와 생성 금지는 보존했지만 `한 번에`를 temporal constraint로 오분류했다. |
| CORE-046 | PARTIAL | Event와 Draft는 분리했지만 범용 relation이 planned specification을 구분하지 못하고 생성 전 Event를 생성된 일정처럼 표현했다. |
| CORE-048 | PARTIAL | 세 업무 의미는 보존했지만 원문에 없는 금지 없음 표식을 추가했다. |
| CORE-050 | PARTIAL | Task·Event·Draft 의미는 보존했지만 금지 없음 표식과 self-relation을 추가했다. |
| CORE-051 | PARTIAL | 준비 내용 정리는 보존했지만 원문에 없는 금지 없음 표식을 추가했다. |
| CORE-059 | PARTIAL | Reply SEND 의미는 보존했지만 self-relation을 만들었다. |

PASS는 CORE-006/009/010/026/028/054/056이다.

## Relation 관찰과 다음 단계

이번 후보는 relation schema나 규칙을 최적화하지 않았다. 그 결과 relation 생성이
현재 가장 큰 인접 실패 경계로 드러났다.

- invalid relation: `12/24`
- required relation missing: `1/24` (CORE-019)
- relation meaning untyped: `1/24` (CORE-046)

따라서 **다음 bounded evaluation 후보로 relation State를 실험할 근거는 충분하다.**
다만 semantic-carry v2 자체를 Production에 채택한다는 뜻은 아니다. 다음 실험은
WorkUnit endpoint와 `NO_RELATION`을 결정적으로 제한하고, 내부 파생 product와 승인 전
planned specification을 구분할 수 있는 owner-local typed relation 표현이 필요한지를
검증해야 한다. 새 규칙·few-shot·Node를 추가하는 방식은 사용하지 않는다.

## 판단

`two-stage semantic-carry v2`는 **HOLD**다.

요청한 두 원인인 Stage 2 typed 의미 재생성과 decomposition effect authority 중복은
해소됐다. 그러나 4개 FAIL의 Stage 1 objective 의미 변경과 12개 invalid relation이
남아 Production flat baseline은 유지한다. 다음 단계는 evaluation-only relation State
후보로 제한하며, 채택 여부는 relation 오류와 기존 PASS 회귀를 다시 비교한 뒤 판단한다.
