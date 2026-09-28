# 093 — Task 답변의 업무별 정보 범위 보존

기준 HEAD `0949eeae`. 092 모델 후보와 별개인 확정 Product consumer 결함이다.
Prompt 문구·sampling 실험을 반복하지 않고 현재 typed binding의 결정적 손실을 수정한다.

## 원인과 수정

정상 V3에서 Work1은 첫 Task의 상태, Work2는 다른 Task의 예정일을 요구한다.
Source item마다 `work_unit_ids`가 있고 원문도 보존되지만, 기존
`project_task_read_answer._requested_task_fields`가 모든 Source의 조회 필드를 합쳐
두 Task 모두에 상태와 예정일을 출력했다. 최초 손실은 모델이 아니라 이 공통 formatter다.
Evidence가 업무별로 분리된 경우와 공유 READ로 ref union인 경우 모두 재현했다.
독립 검토에서 같은 두 요구를 Work1 하나로 묶어도 동일 손실이 남는 것을 확인했다.
하나의 decomposition 모양을 강제하지 않으므로 이 같은 owner의 반례도 함께 수정한다.

두 Task가 관측될 때만 거절하는 중간 구현에는, A만 관측되면 A의 기한을 B 요청의
응답처럼 추가하는 반례가 남았다. **관측 개수는 요청 대상 동일성의 authority가 아니다.**
이를 별도 lexical rule로 고치지 않고, nonempty Task 답변의 Source별 렌더링 필드 범위가
동등할 때만 공통 formatter를 사용하는 하나의 eligibility 경계로 단순화했다. 이질적 범위는
원문·전체 RequestIntent/item binding·기존 `evidence_by_work_unit`을 변경하지 않고
기존 `planning.compose_answer`에 전달한다. 공유 READ ref union으로 Resource의 업무
귀속을 새로 추정하지 않는다. 조회 Source의 필드를 최종 답변의 허가 목록으로 새로
정의하지도 않는다.

- 기존 status/completion_status/task_status 및 due/scheduled_date의 동등성 유지.
- 단일 Source의 복수 필드, 동등 필드의 복수 Source/업무/Task는 결정적 경로 유지.
- Source2개의 필드가 다르면 같은 Work·한 관측 Task라도 위임한다. Source가 같은 대상을
  요구한다는 결속이 이 formatter 입력에는 없으므로, 이를 추측해0회 경로를 유지하지 않는다.
- 정상 COMPLETE + EXHAUSTED + 0건은 이질적 필드여도 기존 빈 결과 안내 유지.
- 미지원 정보, 불완전 조회, legacy 입력의 기존 위임/거절 계약 유지.
- Schema/State/Node/Prompt/활성화 및 Approval/Execution/Verification 의미 변경0.

이번 반례는 WorkAnalysis/미해결 confirmation이 없어 기존 잘못된 자동 렌더링0회에서
기존 compose 호출1회로 돌아간다. 일반적으로 WorkAnalysis/confirmation이 있으면 기존
outline의 조건부 호출도 가능하므로 항상1회라고 일반화하지 않는다. 새 LLM stage나
Work별 호출을 추가하지 않는다. 의미 판정이 필요한 입력을 공통 formatter가
대신 완료하는 것을 막은 수정이지, 위임받은 모델의 답변 정확도를 입증한 결과는 아니다.

## 직접 검증

- 수정 전 valid V3 반례: 2 FAIL / 36 PASS. 상태/예정일 cross-product를 실제로 관측.
- 같은 Work의 두 Task 반례를 추가한 단계에서도 수정 전 1 FAIL / 46 PASS를 확인했다.
  중간 구현 후 직접47 PASS, 인접124 PASS였지만, 한 Task만 관측되는 반례는 남았다.
  중간121/325/124 검사 등은 최종 검사와 중복이므로 합산하지 않는다.
- 부분조회 반례는 변경 전2 FAIL / 47 PASS(원본 Evidence와 같은 Resource 중복 ref),
  최종 Source-field eligibility 수정 후 인접126 PASS로 닫았다. 관측 cardinality로 target을
  단정하던 중간 가정은 기각했고, 같은 Work의 이질 Source 분할은 위임 control로 옮겼다.
- 최종 root broader regression: RU/Tool Route/Retrieval/Analysis/Planning/Review unit,
  LangGraph adapter와 compiled component를 합쳐 **2,187 PASS / 0 FAIL**(8.72초).
- 별도 Approval/Claim/Execution/Verification/Recovery Domain·use-case **156 PASS**(2.03초).
- compiled Planning 신규5개: 서로 다른 Work/같은 Work/부분 조회의 이질 Source는 각각 compose1회,
  동등 필드/정상 빈 조회는 각각0회. Goal과 다른 원문, full valid V3와 공유 READ Evidence
  union이 실제 compose 입력까지 변형 없이 전달됐다. 가짜 응답의 의미 품질은 채점하지 않았다.
- 원문·Intent·Evidence·snapshot 불변, 원문과 Work별 binding의 실제 작성 input 전달 확인.
- scoped Ruff/mypy PASS. 전체 mypy나 전체 평가 PASS라는 뜻이 아니다.
- 구조 검사 **24 PASS / 2 FAIL**. 실패는 기존 `evaluation/` Python inventory 및
  Product internals import25건이다. 시작 `c3f31728` 이후 관련 평가 Python/test 파일의
  diff가 없고 이번 Product diff에 evaluation import 추가도 없다. 이 기존 구조 부채는
  assertion을 완화하거나 전체 gate PASS로 감추지 않는다. 이번 formatter 수정의 회귀는
  아니지만 repository-wide clean gate는 아직 통과하지 않았다.

root 검증 명령:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/application/agents tests/unit/adapters/langgraph tests/component/langgraph -q
.venv/Scripts/python.exe -m pytest tests/unit/domain/approval tests/unit/domain/claim tests/unit/domain/execution_attempt tests/unit/domain/verification tests/unit/domain/recovery tests/unit/application/use_cases/approval tests/unit/application/use_cases/claim tests/unit/application/use_cases/execution_attempt tests/unit/application/use_cases/verification tests/unit/application/use_cases/recovery -q
.venv/Scripts/python.exe -m pytest tests/architecture/test_planning_review_owner_local_structure.py tests/architecture/test_prompt_activation_boundary.py tests/architecture/test_evaluation_boundary.py tests/architecture/test_tool_registry_single_authority.py tests/architecture/test_workflow_handoff_authority.py -q
```

## 판정과 한계

이 owner-local 코드 수정은 **ADOPT**한다. typed 의미를 바꾸지 않고 자동 formatter의
부적합 적용만 막았다. 컴파일된 Planning 연결과 인접 회귀까지 확인했지만 위임 경로의
새로운 모델 성공률·토큰·실제 추론 지연은 아직 측정하지 않았다.

Calendar 인접 formatter도 확인했으나 단일 exact Event/snapshot restriction이 있어
같은 다중 대상 교차 적용 결함으로 단정하지 않았다. 정상 Calendar 경로는 바꾸지 않는다.
Source 수집 범위를 답변 범위로 오인하는088 모델 후보의 오류와 이번 코드 결함은 별도다.
092까지의 기각 raw/판정은 보존하며 실패 Trial을 교체하지 않는다.

실제 모델/Provider READ/WRITE/SEND0, Canonical92·Main·Live Provider·release 미실행.
Dataset/Gold 변경0. 직접 검증은 fake semantic invoker를 사용하며 최종 업무 성공률이 아니다.
