# 020. Planning 인자 수정 호출의 이전 Plan·Review issue 결속 후보

기준 `b02ad1eb`와 019의 정적 전달 손실. 현재 Planning ACTION 재진입은
이전 Review issue나 거절된 Plan을 인자 작성 LLM에 주지 않는다. 먼저 기존
제품 Prompt source/output schema를 그대로 두고 작은 `revision_context`만
추가한 개발 input contract를 비교한다. `revision_context`는 같은 frozen
route의 이전 Action과 검증된 Review issue만 담으며, 원문·Evidence·
Tool schema를 변경하지 않는다. 이전 Action은 실행 결과가 아니다.

고정 입력은 012에서 저장한 실제 연결 023의
`planning.compose_arguments_per_output_route` prompt input과 017의 검수된
합성 WRONG_ACTION_DATE/FORBIDDEN_ATTENDEE
Plan·Review finding을 결속한다. 017 합성 입력은 해당 012 Plan과 동일한
frozen route identity를 사용한다. 이 둘은 실제 revision run이 아닌 합성
대조이다. 각 label에서 A=현행 입력, B=A+revision_context 1회씩,
총 **4호출**, 순서 A/B 교차, 모델 digest/temp/seed 동일. 합성 기대 정답은
제품 LLM 입력에 넣지 않는다. 기준은 수정된 시작/종료 시각·참석자 범위를
사용자 요청과 Evidence에 맞게 보존하는지, 이전 오류를 복사하지 않는지,
Schema 통과, 호출 비용이다. A/B 모두 옳다면 이 후보의 개선은 미증명이다.
한 label이 실패해도 다른 label 결과를 보존한다. 실제 수정→Review RECHECK
연결은 이 비교가 충분할 때만 다음 단계로 실행한다. 원출력과 실패 모두
ignored `evaluation/results/planning-revision-input-20260916/`에 남긴다.

## 결과·판단

계획한 4호출 모두 Schema 완료. WRONG_ACTION_DATE에서 A/B 모두 사용자
요구의 8/8 10:00–10:30을 작성했다. FORBIDDEN_ATTENDEE에서도 A/B 모두
미요청 참석자를 추가하지 않았다. B가 후자의 설명에 Evidence 내용을 더
구체적으로 반영했지만 단일 합성 입력이고 원래 목적 두 축의 A도 정확했다.
입력/출력 50,904/2,066 tokens, 호출 경과 65.2초. B는 A 대비 입력
약 1.5k tokens씩 추가했다. 따라서 **revision_context 추가의 의미 개선은
이 비교에서 증명되지 않았고 제품에 채택하지 않는다.** 올바른 Review
finding이 실제 Planning 재진입·RECHECK에서 같은 오류를 반복하는 입력을
먼저 확보해야 한다. 합성 대조를 실제 수정 성공으로 세지 않는다.
