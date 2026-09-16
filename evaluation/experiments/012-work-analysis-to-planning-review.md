# 012. 실제 Work Analysis → Planning → Review 인접 연결

기준 SHA `9440635a` + 011의 Gmail detail guard patch. 011에서 현재
RU→Route→Retrieval의 021/023/028 모두 `gmail_get_thread` 1회로 본문을
확보하고 Work Analysis에 도달했다. 세 사례의 `analysis_requirement`은
`NONE`이고 Calendar conflict policy 때문에 effective Work Analysis가
실행된다. 따라서 entity/temporal relation 호출 생략과 relation 0개는
06의 policy-only 경로에 맞으며, 그 수만으로 의미 실패라고 하지 않는다.

021은 원문 날짜 8/14 10시·60분, Atlas 메일의 8/18 우선안과 8/19 오전
확정, QR/라벨 Task의 진행 상태가 구별되어 Planning 입력으로 사용할 수 있는
첫 실제 출력이다. 단일 Trial에서 이 in-memory WorkAnalysisResult와 원래
EvidenceStore를 Planning, 이어서 Review에 넘긴다. `SOLUTION_PLANNING`이
아니거나 중간에서 확인/재조회/수정을 요구하면 그 disposition을 기록하고
강제로 PASS·WRITE로 진행하지 않는다. Planning action draft와 Review의
결정, 첫 structured inference/repair·호출/토큰/지연을 분리한다. 실제
Provider WRITE와 Domain Validation, 최종 사용자 응답은 실행하지 않는다.

이 연결이 성립하면 023/028 등 다른 적용 요청으로 확장한다. 첫 연결이
실패하면 input/contract/harness와 모델 판단을 분리해 고치기 전에는
확장하지 않는다. 저장 checkpoint의 과거 WorkAnalysisResult나 Gold Plan을
끼워 넣지 않는다. 상세 artifact는 ignored results에만 남긴다.

## 결과

첫 Trial에서 Retrieval 6 READ(메일 상세 1회) → Work Analysis COMPLETE →
Planning action 1개·`PLAN_REVIEW_INSPECT` handoff가 성립했다. Evaluation harness가
Review target을 `PLAN_REVIEW`로 잘못 검사해 Review는 **실행되지 않았다**.
이는 제품 Review 실패가 아니라 평가기 오류다. 첫 Trial의 Planning은
8월 14일 10:00–11:00 Event를 제안했지만 메일의 To 주소 두 개를 참석자로
넣었다. 사용자는 ‘내부 점검 일정’을 요청했지 메일 수신자 초대를 요청하지
않았으므로 이 초안은 의미·범위 검토가 필요하다. 모델 출력이 만들어졌다는
이유로 성공으로 세지 않는다. Work Analysis의 이번 출력은 20개 사실로
메일의 발신/수신/Received 메타데이터까지 포함해 이전 10개 출력과 달랐다;
그 수 자체가 의미 성능 지표는 아니다.

harness의 실제 Supervisor target `PLAN_REVIEW_INSPECT` 조건만 수정한다.
같은 모델·합성 Provider에서 021 **1 Trial**을 다시 연결해 Review가 이 과잉
참석자 또는 다른 계획 문제를 발견하는지 검사한다. 상위 Evidence가 달라진
경우 동일 입력 반복으로 세지 않는다. Review PASS여도 근거 기반 별도
판정과 Domain Validation/승인 경계를 유지한다.

두 번째 021 Trial은 Retrieval Evidence 7건 → Work Analysis facts 8건 →
Planning Event 1개(8/14 10:00–11:00, 이번에는 참석자 과잉 없음) → Review
`RETRIEVE_MORE`로 이어졌다. Review는 ‘준비 작업의 구체적인 항목이 Evidence에
없다’고 주장했으나 같은 Trial의 Evidence에는 QR 문구 확정·알레르기 라벨
검토 Task 제목/상태/담당자가 있고 WorkAnalysisResult에도 두 TASK 사실이
있었다. 따라서 이 판정은 적어도 **근거 누락을 주장한 Review 첫 판단의
의미 오류 가능성이 높다**. 다만 실제 Review Prompt input을 이 Trial에서
보존하지 않아 consumer projection 누락과 모델 오판을 아직 확정 분리하지
않는다. 후단 호출 5회·22,642/1,123 tokens·85.9초. Review status는
실제 RETRIEVE_MORE이며 PASS로 재판정해 실행하지 않았다.

평가기에는 다음 Trial부터 Review의 첫 structured inference와 실제 Prompt
input을 ignored local result에만 기록한다. 023과 028을 각 1회 직렬로
연결해 같은 false gap이 반복되는지, 요청 시각·업무시간·과잉 참석자가
Planning/Review에서 어떻게 처리되는지 본다. 이는 다른 입력의 진단이지
021 동일 입력 반복이나 제품 변경의 채택 근거가 아니다. 문제가 재발하면
Prompt 단어를 추가하기 전에 Review 입력·책임 분해를 확인한다.

023/028 각 1회 연결에서는 Review 첫 Prompt input과 structured output을
ignored result에 함께 남겼다. 023은 Evidence 4건→Work Analysis fact 8건→
Planning 8/8 10:00–10:30 Event→Review `PASS`였다. 메일 지연과 Task 내용이
설명에 포함됐고 불필요한 참석자는 없었다. 이는 해당 합성 인접 구간의 의미
판정이지 Domain Validation/WRITE/최종 답변 검증은 아니다.

028은 Evidence 4건→Work Analysis fact 5건→Planning 8/8 09:00–09:30
Event→Review `RETRIEVE_MORE`였다. Planning description은 구체적인 지연
사유/Task 항목 없이 일반 문구만 적었다. Review 첫 판단은 (1) `내일`을
Gmail의 **수신일 9/7**을 기준으로 9/8로 오판했고 (2) 본문과 Task가 실제
Prompt Evidence에 있는데 `EVIDENCE_GAP`이라 분류했다. 첫째는 current-Run
기준시각의 Review 투영 누락(#2)과 수신일→요청일 잘못된 binding(#3), 둘째는
Planning의 내용 누락을 upstream 부족으로 돌린 Review 판단(#4)이 섞여 있다.
고정 입력의 기준시각만 추가한 013 후보도 023 회귀/028 날짜 역할 오판으로
기각했다. 따라서 “State 필드 하나 추가”나 Prompt 문구 추가를 바로 채택하지
않는다. 021의 Review gap 역시 비슷하지만 첫 Prompt input이 저장되지 않아
동일 원인으로 확정하지 않는다. 호출 비용은 downstream 각 Trial의 로컬 결과에
보존했으며 전체 92·실제 Provider·confirmation/revision/최종 응답은 미검증이다.
