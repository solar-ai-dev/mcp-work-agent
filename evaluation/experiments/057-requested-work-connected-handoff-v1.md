# 057 — RequestedWork downstream connected handoff

Issue: #288, 선행 결정: 056의 item-owned `work_unit_ids`

## 결론

evaluation-only connected prototype은 `Tool Route → Retrieval → Planning`에서
WorkUnit 귀속을 유지하면서 READ와 Tool capability를 공유할 수 있었다. 연결 후보는
**ADOPT_FOR_PRODUCTION_MIGRATION_SCOPE**로 판정한다.

`RequestIntentV3` 자체는 아직 Production에 적용하지 않는다. 아래 contract를 producer부터
consumer까지 한 변경 단위로 migration하기 전에는 V2와 V3를 동시에 semantic authority로
둘 수 없으므로 **HOLD_UNTIL_ATOMIC_MIGRATION**이다.

## 현재 코드의 최초 binding 손실

최초 손실은 Retrieval이나 Planning이 아니라 Tool Route의 semantic candidate projection이다.

```text
RequestIntent resource responsibility item + work_unit_ids
→ determine_io_resources._resource_responsibility_candidate
→ Source: resource_type tuple
→ Output: (resource_type, effect) tuple
→ work_unit_ids 소실
```

Production V2는 그 앞에서도 다음 표현을 허용하지 않는다.

- `validate_resource_responsibilities`는 Source를 `resource_type` 하나로 unique하게 제한한다.
- Output은 `(resource_type, effect)` 하나로 unique하게 제한한다.
- 현재 item field set에 `work_unit_ids`가 없다.

따라서 같은 capability가 여러 WorkUnit에 필요하다는 사실과 같은 Resource/effect의 서로 다른
사용자 결과를 V2가 구분할 수 없다.

## 현재 경계 조사

| 경계 | 현재 유지되는 값 | binding이 사라지는 방식 | 유지할 구조 |
| --- | --- | --- | --- |
| RU → Tool Route | Source resource type, Output resource/effect | `SemanticRouteCandidate`에 WorkUnit ID가 없음 | owner item의 `work_unit_ids`를 결정적으로 route projection |
| Input route binding | Resource별 one route | `_bind_input_routes`가 `set(resource_types)`로 capability를 dedupe | route는 공유하고 WorkUnit ID union 유지 |
| Output route binding | tuple 항목별 unique `route_id` | V2 validator가 같은 pair를 먼저 거절하고 route에는 binding이 없음 | output owner item 하나당 route 하나, capability 선택은 pair별 공유 |
| Retrieval Query/READ | frozen `route_id` | query/read는 route를 잘 보존하지만 WorkUnit을 알 수 없음 | route requirement projection과 coverage에 WorkUnit binding 추가 |
| Retrieval result | route별 `source_statuses`와 Evidence ref | status에 WorkUnit ID가 없음 | Evidence를 복제하지 않고 route coverage가 applicable WorkUnit을 기록 |
| Planning ACTION | output `route_id`별 objective/arguments/action | route가 binding을 잃었고 각 Prompt에 전체 RequestIntent를 재전달 | route-local owner item/constraint/evidence projection 소비 |
| Planning ANSWER | 전체 RequestIntent + 전체 Evidence | WorkUnit별 Evidence 귀속이 없음 | 호출을 나누지 않고 한 입력 안에 WorkUnit별 Evidence binding 제공 |

현재 좋은 구조는 보존할 수 있다.

- Retrieval의 Query/READ/Result는 이미 frozen `route_id` 단위다.
- Planning ACTION은 이미 output route 하나당 objective와 arguments를 작성한다.
- `finalize_route`의 Tool 선택 map은 `(resource_type, effect)` key이므로 같은 capability 선택을
  여러 output route가 공유할 수 있다.
- Planning assembler는 unique `route_id`를 보존하므로 output owner item을 route까지 살리면
  별도 사용자 결과도 합쳐지지 않는다.

## evaluation-only connected contract

후보는 다음 경계를 사용한다.

1. `InputToolRouteV2` 후보
   - Resource capability별 route 하나
   - 해당 route가 필요한 `work_unit_ids` union
   - Query 의미는 소유하지 않음
2. Retrieval route requirement projection
   - RequestIntent의 exact Source responsibility item을 route별로 결정적 filter
   - 한 route에서 Query/Provider READ 한 번
   - Evidence는 한 번 저장하고 coverage가 여러 WorkUnit에 연결
