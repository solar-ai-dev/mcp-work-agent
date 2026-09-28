# 074 — 실제 자연어 해석에서 기존 Source owner로의 전달

## 가설과 기존 실패와의 차이

072는 짧은 원문·선택 identity·시각 입력에서049의 기한/시작 관계를 복구했다.
그 실제 최종 표시문을 현재 Source owner가 참고해도 보존하는지 검증한다.
v7의 구조화된 needs→원문 없는 binding, v43 membership 분리 실험을 반복하지 않는다.
원문/Goal/Work/catalog/Schema를 제거하지 않고 optional 비권위 해석만 추가한다.
새 Source 정답·Gold·사람이 수정한 해석이나 숨겨진 추론은 입력하지 않는다.

## 실행 전 고정

- Core017→049→005, 각 FIRST1, 신규3호출, 직렬1, timeout180초, retry/repair0.
- 072 raw bytes SHA256 `af183697e4a0e1b5aa68a5ca5d270dc2f115d7704cd02581cbcd38128a6f7186`.
  frozen final response를 exact하게 재사용하며 해석 호출은 새로 실행하지 않는다.
- 과거v42 Source의 실제 wire를 현재 Product assembler/Registry/Schema/validator로
  재구성해 동일성을 먼저 검사한다. historical SHA와 current SHA는 구분한다.
- Source wire의 model/think=false/options/format/출력 Schema는 그대로다.
  system 입력과 prompt.input 두 복사본에 interpretation_candidate만 추가하고
  비권위 optional 입력 선언 및 evaluation PromptRef/hash를 별도로 결속한다.
- current HEAD·code·Prompt·원문·선택·시각·Dataset/Fixture·모델·실제 sampling을 잠근다.
- generation 중 코드 편집/pytest/다른 모델0. timeout·미완료/transport/model drift 시
  남은 미실행을 표시하고 원 실패를 보존한다. 의미 실패는 다음 고정 Case로 진행한다.
- Provider/Graph/승인/WRITE0. Product source/Prompt/State/Schema 변경0.

## 판정 범위

1. 072 자연어 의미(기존 판정 유지), 2. Source FIRST 원시 출력, 3. strict Schema/owner
검증, 4. 실제 merge의 Source projection을 분리한다. merge의 Output은 빈 값으로 둔
격리 진단이므로 전체 RU 조립·Tool Route·실제 조회·업무 성공으로 주장하지 않는다.

- 005: 선택된 동일 Task 상태·기한, 생성 금지. 임의 목록 검색·미완료 필터로 좁히지 않음.
- 017: 현재 Tasks와8/12Calendar 조회. Task date-only를 특정 시간/날짜에 제한하거나
  미확정 검토시간·충돌을 발명하지 않음. Draft는 결과이며 기존 Draft 조회를 요구하지 않음.
- 049: 기존 Atlas Mail/Task/Calendar 근거와 새 Task기한·Event시간·Draft 결과를 구분.
  새로 만들 값을 기존 자료에 존재해야 할 필수 사실로 변환하지 않음.

Resource 이름만 맞으면 PASS하지 않는다. 다양한 유효 조회 표현은 허용하며 의미를
보존한 scope/required_information/Work binding을 확인한다. 구조적 통과와 의미 통과를
구분한다. SOURCE_SCOPE_DROPPED / OUTPUT_AS_SOURCE / UNSUPPORTED_FACT /
WORK_BINDING_LOSS / CONTRACT_FAILURE 및 기존005 회귀를 별도로 기록한다.

비용은 신규 Source와 frozen072 해석+Source 총비용을 모두 기록한다. 재사용한 호출을
공짜로 계산하지 않는다. 단발3건 통과만으로 Product adoption/92개 성공을 선언하지 않는다.
정확한 해석도 typed boundary에서 손실되면 후속 Prompt 문구를 추가하기 전에 그 입력·
표현·ownership을 다시 분석한다. 효과/비용이 불리하면 후보를 비활성으로 보존하고 다음
원인 축을 선택한다. 동일 실패를 성공할 때까지 재실행하지 않는다.
