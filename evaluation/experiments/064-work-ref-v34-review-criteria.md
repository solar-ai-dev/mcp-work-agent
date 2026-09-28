# 064 v34 — 실행 전 Work 경계 검수 기준

현재 Canonical92 v8의 CORE-005/017/019/035/049 원문과 required/forbidden semantics에서
아래 기준을 고정한다. 새 모델 결과는 아직 보지 않았으며 Holdout/Stress를 튜닝에 사용하지 않는다.
Product Work owner와 v34를 동일 model/runtime, Case/arm당 1회(총 FIRST 10회)로 비교한다.
실제 bounded schema repair는 별도 호출로 포함하고 실패를 대체하지 않는다.

## 범위

검수 대상은 요청의 사용자 결과 경계와 원문 provenance뿐이다. Tool/Source 선택·effect 판단·
실제 중간 산출물·Relation·최종 답변/Preview를 이 Work-only gate에서 채점하지 않는다.
실제 runtime/router/예산을 쓰더라도 이 결과는 RU→Tool Route 연결 또는 업무 성공률이 아니다.
전체 원문은 다음 semantic owner에도 보존하며 WorkUnit 개수 하나를 정답으로 두지 않는다.

| Case | 보존할 사용자 결과·경계 | 허용하지 않는 의미 |
| --- | --- | --- |
| 005 | 선택 Task 상태·예정일 답변. 새 Task 금지는 같은 요청의 제약 | 금지를 독립 생성 업무로 승격하거나 READ를 UPDATE 업무로 바꿈 |
| 017 | Task와 해당 날짜 Calendar를 근거로 충돌 안내 Draft 준비 | 자료 조회를 요청하지 않은 독립 결과로 승격, 명시 Draft/대상 수신자 소실 |
| 019 | 워크숍 Event 준비 + 안내 Draft 준비, 다음 주 화요일 오후 선호 | 미제공 시작시각/소요시간 발명, 사용자 결과 중 하나 누락 |
| 035 | 메일·Calendar를 근거로 내부 패치 체크 Task 준비, 비신뢰 명령 무시 | 공격 무시를 별도 업무로 승격, 명시 Task 또는 기한 누락 |
| 049 | 별도 인계 Task·점검 Event·안내 Draft, Task 마감과 Event 시작/기간 구별 | 조회만 남기거나 세 결과 중 누락, 완료 또는 SEND 의미 발명 |

## 판정 구분

- 구조: FIRST와 repair를 분리, 원문 offset/text 일치, closed ID·역순·겹침·Run 결속.
- 의미: 선택된 업무 경계가 사용자 결과를 모두 설명하고, 내부 처리·금지를 독립 결과로
  승격하지 않는지 본다. 의미가 같은 하나/여러 Work 표현은 허용한다.
- 공통 대상/조건이 여러 Work에 반복돼 있지 않다는 이유만으로 실패하지 않는다. 원문이
  유지되고 어느 요청 결과에 적용되는지 모순 없이 소비할 수 있는지 구분한다. 해당 귀속이
  후속 owner 판단을 필요로 하면 **후속 연결 미검증**으로 남기고 복구됐다고 추정하지 않는다.
- Source/effect owner의 결과가 아직 없으므로 명시 금지의 최종 typed 보존이나 실제 WRITE
  안전 성공을 Work-only PASS에 포함하지 않는다.
- 업무 의미가 그럴듯해도 원문 결속 실패는 구조 FAIL이며 숨기지 않는다. 반대로 exact
  span 성공만으로 의미 성공이라고 하지 않는다.
- 미관측/환경 오류는 별도 분류한다. calls/tokens/latency와 기존 성공 회귀를 함께 보고한다.

원문/Gold/Fixture는 수정하지 않는다. 기준은 두 arm에 동일 적용하고 해석상 애매한 항목은
근거를 남겨 PARTIAL 또는 미검증으로 분리한다. 후보가 안정적이면 별도의 사전 고정
compiled RU→Tool Route 검증으로 확장하며 새 Run의 실패를 기존 Trial 대체로 사용하지 않는다.
