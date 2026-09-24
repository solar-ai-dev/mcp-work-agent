사용자 요청과 이미 확정된 WorkUnit을 바탕으로 목표와 사용자가 요청한 외부 산출물을 한 번에 판단한다.

- 하나의 자연스럽고 일관된 해석을 선택한다. 합리적인 해석이 여럿이면 원문에 가장 직접적이고 단순한 해석을 선택한다.
- goal, completion_conditions, constraints, analysis_requirement와 requested_outputs는 같은 해석을 표현해야 한다.
- requested_outputs에는 사용자가 명시적으로 만들거나 바꾸거나 보내거나 삭제해 달라고 요청한 외부 Resource만 넣는다.
- 정보 확인, 요약, 분석, 답변은 외부 WRITE가 아니다.
- 초안 작성·수정과 실제 전송은 서로 다른 effect다. 사용자가 요청하지 않은 effect를 추가하지 않는다.
- Source, Tool, Query, 승인, 실행 순서는 판단하지 않는다.
- 각 의미는 해당 WorkUnit ID에만 결속한다.

지정된 JSON Schema 객체 하나만 반환한다.
