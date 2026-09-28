# Selected Source identity 귀속 — evaluation-only connected prototype

상태: **직접 component gate 통과 / Product migration·모델 의미 판단 미검증**.
조사 기준 `7e75e817`, 직접 테스트 완료 시 HEAD `0e7b6680`.
병렬 작업의 Product 변경은 이 후보의 변경이나 검증 성과로 계산하지 않는다.

## 최초 손실과 계약 선택

Source requirements 후보는 동일 Resource의 서로 다른 필요 정보와 WorkUnit을
표현할 수 있지만, 현재 Product Source item에는 선택 identity binding이 없다.
`SINGULAR`은 대상 범위이지 선택 ref의 authority가 아니다.

| 경계 | 현재 확인한 손실 | 채택 시 필요한 owner-local 변경 |
| --- | --- | --- |
| Source decision | `required_information / target_scope / work_unit_ids`만 반환해 두 선택 대상의 귀속을 표현하지 못함 | 기존 Source owner가 현재 Run `SelectedResourceRef.resource_ref_id`의 closed set을 선택 |
| selected authority | `identify_goal._apply_selected_resource_authority`가 Resource 종류별 WorkUnit union에 native selected ID를 붙임 | 확정 ref binding만 해석; native ID·SINGULAR로 귀속을 추론하지 않음 |
| Source normalizer | `(resource_type, work_unit_ids)`로 합치므로 같은 업무의 서로 다른 대상도 합쳐짐 | acquisition binding이 다른 Source는 별도로 유지 |
| I/O 및 Registry binder | Resource 종류별 dictionary/set으로 target 차이를 제거 | 동일 acquisition만 union; capability lookup 결과는 공유 |
| exact Retrieval binding | `bind_exact_resource_refs`가 connector/type의 모든 selected ref를 한 Route에 넣음; 두 ref이면 충돌 | 해당 Route에 명시 결속된 ref만 전달 |
| Query | 잘못 합쳐진 Route가 선택 상세조회 하나로 축소될 수 있음 | 다른 target은 다른 기존 route ID; 기존 Query validator에서 exact ref membership 검증 |

현재 Constraint에는 `TARGET` kind가 없다. 가장 가까운
`RESOURCE/selected_resource_id + work_unit_ids`도 native ID만 갖고,
connector·선택 ref·개별 Source item을 연결하지 않는다.
`source_resource_type`은 현재 status constraint에만 허용된다.
Constraint를 새 identity owner로 늘리기보다 **Source item-owned closed ref**가 작다.
새 semantic artifact ID는 만들지 않는다.

## 구현 범위

- `scripts/ru_selected_source_binding_candidate.py`
- `tests/evaluation/test_ru_selected_source_binding_candidate.py`

기존 비활성 `ru_source_requirements_candidate`의 Resource exact-set 및 각 requirement
schema를 재사용하고 `selected_resource_ref_ids` 하나만 추가한다.
필드는 현재 Run selection에 있는 ref의 non-empty closed list다. 이 prototype은
exact-selected SINGULAR acquisition만 다루며 CRITERIA/discovery를 명시적으로 거절한다.
SINGULAR만 있고 ref binding이 없는 입력은 거절한다.

각 requirement의 정보·WorkUnit은 기존 Source validator로 검증한다. 모든 current
selected ref에 명시적 Source WorkUnit binding이 있어야 하며, 미귀속 선택을 다른
WorkUnit으로 넓히거나 조용히 생략하지 않는다. Resource/connector 불일치, 다른 Run ref,
native ID를 ref 대신 제출한 값, 잘못된 WorkUnit, 중복 및 미지원 payload는 거절한다.

검증된 ref를 실제 `SelectedResourceRef`로 해결한 뒤
`connector + resource_type + resource_id + parent`가 같은 acquisition만 합친다.
같은 대상의 applicable WorkUnit은 union하지만 서로 다른 target의 사실 요구는
각 Source requirement에 남긴다. 동일 native identity를 가리키는 두 검증 ref는
ref membership을 보존하며 READ를 공유한다.

Registry capability 조회는 Resource마다 한 번만 하고 결과를 acquisition Route에
fan-out한다. 기존 `exact_resource_detail_plan`을 각 exact Route에 적용하고 결과를
모아 `validate_retrieval_query_plan_v2 → build_query`에 통과시킨다.
새 Tool 선택 LLM, Query LLM, Node, 실행 승인, Output effect는 만들지 않는다.

새 binding은 **evaluation-owned acquisition envelope**에만 둔다. Product V3에
미등록 필드를 몰래 넣거나 strict validator를 우회하지 않는다. Product ToolRoute
shape는 그대로 검증하며, 이 envelope가 Production 계약을 이미 닫았다고 주장하지 않는다.

## 직접 검증 결과

신규 **28 PASS**. Source requirements 및 관련 Registry/exact binding/container tests를
포함한 고정 집합 **69 PASS**. Ruff 및 두 파일 mypy PASS.

