# Prompt 문맥 정리 · 승인된 규칙 변경 반영

- 작업일: 2026-09-11
- 브랜치: `codex/issue-251-connected-contract`
- Prompt 수정 커밋: `34150a269bfd1ad4fb8c3b7f788426abfa7b3fa0`
- 직전 원격 변경 `49e03a5a`를 보존한 후 같은 브랜치에 반영했다. 새 branch/worktree, 과거 SHA reset, issue 변경은 하지 않았다.
- 상태: Prompt source/manifest 수정 완료. 실제 Local 모델·production Graph 업무 품질은 미검증.

## 수정 범위

현재 RU/Retrieval/Planning의 State, Prompt input contract, Query/결과 schema, 관련 실제 caller와 Review 입력을 대조했다. 문구는 승인된 변경 후 동작까지 반영했다. 기존 전체 23개 슬롯 중 다음 12개만 수정했고, 나머지는 유지했다.

| Prompt | 버전 | 반영 내용 |
| --- | --- | --- |
| request_understanding.identify_goal | 1.0.54 | 일반 설명/자료 조회/외부 변경 구분, 수정 위치·literal·금지의 후단 전달, source/output 책임 정리 |
| request_understanding.detect_ambiguity | 1.0.9 | 최초 정보 소유권의 영구 고정 제거, 대상 선택과 사실 조회 구분, READ 일괄 질문 금지 제거 |
| tool_routing.determine_io_resources | 1.0.5 | 필요한 I/O만 선택, NO_TOOL_NEEDED와 빈 input/output 일관성, 실제 선택 필요 판단 |
| retrieval.plan_query | 1.0.25 | 확장 강제/비강제 모순 정리, 조회 관측 기반 가설, 승인된 의도적 제한 목록 탐색 반영 |
| retrieval.select_evidence | 1.2.9 | 모든 제공 segment의 실제 관련성, 목록을 대표 한 항목으로 축소하지 않기, identity와 의미 근거 구분 |
| retrieval.assess_sufficiency | 1.0.6 | 미발견/미확정/실패/미실행 구분, 페이지 관측과 조회 필요성 분리, 현재 사용자 선택 재판단 |
| planning.outline_answer | 1.0.6 | 초기 false를 영구 질문 금지로 해석하지 않기, 일반 설명과 목록 범위 보존 |
| planning.compose_answer | 1.0.13 | 실제 상태에 근거한 설명, 일괄 재요청 강제 제거, 내부 ID·허위 완료 방지, 목록 보존 |
| planning.draft_action_objective_per_output_route | 1.0.5 | 원문의 변경 내용·위치·보존 범위를 argument writer까지 전달 |
| planning.compose_arguments_per_output_route | 1.0.12 | editable_source 기반 요청 patch, 원본 보존, Reply identity는 binder 책임으로 통일 |
| review.inspect_goal_and_evidence | 1.0.11 | 작성된 값의 누락/오류와 사용자 선택을 구분, BEFORE/AFTER·승인 전 제안 검토 |
| review.recheck_affected_dimensions | 1.0.4 | 영향받은 영역만 재검토, 해결된 finding 제거, 필요한 실제 선택만 질문 |

각 source는 역할/시점, 입력 의미, 해당 판단 책임, 출력 형식으로 정리했다. 새 deterministic 의미 규칙, 프로젝트별 정답, synonym 목록, 새로운 Agent/Node, budget·권한·승인 정책은 추가하지 않았다. 등록된 input/output schema와 구조·identity·실행 안전 경계는 변경하지 않았다.

## 수행한 확인과 하지 않은 확인

- 정적 artifact 확인: 기존 manifest 원문의 Git blob hash 일치, 23개 slot identity 유지, 변경 12개 source의 SHA-256과 새 manifest 일치, UTF-8/개행, 선언된 required input 이름 포함을 검사했다.
- 원격 저장 확인: 12개 source와 manifest의 Git blob SHA를 로컬 작성본과 대조했다. 제품 commit diff는 이 13개 파일만 변경한다.
- 각 변경 슬롯의 prompt_version/content_hash만 갱신했다. input/output schema version, activation_status=DRAFT, 기존 false 검증 flags 및 activation_evidence=null은 유지했다. 실제 수행하지 않은 Dev/Holdout/Safety PASS를 생성하지 않았다.
- 위 확인은 정적 파일 무결성 점검이다. 전체 저장소를 로드한 PromptRegistry/pytest, production Node/compiled Graph, 실제 LLM/Connector/Browser 검증은 수행하지 않았다. 의미 품질 향상이나 업무 성공을 입증하는 결과가 아니다.
- 사용자 PC의 local/upstream HEAD·working tree·실행 프로세스는 이 작업에서 직접 확인하지 않았다. 원격 반영만 확인했다.

## 승인된 코드 작업과 함께 연결할 잔여

| 변경 후 동작 | 현재 코드에서 함께 맞춰야 할 경계 |
| --- | --- |
| 의도적인 조건 없는 Gmail 목록 탐색 | INITIAL constraints minItems, Builder materializability, Gmail projection은 아직 빈 조건을 거절한다. 새 Prompt는 현재 supplied schema가 지원하는 표현만 쓰도록 하며 임의 operation/placeholder를 만들지 않는다. 목록 조회 구현 완료가 아니다. |
| 후단에서 새로 필요한 질문 | outline_answer의 confirmation_allowed schema binding과 runtime validator가 아직 최초 ambiguity flag를 사용한다. Prompt의 영구 금지 문구 제거와 별도로 승인된 caller/validator 교정이 필요하다. |
| 정상 미발견의 Answer Agent 설명 | project_empty_read_answer의 결정적 조기 반환이 해당 Prompt를 생략할 수 있다. 실제 관측의 bounded 전달과 Answer 호출 경계를 함께 맞춰야 한다. |
| 페이지·다건 목록 보존 | 현재 입력에 없는 page coverage나 선별 전에 사라진 Resource를 Prompt가 복구할 수 없다. 이미 승인된 관측/목록 전달 교정과 함께 검증한다. |
| 상태·cache 결속 | stale FINALIZE와 원래 Query Plan binding은 코드 책임이며 이번 Prompt 변경으로 해결됐다고 계산하지 않는다. |

코드 변경 후에는 현재 supplied schema·validator·caller가 새 문구와 일치하는지 직접 검사하고 기존 관련 사례로 실제 LangGraph 결과를 확인해야 한다. 새 semantic rule은 사용자 승인 없이 추가하지 않는다. 이번 기록은 추가 실험 횟수·새 Gate를 정하지 않는다.

평가 기준은 READ의 정확한 답변/미발견/미확정 설명, WRITE의 정확한 target/content Preview + WAITING_APPROVAL이다. 승인 대기 성공은 Provider WRITE나 독립 Verification 완료와 구분한다.
