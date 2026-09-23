# 060 — Request Understanding owner 경계 재분류

Issues: #287 / #288

## 결론

059의 구조 성공(`compiled RU → Tool Route` 도달)과 업무 의미 성공을 분리했다.
`RequestIntentV3`의 `work_unit_ids`와 Route projection은 유지됐지만, 의미는 그보다 앞선
atomic owner에서 처음 달라졌다. 확인된 결정적 consumer 결함 3개는 owner-local하게
수정했다.

1. `CREATE` Output과 Resource가 같다는 이유로 이미 선택된 Source READ를 삭제하지 않는다.
2. effect prohibition은 전역 effect 집합이 아니라 Output item과 겹치는
   `work_unit_ids` 범위에서 검증한다.
3. Source 중복은 Resource type만 같다고 거절하지 않고, owner item의
   `(resource, information, scope, work units)`가 모두 같은 경우만 거절한다.

이 수정은 잘못된 Source/Output 판단을 숨기지 않고 그대로 드러내며 V3 binding을
보존한다. 그러나 두 번의 고정 Trial에서도 atomic Source/Output owner의 의미 오판은
남았다. 따라서 추가 Prompt patch를 쌓는 대신 ownership/physical inference 경계를
바꾸는 구조 후보를 먼저 검토해야 한다.

## 실행 결속

- Start Product SHA: `6ed73a6500a39df9bd9a56f8dc8a712aee2377ae`
- Dataset: Canonical v8 Core, 기존 059 9건 + CORE-005 control
- Dataset / fixture / Prompt manifest / model digest / temperature / seed는 각 로컬
  `result.json`의 `binding`에 보존
- Model: `qwen3.5:9b`, temperature `0.0`, seed `20260923`
- 각 결과 경로는 새 파일로 생성했고 기존 Trial을 덮어쓰지 않음
- Provider READ/WRITE/SEND: `0/0/0`
- 범위: compiled RU → Tool Route. Retrieval/Planning/Provider 연결은 실행하지 않음

## 059 Case와 atomic owner 재분류

atomic 기록에는 각 owner의 실제 input, `FIRST` output, revision output이 순서대로 남고,
owner output과 final `request_intent`를 비교해 merge 전후를 확인한다.

| Case | 최초 의미 차이 | Goal 입력 오염 | owner/merge 결과 |
| --- | --- | --- | --- |
| CORE-001 | 없음 | 없음 | 선택 Gmail READ, Output 없음 |
| CORE-005 | prohibition owner, 이어서 Output owner | 없음. Goal은 상태·기한 조회와 새 작업 금지를 보존 | CREATE 금지를 놓치고 Task UPDATE/Gmail SEND를 추가 |
| CORE-009 | Output owner | 없음. Goal은 메일+작업 현황 파악 | READ-only를 Gmail SEND+Task CREATE로 변경 |
| CORE-012 | Output owner | 없음. Goal은 Draft 작성 | Draft CREATE에 SEND 추가. Source owner는 기존 Draft READ도 잘못 추가했고 과거 merge가 이를 숨김 |
| CORE-019 | Source owner, 이어서 merge | 없음으로 판정 | Gmail READ 누락. Event/Freebusy READ 중 CREATE merge가 Event READ 삭제. 관련 READ 후 확인은 Canonical상 허용되므로 ambiguity 실패 판정 취소 |
| CORE-035 | Output owner | 없음. Goal은 Task 생성만 보존 | Task CREATE에 Event CREATE 추가 |
| CORE-037 | Source owner, 이어서 Output owner | 없음. Goal은 기존 Task 기한 UPDATE | 최초 Source 0건, Output에 GitHub UPDATE 추가; revision 뒤에도 안정적으로 닫히지 않음 |
| CORE-049 | Source owner, 이어서 merge | Goal은 Task/Event/Draft 결과를 보존 | 필요한 Gmail/Task Source 누락, 근거 없는 Event Source만 선택; 과거 merge가 그 Event Source도 삭제 |
| CORE-056 | prohibition owner | 없음. Goal은 비실행 지시를 보존 | SEND만 금지하고 CREATE/UPDATE/DELETE의 업무 의미를 보존하지 못함. 우연히 Output 0은 의미 보존의 충분조건이 아님 |
| CORE-059 | Goal owner, 이어서 Output owner | 있음. `바로 답장 보내줘`를 `답장 메시지 작성`으로 축약 | SEND와 Draft CREATE를 함께 선택. Trial 간 SEND-only/extra Draft로 변동 |

CORE-019는 `소요시간 미확정 → 즉시 Confirmation`만 정답으로 강제하지 않는다.
Canonical은 Fjord 메일과 Calendar를 먼저 읽은 뒤 필요한 확인을 허용한다. 이번 범위에서는
Gmail READ조차 Route에 없었으므로 `Source 의미 실패`까지만 확정하며, 최종 Confirmation
성공/실패는 미검증이다.

## consumer 경계 수정 후 반복

동일 Product patch와 고정 sampling으로 각 Case를 두 번 실행했다. 이는 기존 실패를
PASS로 바꾸기 위한 재실행이 아니라 owner 안정성 비교용 사전 고정 반복이다.

- CREATE와 같은 Resource의 Source가 final intent에 유지됨: 두 Trial 모두 확인
- 서로 다른 Source owner item을 Resource type만으로 거절하지 않음: 직접 contract test
- WorkUnit별 금지가 다른 WorkUnit Output을 전역 삭제하지 않음: 직접 contract test
- exact Output pair 일치: Trial 1 `8/10`, Trial 2 `6/10`
- 안정적으로 남은 오판: CORE-035 extra Event, CORE-019 missing Gmail,
  CORE-049 missing Gmail/Task, CORE-037 Source/Output 오류
