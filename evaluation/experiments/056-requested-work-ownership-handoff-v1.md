# 056 — RequestedWork ownership / handoff contract 검토

Issue: #288, 근거 실험: #287 046~055

## 결론

`RequestIntentV3` 후보는 `RequestedWorkDefinitionV1`을 같은 Request Understanding
Artifact 안에 포함하고, 기존 semantic item이 `work_unit_ids`를 직접 소유하는 방식으로
진행하는 것이 가장 단순하다.

별도 stable local ID와 binding table은 선택하지 않는다. 현재 item에는 stable ID가 없고,
새 ID를 추가해도 의미 owner가 아닌 별도 binding owner, orphan/stale reference 검증과 revision
matching이 추가된다. Core 24 projection에서 의미 보존이나 점수 개선 없이 local ID 89개와
binding record 89개가 추가됐다.

Production 구현은 아직 시작하지 않는다. 현재 `ResourceResponsibilitiesV1`과 validator가
Source는 `resource_type`, Output은 `(resource_type, effect)` 하나로 집계하므로 같은
Resource/effect의 서로 다른 WorkUnit을 표현하려면 V3 consumer migration이 필요하다. 이
경계를 먼저 닫지 않고 `RequestIntentV2`에 필드만 추가하면 두 업무가 다시 합쳐진다.

## 현재 구조와 최초 handoff gap

현재 Request Understanding은 `identify_goal` runtime Node 안에서 goal, effect prohibition,
Source dependency, Output responsibility, Source status를 atomic operation으로 판단한다.
`finalize_intent`는 이를 하나의 `RequestIntentV2`로 검증·revision하고 Main State의
`request_intent`에 둔다.

그러나 다음 연결이 없다.

```text
독립 WorkUnit
→ Constraint / Source / Output / Effect applicability
→ typed WorkRelation
→ downstream consumer
```

`RequestIntentV2`에는 WorkUnit도 semantic item별 applicability도 없다. 따라서 #287의
evaluation 후보는 WorkUnit 안에 semantic 문자열을 복제하거나 shared/local category를
새로 판단해야 했고, 그 경계가 v4/v5 회귀의 최초 divergence가 됐다.

## binding 구조 비교

| 기준 | semantic item이 `work_unit_ids` 소유 | stable local ID + 별도 binding |
| --- | --- | --- |
| 의미 producer | 기존 Constraint/Source/Output/Effect owner | 기존 owner + binding producer가 추가로 필요 |
| shared 의미 | 한 item에 여러 WorkUnit ID | 한 item ID를 binding table에서 여러 WorkUnit에 연결 |
| 문자열 복제 | 없음 | 없음 |
| reference layer | WorkUnit ID 하나 | WorkUnit ID + semantic local ID |
| revision | RequestIntent revision 안에서 전체 재검증 | item ID 유지/matching/orphan 정리가 추가됨 |
| 동일 값의 별도 업무 | item의 WorkUnit 집합과 owner item granularity로 구분 | content-derived ID는 충돌하고 random ID는 revision matching 필요 |
| Core 24 round-trip | 24/24 | 24/24 |
| Core 24 binding validation | 24/24 | 24/24 |
| semantic items / WorkUnit refs | 89 / 90 | 89 / 90 |
| 추가 local IDs / binding records | 0 / 0 | 89 / 89 |
| 선택 | **ADOPT 후보** | **REJECT** |

두 방식 모두 v3의 잘못된 exact span 5건을 그대로 보존하므로 전체 contract validation은
19/24다. 이는 binding 오류가 아니라 기존 WorkUnit producer 오류다. semantic 판정도
v3와 동일한 `PASS 14 / PARTIAL 10 / FAIL 0`이며, 구조 projection이 결과를 개선했다고
주장하지 않는다.

## producer → validator → state → projection → consumer → revision owner

