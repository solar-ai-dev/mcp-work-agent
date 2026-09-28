# 073 — Task 업무 Source의 완료 항목 손실 수정

판단: **deterministic scope 수정 채택**. 071/072의 자유 자연어 설명을 제품 성공으로
승격한 것이 아니다. 실제 compiled Retrieval에서 별도로 재현한 consumer 결함을 수정했다.
기준 HEAD `665b0ce3fc69a688979cb8d0443a0c8ee1301198`; 수정 SHA는 이 문서를 포함한 commit이다.

## 최초 divergence와 수정

현재 Task Source에 상태 제한이 없어도 runtime Query capability는 `CONTAINER_REF`만
지원하고 Connector lowering은 `show_completed=false`, `show_hidden=false`를 보냈다.
그러므로 모델이 올바른 업무 Source를 제공해도 완료 Task를 읽을 수 없었다.
071/072의 '진행 중' 표현이 이 Query를 실제로 만들었다고 주장하지 않는다.

| 경계 | 수정 및 보존 |
| --- | --- |
| typed Source → 수집 범위 | Task Source와 Route의 실제 Work 교집합을 사용. 모든 Source 소비자가 typed INCOMPLETE일 때만 미완료로 좁힘. 제한 없는 소비자가 있으면 ANY |
| Policy-only | 기존 미완료 중복검사 유지. 공유 Route의 Policy reason이 업무 Source를 덮어쓰지 않음 |
| build_query | code-owned STATUS_SCOPE를 effective constraints와 query hash에 함께 결속. Query LLM의 지원 kinds·상태 판단 권한은 늘리지 않음 |
| Connector | ANY는 completed/hidden 포함, deleted 제외. Google 문서상 UI에서 완료한 항목은 두 flag가 필요함 |
| pagination/cache | 동일 범위·hash를 계속 소비. 과거 무status checkpoint의 페이지는 기존 미완료 범위 유지, 전체 범위 cache로 승격하지 않음 |
| CHANGED | code-owned 범위 삭제 거절. 과거 implicit INCOMPLETE를 명시한 것만으로 새 query라고 처리하지 않음 |
| selected detail | exact Resource identity DETAIL_FETCH는 collection 변경 대상 아님 |

공식 Provider flag 의미: [Google Tasks tasks.list](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/list).
이 수정은 완료 전용 결과 필터 기능을 추가하지 않는다. 완료 포함 수집 후 실제 필요한
사실 선택과 업무 충족 여부는 기존 semantic owner의 책임이다. Source/Output/Work 정의,
Prompt, public Schema, Node/Edge, 승인·권한·WRITE·Verification 계약은 바꾸지 않았다.

검토 중 'completed Task는 SATISFIED를 무조건 금지'도 고려했지만 **구현하지 않았다**.
05/06의 미완료 Policy pre-read와 '현재 Task가 요청 업무를 이미 만족하는지'는 다른
책임이다. 기존 계약은 completed의 업무 충족 가능성을 일괄 금지하지 않는다.
후보 삭제나 Validator의 자동 NOT_SATISFIED 생성은 새 의미 정책이므로 배제했다.

## 재현과 회귀

먼저 제품 수정 없이 실제 compiled Retrieval의 일반/정책/공유 3경로를 실행했다.
합성 Connector는 받은 flag에 따라서만 미완료1건·숨김 완료1건을 반환한다.
일반과 공유는 완료 항목이 collection에서 사라져 **2 FAIL**, 정책 전용 **1 PASS**였다.
초기 test fixture의 required_information 불일치는 별도 fixture 오류로 수정했으며
이 오류를 제품 결함의 재현으로 세지 않았다.

수정 후 같은 3경로 모두 통과했다. 실제 READ→cache→정규화→collection→source_status→
authoritative snapshot까지 연결했고 Work union·상태·부모 identity·관측 개수·예산을 확인했다.
각 경로 synthetic Connector READ1, source-page1, detail0, additional round0, 외부 WRITE0.
Fake sufficiency를 사용했으므로 모델 의미 판단이나 최종 업무 성공으로 보고하지 않는다.

최종 직접·인접 회귀 **1004 PASS (5.10초)**:

- Retrieval owner/query contracts/adapter와 Work Analysis unit.
- production subgraphs component(신규 3모드는 같은 파일에 배치; peer-test import 없음).
- Run cache/continuation/restart, Task duplicate kernel/validator.
- approval source snapshot, execution identity/dispatch 안전 검사.
- Retrieval Node/State architecture.

새 scope unit/plan-lowering/component 검증은 총39건이다. 신규 owner의 mirrored unit
test는 `test_project_task_collection_scope.py`다. 변경 Product 5파일 scoped mypy PASS,
변경 파일 Ruff PASS. 모델 호출/실제 Provider READ·WRITE/Approval 클릭은 모두0이다.
페이지 수 증가 가능성은 있으나 기존 page/context/round cap을 확대하거나 우회하지 않았다.

넓혀 실행한 repository architecture gate는 **20 PASS / 3 FAIL**이다. 전체 테스트
통과로 보고하지 않는다. 새 파일 mirror·peer-import·함수명 위반은 고쳤고 남은 항목은
기준 tree에도 있는 Agent mirror/operation naming, 과거 peer-test imports, test naming이다.
이번 관측으로 발견한 071/072 신규 테스트의 이름은 별도 정리한다. Assertion 완화 없음.
기존 3 gate의 대량 정리는 이번 Task 의미 수정에 섞지 않는다.

## 다음 판단

이 결함은 정확한 Typed Source도 downstream에서 좁아질 수 있음을 보여준다.
모든 실패를 9B/Prompt에 귀속하거나, LoRA로 잘못된 결정적 lowering을 학습시키지 않는다.
072의 추론 모드는 짧은 해석에서 개선됐지만 약5.56배 지연과 typed handoff 미검증이 남아
Product에 활성화하지 않는다. 다음 의미 후보는 원문·시간·선택 identity를 보존한
작은 해석의 typed owner handoff를 검증해야 하며, 자연어 요약을 새로운 단독 권위로
만들면 안 된다. Canonical92/전체 RU→Tool Route/최종 업무 점수는 이번에 새로 측정하지 않았다.