- 변동 오판: CORE-009와 CORE-059 Output

따라서 deterministic consumer 결함 수정은 **ADOPT**, 현재 Output semantic owner는
**안정화되지 않음**이다.

## Goal 오염과 Output owner 오류 분리

Goal이 요청 효과를 깨끗하게 보존한 CORE-005/009/012/035/037에서도 Output owner가
READ를 WRITE로 바꾸거나 다른 WRITE를 추가했다. CORE-059에는 Goal 오염도 있었지만,
전체 Output 실패를 Goal 입력 하나로 설명할 수 없다.

추가 Prompt patch 대신 세 개의 bounded evaluation-only 반례를 비교했다.

| 후보 | baseline exact Output | 후보 exact Output | 추가 호출 / 지연 | 판정과 이유 |
| --- | ---: | ---: | ---: | --- |
| 선택된 Output 재검증 | 14/20 | 16/20 | 13 / 51,677ms | REJECT. CORE-035에서 두 번 모두 정답 Task를 버리고 오답 Event를 유지했고 CORE-037/009도 Trial별로 잘못된 항목을 유지 |
| Resource semantic metadata 보강 | 14/20 | 12/20 | 20 / 62,439ms | REJECT. CORE-012에 SEND를 추가했고 안정 실패를 줄이지 못함 |
| closed capability ID Schema | 14/20 | 6/20 | 20 / 69,353ms | REJECT. CORE-001에서 11개 WRITE capability를 모두 선택하는 등 과선택 악화 |

`selected verification`의 숫자만 보면 2건 개선이지만, 같은 의미에서 정답 대신 오답을
선택하는 반례가 반복되어 채택하지 않는다. 기존 043/044의 Prompt contrast, concise,
Goal projection 제거, exact disposition, Resource 분리, change span, WorkUnit별 Prompt
실패와 합치면 현재 physical owner에 Prompt/Schema를 더 쌓을 근거가 없다.

## 구조 변경 판단

### 현재 구조에서 반복 해결되지 않는 이유

Goal owner가 이미 보존한 사용자 결과를 Output owner가 동일 원문과 Goal을 다시
해석하면서 Resource/effect 후보로 재생성한다. 이 두 번째 생성이 독립 semantic authority로
작동하고, validator는 schema/Registry 호환성만 확인하므로 의미상 추가·변경을 거절할
근거가 없다. downstream Tool Route는 잘못된 intent를 충실하게 투영할 뿐이다.

### 최초 실패 경계

- 대부분: `identify_output_responsibilities` 첫 structured output
- Source 계열: `identify_source_dependencies` 첫 structured output
- 일부 금지: `identify_effect_prohibitions` 첫 structured output
- CORE-059만 Goal 첫 출력부터 SEND/작성 의미가 약화

### 유지할 성공

- `RequestIntentV3` item-owned `work_unit_ids`
- shared READ Route의 capability 공유와 WorkUnit union
- 독립 Output Route identity
- Relation owner의 closed endpoints와 typed kind
- Approval/Policy/Planning Action dependency/Execution/Verification/Recovery 경계

### 다음 구조 후보

Goal과 사용자 요청 결과 의미를 별도 LLM들이 중복 판정하지 않도록, 하나의 atomic
inference에서 Goal과 Output responsibility를 함께 산출하되 논리적 필드 owner와 기존
validator는 유지하는 후보가 가장 작다. Source와 prohibition은 별도 owner로 유지한다.
이 후보는 새 heuristic이나 Case 규칙이 아니라 `Goal → Output` 재해석 handoff를
제거하는 physical Node/ownership 변경이다.

검증 전 Production 적용은 하지 않는다. evaluation-only prototype에서 먼저 다음을
확인해야 한다.

- READ-only/Task/Draft/Event/Send 성공·실패·반례의 exact semantic preservation
- 동일 WorkUnit binding과 Route identity
- 기존 Goal 의미 회귀
- LLM 1회 제거에 따른 calls/tokens/latency
- persisted V3 checkpoint revision/resume 영향

장점은 동일 의미의 이중 생성 제거와 호출 감소다. 단점은 한 inference schema가 커지고
Goal과 Output revision을 독립 재시도하기 어려워진다는 점이다. 이 구조가 실패하면 Prompt
추가가 아니라 Output owner model tier/runtime policy 비교가 다음 선택이다.

## 통과 범위 구분

- **구조 통과:** V3 binding과 Tool Route projection, 이번 deterministic consumer contract
  직접 테스트
- **의미 통과:** 일부 control만 통과. Source/Output/prohibition owner는 수평 안정화 실패
- **실제 연결 성공:** 미검증. Retrieval → Planning과 Provider는 실행하지 않음

## 로컬 결과

- atomic baseline: `evaluation/results/ru288-owner-atomic-baseline-20260924/`
- CORE-005 baseline: `evaluation/results/ru288-owner-atomic-core005-baseline-20260924/`
- boundary fix Trial 1/2: `evaluation/results/ru288-owner-atomic-boundary-fix-20260924/`,
  `evaluation/results/ru288-owner-atomic-boundary-fix-repeat2-20260924/`
- Output 후보 3종: `evaluation/results/ru288-output-selected-verification-v1-20260924-r2/`,
  `evaluation/results/ru288-output-resource-semantics-v1-20260924/`,
  `evaluation/results/ru288-output-capability-selection-v1-20260924/`

상세 raw 결과는 저장소 ignore 정책에 따라 로컬에만 보존한다. 원격에서는 이 보고서와
evaluation runner/candidate source로 판단할 수 있다.