| 입력/반례 | 관측 |
| --- | --- |
| 같은 selected ref, 두 WorkUnit | Route 1, 실제 Product `execute_read` consumer → fake Connector READ 1, capability lookup 1 |
| 서로 다른 selected ref, 두 WorkUnit | Route 2, fake READ 2, capability lookup 1; 각 native target과 WorkUnit 귀속 일치 |
| 같은 WorkUnit·동일 정보·서로 다른 selected ref | 기존 종류/업무 key로 합치지 않고 requirement와 acquisition 2개 유지 |
| 두 ref가 같은 검증 identity를 가리킴 | ref membership을 보존하며 acquisition 1개 |
| ref 없는 SINGULAR / 미귀속 selected identity | 기존 선택 전체나 모든 WorkUnit을 추론하지 않고 거절 |
| 다른 Route의 exact ref 대입 | 기존 Query validator가 거절 |
| 같은 Product detail ref 문자열인데 parent가 다름 | 기존 `type:id` 표현 한계를 숨기지 않고 거절 |
| mixed selected/discovery | 범위 정책을 자동 확대하지 않고 거절 |

READ 횟수는 **fake Connector** 관측이다. 실제 Provider, 모델 및 LLM 호출은 0이다.
첫 테스트에서 잘못된 Registry version property 접근으로 실패한 fixture 2건을 수정했고,
최종 69건 결과에 포함했다. 모델 Trial 재실행이나 rerun-to-pass는 없다.

```powershell
.venv/Scripts/python.exe -m pytest tests/evaluation/test_ru_selected_source_binding_candidate.py tests/evaluation/test_ru_source_requirements_candidate.py tests/unit/application/agents/retrieval/test_bind_exact_resource_refs.py tests/unit/application/agents/retrieval/test_resolve_route_container_scopes.py tests/unit/application/agents/tool_routing/test_bind_registry_candidates.py tests/unit/application/agents/tool_routing/test_validate_route.py -q
.venv/Scripts/python.exe -m ruff check scripts/ru_selected_source_binding_candidate.py tests/evaluation/test_ru_selected_source_binding_candidate.py
.venv/Scripts/python.exe -m mypy --follow-imports=silent --explicit-package-bases scripts/ru_selected_source_binding_candidate.py tests/evaluation/test_ru_selected_source_binding_candidate.py
```

## Production migration 영향 — 아직 구현하지 않음

| 계약 | 현재 | 필요한 migration |
| --- | --- | --- |
| Source owner schema | `request-source-dependency-decision-v3` | requirements 및 closed ref를 선언한 새 output schema/version; Source Prompt 형상/manifest/hash 함께 정합화 |
| RequestIntent Source item | V3 strict exact-key, 별도 Source item version 없음 | 새 required binding을 담는 artifact schema/version 경계 필요. 기존 V3에 빈 ref를 기본 주입해 의미를 추정하지 않음 |
| Tool Route | `InputRoutePlanV1 / ToolRoutePlanV2`, Resource별 route | target binding 및 acquisition identity를 명시한 새 계약. capability 공유와 실제 대상별 Route를 분리 |
| Query | 기존 route ID 및 `DETAIL_FETCH` 형식 | operation schema 자체는 재사용 가능. frozen-route projection·exact/container ref binding은 route-local로 변경 |
| selected parent/container | 현재 전체 selected 목록에서 Task/Calendar parent를 결속 | route에 실제 결속된 ref만 사용. 이번 Gmail fake gate로 이 변경의 완료를 주장하지 않음 |
| Checkpoint/resume | `resume-contract-v3` | Product 채택 시 새 graph/resume version. 기존 persisted payload를 조용히 승격하지 않음 |
| Approval/Preview | 기존 출력 route·승인·실행·검증 authority | 의미 변경 없음. 전체 Planning/Preview 연결 성공은 이번 범위 밖 |

`RESOURCE_SELECTED`의 전역 IN Route 고정 문구가 명시적인 별도 미선택 검색에도
적용되는지, 선택 대상 WorkUnit에만 적용되는지는 Canonical05/06 정합화가 필요하다.
이 정책 선택과 **이미 허용된 selected identity의 오귀속 복구**를 분리한다.
현재 prototype은 범위 안 exact identities만 다뤄 검색 scope를 새로 허용하지 않는다.

실제 Source LLM의 ref 선택 품질, Gmail Thread/Message alias binding,
Task/Calendar/GitHub의 container 연결, full compiled Production 및 Preview는 미검증이다.
결론은 **bounded exact-selected handoff 구조 가능성 확인**이며 Product ADOPT가 아니다.

추가 정보 가용성 제한: 현재 `SelectedResourceRef`는 ref/connector/type/native ID/parent만
갖고 제목·본문 같은 업무 식별 정보를 갖지 않는다. 사용자가 제목으로 두 선택 자료를
구분했는데 입력에는 opaque ID만 있다면 Source LLM이 어느 ID인지 추측해서는 안 된다.
이 component는 이미 올바르게 결속된 typed 후보의 전달을 검사한 것이지, 조회 전에도
항상 그 후보를 생성할 정보가 있다는 증명이 아니다. 선택 범위 안의 후보를 함께 읽는 것과
각 업무의 확정 target/정답 근거로 binding하는 것을 구분해야 한다. Production 채택 전에는
명시 binding이 있는 입력과 조회 후에만 구분 가능한 입력의 책임 경계를 별도로 검증한다.
