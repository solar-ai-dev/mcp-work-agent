# 내부 Agent Prompt — 적용 전 후보

이 디렉터리는 **제품 내부 LLM 호출에 사용할 Prompt 수정 후보**다. 시험용 사용자 질문은 `../../datasets/`에 있다. 이 파일들과 `sources/`를 Google·GitHub 업무 자료로 올리지 않는다.

## 본문 수정 범위

원본의 21개 역할과 경로를 유지하고 각 본문을 Responsibility / Input boundary / Decision procedure / Boundaries / Output and repair로 정리했다. 일반적인 규칙의 반복은 줄이고 각 호출이 실제로 결정할 것과 결정하지 않을 것을 구분했다.

- Request Understanding: 부정·인용·일반 역할과 실제 사람, 시간 표현의 여러 역할, 원래 사용자 제약을 보존한다. 독립 시간축 owner의 결과를 다시 덮어쓰지 않는다.
- Retrieval: 사용자 제약과 검색 가설을 구분하고 실제 관측으로 다음 search/page/detail을 선택한다. Evidence의 관련성·모든 segment의 선택/제외·취소와 정정·연도 불확실성을 보존한다. Sufficiency가 보지 못한 candidate/coverage를 있다고 가정하지 않는다.
- Work Analysis: 사실·관계·의존·중복·누락·위험의 책임을 분리하고 원본의 necessity/empty-result 조건과 ID namespace를 유지한다.
- Planning: 본문 제안·Draft 저장·SEND·Reply를 구분하고 부분 수정의 미언급 필드를 보존한다. 외부 결과를 미리 성공으로 쓰지 않는다.
- Review: 담당 dimension의 실제 결함만 반환한다. 정상 finding을 만들거나 해결된 옛 결함을 반복하지 않고 영향을 받지 않은 dimension은 재검토하지 않는다.

이들은 **오프라인 수정 후보**이지 실제 9B/4B 개선 결과가 아니다. 원본처럼 내부 지시 언어는 영어이며, 생성 답변은 사용자가 요청한 언어를 따른다. 시험 질문/Gold/Case ID를 내부 Prompt에 넣지 않았다.

## 원래 경로와 연결 유지

`evaluation/prompt_candidates/mcp-tool-use-2026-v1/`와 각 `sources/<slot_id>.md`를 유지한다. `candidate.json`의 candidate ID, slot ID, source 경로, Product manifest/input-contract 경로는 그대로다. 본문 개정에 해당하는 candidate/Prompt 버전과 hash만 갱신하고 DRAFT 및 activation evidence의 false를 유지한다. `base_product_sha`는 첨부 원본의 출처이지 최신 로컬 실행을 검증했다는 표시가 아니다.

이전 `planning-review-sllm-decomposition-v0.9.2`의 source/assembled/입력 계약은 비활성 비교자료다. 이 묶음의 옛 7-slot 또는 fragment 구성을 현재 제품에 병합하지 않는다. 21개도 현재 로컬 제품의 전체 slot 수를 강제하는 숫자가 아니다.

## 후보 사본 만들기

원래 materializer 경로와 함수 진입점을 유지한다. 저장소 루트에서 다음을 실행한다. 현재 Product manifest·input contract가 실제로 있어야 한다.

```text
python -m evaluation.prompt_candidates.mcp-tool-use-2026-v1.materialize_prompt_candidate --repository-root <repository-root> --output <empty-temporary-directory>
```

기본값은 후보·Product manifest·input-contract의 slot 집합이 모두 일치해야 한다. 현재 제품에 추가 slot이 있다면 먼저 그 책임과 schema를 대조하고, 변경하지 않을 추가 source를 보존하는 경우에만 명시적으로 사용한다.

```text
python -m evaluation.prompt_candidates.mcp-tool-use-2026-v1.materialize_prompt_candidate --repository-root <repository-root> --output <empty-temporary-directory> --keep-extra-product-slots
```

추가 slot의 source bytes·prompt_version·content_hash·runtime/schema binding은 유지한다. 입력 계약은 바이트 그대로 복사한다. 새로 조합한 후보 묶음은 모든 slot을 DRAFT/미검증으로 만들므로 과거 activation evidence를 새 묶음의 PASS로 재사용하지 않는다. 추가 source 누락/변조, 후보에만 있는 unknown slot, manifest/input-contract 불일치, version 불일치는 거부한다. 없는 시간축 Prompt를 생성하거나 22를 또 고정값으로 넣지 않는다.

출력은 별도의 비어 있는 임시 경로에만 만들고 기존 Product/후보 source와 겹치거나 기존 파일을 덮어쓰는 경로는 거부한다. 검증을 먼저 완료한 뒤 사본을 만들며 실패한 binding 뒤 부분 사본을 남기지 않는다. 이 명령은 제품을 실행하거나 Prompt를 활성화하지 않는다.

