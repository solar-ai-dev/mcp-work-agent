# 077 — 파생 조건 제거는 대상 범위 오류를 해결하지 못함

**REJECT / Product 전역 조건 삭제 안 함.** 같은 부분 Source 4건은
**3 PASS / 0 PARTIAL / 1 FAIL → 3 PASS / 0 PARTIAL / 1 FAIL**이다.
Core 2/3와 합성 1/1을 전체 Case/Source/업무 성공률로 승계하지 않는다.

| 대상 | 결과 | 실제 변화 |
| --- | --- | --- |
| 017 TASK | PASS 유지 | 현재 작업 목록의 CRITERIA와 필요한 상태·기한 유지 |
| 049 TASK | FAIL 유지 | 신규 Task의 '현재 제목/내용' 혼동은 일반적인 title/notes/due로 줄었으나 **SINGULAR**로 근거 없이 좁힘 |
| 005 TASK | PASS 유지 | 선택된 단일 대상, 상태·기한 보존 |
| 합성 Draft UPDATE | PASS 유지 | 본문·수신자 조회와 SINGULAR 보존. 이미 constraints={}인 exact no-op control |

049의 원문은 Atlas 관련 자료를 확인한 뒤 새 Task를 만드는 요청이다. 특정 기존 Task
하나를 선택/지목하지 않았는데 SINGULAR를 생성했다. 이는 Task 정답 개수를 강제한
판정이 아니다. CRITERIA 조회의 실제 결과가 하나인 것은 정상이다. 또한077에서 여전히
새 Task를 조회한다고 확정하면 안 된다. 확정된 잔여 실패는 **대상 범위 축소**다.

FIRST4/4는 strict VALIDATED이고 원 출력과 검증값이 같다. 입력의 constraints만 비웠고
원문·Goal문장·Work/Relation·selected·clock·catalog·focus·Schema·sampling은 유지했다.
이 결과는 조건 묶음의 영향을 보는 작은 비교이지 특정 search_terms/period의 단독 원인
증명이 아니다. Goal이 신규 제목·시각을 가진 것 자체를 잘못이라고 판정하지 않는다.
그 값이 Source의 기존 대상 조건으로 소비될 위험을 분리하려 했으며, 삭제만으로는
안정화되지 않았다. 과거003의 기각도 유지하고 이 제거 방법을 다시 후순위로 돌린다.

## 조건과 비용

- 실행 SHA `72d3c98f27b3f90fc47e5c8bb51432da8c3a9fe6`, 고정 FIRST4회,
  retry/repair/rerun-to-pass0, 시작·종료 binding 동일. 별도 해석 추가 없음.
- qwen3.5:9b/기존digest/Ollama0.34.0/temp0.05/seed20260923/ctx16384/think=false.
  실제 wire에서 Goal.constraints 외 옵션 변경0.
- 076의 같은4건: input14,650/output238,24,655ms. 신규: input13,598/output193,
  **13,827ms**(Core11,786ms/합성2,041ms),wall13,936/load32ms,usage누락0.
  역사 cold load와 cache 차이가 있으므로 일반 속도 효과로 해석하지 않는다.
- 직접 harness/recorder **92 tests PASS**(Canonical92 평가가 아님),scoped Ruff/mypy PASS.
  모델은 직렬1, 생성 중 편집/pytest0. 종료GPU6385MiB/0%/47°C(snapshot).

Product source/활성Prompt/State/Graph 변경0, Provider/Approval/WRITE0,
새 Canonical92/전체pytest 실행0. 전체 LangGraph 안정화는 미완료다.
단일Resource판정의 일부 개선은076근거로 보존하되 대상·조건·호출 비용이 닫히기 전에는
Production에 반영하지 않는다. 전체 Source 조합·실제 upstream·Query/Retrieval/Planning,
CREATE Source0 회귀와 반복 안정성은 이번4개로 검증하지 않았다.

## 재현

- plan `evaluation/results/077-source-goal-constraint-plan/preregistered-plan.json`, object hash
  `67ac0dc34c9ac955f77e4aa72d36a560d64cade9cde9785806461e39c3db22cd`.
- raw `evaluation/results/077-source-goal-constraint-t1/raw.json`, bytes hash
  `20a9555b774496ac716d6ff94b532c3a211e89da4ee782aedd9986529634eeb6`.
- source-admission.json 및 plan에 각focus/current-source/schema/model/Dataset/Fixture
  결속. 상세 raw는로컬ignore영역, 이문서는원격리뷰용비민감결론이다.