3. `OutputToolRouteV2` 후보
   - Output responsibility owner item 하나당 route 하나
   - `work_unit_ids` 보존
   - 동일 Resource/effect Tool 선택은 한 capability 결정 공유
4. Planning
   - ACTION: output route별 planned specification과 WorkUnit ID 유지
   - ANSWER: WorkUnit마다 호출하지 않고 하나의 입력에 `evidence_by_work_unit` 제공
   - WorkRelation을 Planning Action dependency로 변환하지 않음
   - Provider WRITE 없음

Tool Route가 `required_information`을 소유하지 않도록 Source owner item은 input route 안에
복제하지 않았다. Retrieval 진입 projection이 current RequestIntent에서 exact owner item을
선택하며, route는 capability와 applicability만 소유한다.

## 결과

- Product HEAD: `961b735a8106dd659e1b3177b2ab69e9de206f07`
- 선행 Core 24 candidate source SHA-256:
  `83990b7133ec14cb761da4d088d71e68f18b67c26087d4cd557f7d824fb482c8`
- connected result SHA-256:
  `145a91353f2ca3f5f84bf076d756f3f1bd3348e987e7528c9030716d40ebcb60`
- Core 24 item-owned binding gate: `24/24`
- 단일 WorkUnit: `22`, 복수 WorkUnit: `2`
- connected contract scenarios: `5/5`
- 새 LLM call: `0`
- 실제 Provider READ/WRITE: `0/0`
- Prompt/Few-shot/Product contract 변경: `0/0/0`
- rerun-to-pass: `0`

| scenario | V2 표현 가능 | projected READ | answer input | capability 선택 | output route | planned spec |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SIMPLE_READ | yes | 1 | 1 | 0 | 0 | 0 |
| SHARED_READ_MULTI_WORK_ANSWER | yes | 1 | 1 | 0 | 0 | 0 |
| SHARED_READ_TWO_WORK_UNITS | yes | 1 | 0 | 1 | 1 | 1 |
| DISTINCT_RESULTS_SAME_WRITE_CAPABILITY | no | 0 | 0 | 1 | 2 | 2 |
| SHARED_AND_DISTINCT_CAPABILITIES | yes | 2 | 0 | 2 | 2 | 2 |

표의 READ와 Planning 수는 Provider/Model 실행 결과가 아니라 contract projection count다.
모든 scenario에서 baseline 대비 projected Provider READ 증가 `0`, capability 선택 증가 `0`,
Provider WRITE `0`이었다. 동일 WRITE capability의 별도 사용자 결과만 V2에서 표현 불가능했고,
후보는 Tool 선택 1회를 공유하면서 route/specification 2개를 보존했다.

## Production migration 범위

다음은 하나의 atomic migration이어야 한다.

1. Request Understanding
   - `RequestIntentV3`, RequestedWorkDefinition, item-owned `work_unit_ids`
   - Source/Output duplicate validation을 exact owner item 기준으로 변경
   - unknown/orphan WorkUnit ref와 current revision provenance 검증
2. Tool Route
   - `SemanticRouteCandidate`가 Source/Output owner item applicability를 잃지 않게 변경
   - Input route에는 shared WorkUnit union, Output route에는 owner item WorkUnit ID 보존
   - input plan reuse equality와 route validator에 binding 포함
   - Tool eligibility/selection은 기존 Registry authority 유지
3. Retrieval
   - Query input에 route별 exact Source responsibility projection
   - `RetrievalSourceStatus` 또는 동등한 typed coverage에 `work_unit_ids`
   - Query, Provider READ, Evidence는 WorkUnit별로 복제하지 않음
4. Planning
   - ACTION objective/argument/action seed에 frozen output route binding 전달
   - raw 전체 Intent에서 Work 귀속을 다시 추론하지 않도록 route-local owner item과
     applicable constraint/evidence만 projection
   - ANSWER는 단일 호출 구조를 유지하며 WorkUnit별 Evidence binding을 입력에 포함
5. validator/revision/tests
   - producer → validator → Main State → projection → consumer를 같은 revision으로 검증
   - simple request call count, shared READ, same-capability distinct output regression 고정

Approval, Policy, Tool 선택 authority, Planning Action dependency, Execution, Verification,
Provider result 의미는 변경하지 않는다. WorkRelation type 최적화나 external Action dependency
변환도 이번 migration 범위에 포함하지 않는다.

## 산출물

- `evaluation/requested_work_connected_handoff.py`
- `scripts/evaluate_ru_connected_handoff.py`
- `evaluation/tests/test_requested_work_connected_handoff.py`
- `evaluation/results/ru288-connected-handoff-v1-core24-20260921-r4/result.json`