| semantic concept | authoritative producer | validator | State | projection | consumer | revision owner |
| --- | --- | --- | --- | --- | --- | --- |
| WorkUnit boundary | Request Understanding의 새 owner-local `identify_requested_work` supporting operation | ID unique, span provenance가 현재 user request에 결속, unit 1개 이상 | `RequestIntentV3.requested_work.work_units` | WorkUnit ID + bounded provenance만 각 atomic owner에 전달 | RU의 기존 atomic owner, 이후 Work Analysis/Planning/Review | Request Understanding `finalize_intent` |
| Goal / completion | 기존 `identify_goal` | 기존 goal candidate validator + referenced WorkUnit ID closed set | 기존 V3 goal/completion item에 `work_unit_ids` | 전체 문자열 재복제 없이 owner item 그대로 | Retrieval sufficiency, Work Analysis, Planning, Review | Request Understanding |
| Constraint | 현재 constraint를 만든 goal/source-status/temporal operation | 기존 provenance/field validator + non-empty known `work_unit_ids` | `RequestIntentV3.constraints[]` | 해당 constraint item 그대로 | Tool Route policy projection, Retrieval, Planning, Review | 해당 RU atomic producer를 거친 Request Understanding revision |
| Source responsibility | `identify_source_dependencies` | Resource/fact/scope validation + known `work_unit_ids`; exact duplicate만 거절 | `resource_responsibilities.source_reads[]` | Tool Route와 Retrieval에 owner item 전달 | Tool Route, Retrieval, Work Analysis | Request Understanding |
| Output responsibility / positive effect | `identify_output_responsibilities` | Resource/effect compatibility + known `work_unit_ids`; exact duplicate만 거절 | `resource_responsibilities.outputs[]` | Output route 후보에 WorkUnit ID 보존 | Tool Route, Planning, Review | Request Understanding |
| Explicit effect prohibition | `identify_effect_prohibitions` | supported effect exact set + known `work_unit_ids` | V3의 typed effect prohibition item | Policy/Planning/Review에 금지 item만 전달 | Tool Route policy, Planning, Review | Request Understanding |
| WorkRelation | WorkUnit과 위 semantic item이 확정된 뒤의 RU owner-local `identify_work_relations` supporting operation | endpoint가 현재 WorkUnit ID, self-edge 금지, closed relation kind | `requested_work.work_relations[]` | relation과 referenced WorkUnit만 전달 | Work Analysis, Planning, Review | Request Understanding |
| RequestIntentV3 artifact | `finalize_intent` | 모든 unit ref, provenance, resource/effect consistency와 meta validation | Main State `request_intent` 단일 authority | 기존 owner projection이 필요한 V3 slice만 읽음 | Tool Route → Retrieval → Work Analysis → Planning → Review | Request Understanding only |

### WorkRelation 경계

허용 후보는 사용자 요청 업무 사이 의미만 표현한다.

- `CONSUMES_WORK_PRODUCT`: 앞 업무의 same-Run 내부 파생 결과를 뒤 업무가 입력으로 소비
- `CONSUMES_PLANNED_SPECIFICATION`: 승인 전 외부 결과가 아니라 앞 업무의 계획 명세를 참조

Tool 실행 순서, Approval, Policy, Planning Action dependency, Provider 결과, Execution과
Verification은 WorkRelation이 소유하지 않는다. 관계는 WorkUnit과 semantic item이
검증된 뒤 판단하며, relation 결과가 기존 owner 값을 수정하지 않는다.

## 후보 V3 shape

```text
RequestIntentV3
├─ existing goal / completion fields
├─ requested_work
│  ├─ work_units[]
│  │  ├─ unit_id                 # finalized span order로 deterministic assignment
│  │  └─ request_provenance[]    # current user request offset authority
│  └─ work_relations[]
├─ constraints[]                 # + work_unit_ids
├─ resource_responsibilities
│  ├─ source_reads[]             # + work_unit_ids
│  └─ outputs[]                  # + work_unit_ids
└─ effect_prohibitions[]         # + work_unit_ids
```

WorkUnit에는 Source/target/time/prohibition 문자열을 복제하지 않는다. 모든 semantic item은
적용되는 WorkUnit ID를 명시하며, 별도 shared/local category나 implicit "전체 적용" default는
두지 않는다. WorkUnit ID는 RequestIntent revision-local identity이며 별도 장기 Artifact ID가
아니다.

## prototype 결과

- Product HEAD: `f173fe66cfe57e233d61b5c6d812cb9a7796c505`
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Model/digest: `qwen3.5:9b` / `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- 현재 HEAD v3 고정 Trial: 48 calls, tokens `32,604 / 3,561`, latency `149,726ms`
- 과거 053과 candidate output: runtime metadata를 제외한 24/24 JSON candidate 동일
- current-HEAD source result SHA-256: `83990b7133ec14cb761da4d088d71e68f18b67c26087d4cd557f7d824fb482c8`
- binding contract result SHA-256: `b51d62206b78f8e7485639fffac46820580002af07d4e03df59fe5764de2f5b7`
- binding prototype 추가 LLM call: 0
- Prompt/Few-shot 변경: 0
- inline binding validation / round-trip: 24/24 / 24/24
- local-ID binding validation / round-trip: 24/24 / 24/24
- semantic 결과: `14 PASS / 10 PARTIAL / 0 FAIL`, v3와 동일
- Provider READ/WRITE: `0/0`
- rerun-to-pass: `0`

결과:

- `semantic item owns work_unit_ids`: **구조 후보 ADOPT**
- `stable local ID + separate binding table`: **REJECT**
- `RequestIntentV3` Production migration: **HOLD**

HOLD 이유는 같은 Resource/effect의 복수 업무를 현재 Tool Route와 Output Route가 합치지
않도록 producer/validator/consumer를 같은 변경 단위에서 갱신해야 하기 때문이다. 이 위험은
owner-local evaluation projection만으로 닫을 수 없으므로 production 구현을 확대하지 않았다.

## 산출물

- `evaluation/requested_work_binding_contract.py`
- `scripts/evaluate_ru_requested_work_binding_contract.py`
- `evaluation/tests/test_requested_work_binding_contract.py`
- `evaluation/results/ru288-requested-work-binding-contract-v1-core24-20260921/`