생성된 DRAFT 묶음은 기존 Product composition의 명시적 개발 입력으로만 선택한다. 새 Registry나
별도 Graph를 만들지 않으며, `<materialized-directory>/prompt_manifest.json`을 다음 경로에 전달한다.

```text
python -m launcher.development_entrypoint --prompt-manifest <materialized-directory>/prompt_manifest.json
python scripts/measure_local_runtime.py --prompt-manifest <materialized-directory>/prompt_manifest.json
```

두 명령 모두 같은 Product `PromptRegistry`와 production Graph/Node caller를 사용한다. 인자를
생략하면 기존 baseline manifest를 사용하고, signed release는 이 개발 후보 경로를 허용하지 않는다.
개발 앱 기동이나 Graph 로딩 성공은 Prompt 품질 또는 activation PASS가 아니다.

## 실제 적용 전 확인

현재 로컬의 최종 caller·입출력 schema·새 시간축 Prompt는 첨부본에 없다. 따라서 필드/enum/책임 일치와 실제 모델의 구조화 출력은 로컬에서 확인해야 한다. manifest metadata가 일치한다는 사실만으로 의미 호환을 보증하지 않는다.

특히 이 후보의 ambiguity/necessity/empty-result 지침이 참조하는 필드는 원본 계약을 유지한 것이다. 현재 계약이 다르면 Prompt와 해당 caller를 함께 대조한다. Prompt 안에서 "구버전이면 이 필드를 새로 만들라"는 방식으로 해결하지 않는다. 없는 입력을 발명하거나 기존 구조·안전 검증을 약화하지 않는다.

같은 업무 자료와 질문에서 현재 Prompt와 후보를 비교한다. 실제 사용 모델·커밋·변경·결과는 [실행 기록](../../실행기록.md)에만 간단히 남긴다. source review/구조 검사/임시 사본 생성은 제품·모델 품질 PASS가 아니다.

## 책임별 원문

| 책임 | 후보 |
| --- | --- |
| request_understanding | [identify_goal](sources/request_understanding.identify_goal.md) — Identify the current request |
| request_understanding | [detect_ambiguity](sources/request_understanding.detect_ambiguity.md) — Locate genuine unresolved user choices |
| tool_routing | [determine_io_resources](sources/tool_routing.determine_io_resources.md) — Determine the semantic input and output needs |
| tool_routing | [select_tool_if_needed](sources/tool_routing.select_tool_if_needed.md) — Select within the supplied Tool candidates |
| retrieval | [plan_query](sources/retrieval.plan_query.md) — Plan the next useful information acquisition |
| retrieval | [select_evidence](sources/retrieval.select_evidence.md) — Select material evidence, not merely matching text |
| retrieval | [assess_sufficiency](sources/retrieval.assess_sufficiency.md) — Decide whether the collected evidence meets the request |
| work_analysis | [extract_work_facts](sources/work_analysis.extract_work_facts.md) — Extract business facts from admitted evidence |
| work_analysis | [resolve_entity_relations](sources/work_analysis.resolve_entity_relations.md) — Resolve supported entity relationships |
| work_analysis | [resolve_temporal_dependencies](sources/work_analysis.resolve_temporal_dependencies.md) — Interpret evidenced temporal and work dependencies |
| work_analysis | [detect_duplicate_conflict_candidates](sources/work_analysis.detect_duplicate_conflict_candidates.md) — Identify meaningful duplicate and conflict candidates |
| work_analysis | [assess_information_gaps](sources/work_analysis.assess_information_gaps.md) — Identify the information needed for the requested result |
| work_analysis | [assess_operational_risks](sources/work_analysis.assess_operational_risks.md) — Assess evidence-grounded operational risks |
| planning | [outline_answer](sources/planning.outline_answer.md) — Outline a grounded answer |
| planning | [compose_answer](sources/planning.compose_answer.md) — Compose the answer supported by the outline and evidence |
| planning | [draft_action_objective_per_output_route](sources/planning.draft_action_objective_per_output_route.md) — Draft the objective for one frozen output route |
| planning | [compose_arguments_per_output_route](sources/planning.compose_arguments_per_output_route.md) — Compose supported business arguments for one action |
| review | [inspect_goal_and_evidence](sources/review.inspect_goal_and_evidence.md) — Inspect goal satisfaction and evidence grounding |
| review | [inspect_action_scope_and_route](sources/review.inspect_action_scope_and_route.md) — Inspect action necessity, scope, and frozen route consistency |
| review | [inspect_constraints_and_policy_summary](sources/review.inspect_constraints_and_policy_summary.md) — Inspect the plan against supplied constraints and policy summary |
| review | [recheck_affected_dimensions](sources/review.recheck_affected_dimensions.md) — Recheck the specific dimensions affected by a revision |
