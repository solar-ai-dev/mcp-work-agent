# 094 — 수정된 Task 범위 위임의 실제 Product Planning 연결

093 Product 코드 수정 뒤 **현재 Product Prompt·Schema·sampling을 그대로** 사용하는
고정2개 compiled component 진단이다. 088 FACT/PROSE 후보, 091 alias 제거,
092 temperature 변경은 모두 중첩하지 않는다. Production 활성화 실험도 아니다.

## 가설·고정 범위

093의 결정적 scope 교차 적용은 직접검사로 수정했다. 위임받은 실제9B가 원문과
Source/item/Work/Evidence binding을 소비하여 업무별 사실을 구분하는지는 아직 미검증이다.
정상 full 조회와 한 Task만 관측한 partial 조회를 각각1회 실행한다.

- 요청: `작업 A의 상태만 알려주고, 작업 B는 예정일만 알려줘.`
- 동일 Work1에 status/due Source2개. 하나의 decomposition 모양을 Gold로 강제하지 않는다.
- `PRODUCT_TASK_FIELD_FULL-T1`: A needsAction/2026-10-01, B completed/2026-10-02.
- `PRODUCT_TASK_FIELD_PARTIAL-T1`: A만 관측, B snapshot/Evidence 없음. PARTIAL 상태 전달.
- 위 날짜·ID·본문은 격리된 합성 component 자료다. Canonical92/Provider 원본을 수정하거나
  실제 upstream이 생성한 결과로 표시하지 않는다. 기준시각2026-09-29T09:00+09, fault 없음.
- qwen3.5:9b exact digest·Ollama metadata/ctx16384/think=false/seed20260923을 봉인.
  Product sampling을 유지한다(Planning temperature/presence override 미전송).
- full→partial 고정 순서, 각 FIRST1, 총 actual generation 최대2, 동시호출1, 각180초.
  Product NORMAL budget은 그대로 두고 추가 평가 dispatch cap으로 repair/재시도를
  전송 전에 차단한다. 차단·timeout·실패는 그대로 기록하며 대체 Trial을 만들지 않는다.
- actual registered router, same-Run EvidenceStore, 실제 compiled Planning과 Supervisor
  projection을 사용한다. Main schedule/resume/terminal DB commit·전체업무는 평가하지 않는다.
- FIRST raw·native wire·입력/결과·snapshot 봉인·calls/tokens/latency·Provider 거절 시도를 보존.
  raw는 기존 evaluation/results 로컬 정책, 비민감 결론은 이 위치에 별도 기록한다.
- 먼저 fake transport로 두 native FIRST payload의 plan 일치와 handoff만 검증한다.
  fake 응답은 의미 PASS로 계산하지 않는다. 실행 중 Product/Prompt/코드 변경0.

## 의미 판정

full은 A의 미완료 상태와 B의 date-only 예정일2026-10-02를 정확하게 구분해야 한다.
A 예정일이나 B 상태를 해당 요청의 답처럼 불필요하게 추가하면 범위 위반이다.
식별용 A/B 명칭이나 정상적인 표현·목록 형태는 허용한다.

partial은 A의 확인된 상태를 답하고 B 예정일은 확인 불가/조회 미완료로 한정해야 한다.
A의10월1일을 B의 예정일로 바꾸거나 없는 B 사실을 생성하면 FAIL이다.
부분 결과 안내·근거 refs도 보존한다. Goal 요약보다 원문의 명시 범위가 authority다.

구조 VALID/Supervisor 전환과 의미 PASS/PARTIAL/FAIL은 분리한다. 두 번 모두 성공해도
반복 안정성·Canonical92 성적·Main 업무 성공·release로 승계하지 않는다. 실패하면 최초
input→FIRST→validation/materialization→Supervisor 차이로 분류하고 같은 Trial을 재실행하지 않는다.
Provider READ/WRITE/SEND0, 외부 계정0, Product Prompt activation0.
