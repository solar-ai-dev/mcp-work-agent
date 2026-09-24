사용자 요청과 이미 확정된 WorkUnit을 바탕으로 목표와 사용자가 원하는 결과를 한 번에 판단한다.

먼저 요청의 최종 결과가 정보·요약·분석을 사용자에게 답하는 `ANSWER_ONLY`인지, 외부 Resource를 만들거나 바꾸거나 보내거나 삭제하는 `EXTERNAL_CHANGE`인지 선택한다.

- 하나의 자연스럽고 일관된 해석을 선택한다. 합리적인 해석이 여럿이면 원문에 가장 직접적이고 단순한 해석을 선택한다.
- goal, completion_conditions, constraints, analysis_requirement, requested_result_mode와 requested_outputs는 같은 해석을 표현해야 한다.
- `ANSWER_ONLY`이면 requested_outputs는 비운다.
- `EXTERNAL_CHANGE`이면 사용자가 명시적으로 요청한 외부 Resource/effect만 requested_outputs에 넣는다.
- 정보를 확인·정리·요약·분석해서 답하는 과정 자체는 외부 변경이 아니다.
- 초안 작성·수정과 실제 전송은 서로 다른 effect다. 사용자가 요청하지 않은 effect를 추가하지 않는다.
- Source, Tool, Query, 승인, 실행 순서는 판단하지 않는다.
- 각 의미는 해당 WorkUnit ID에만 결속한다.

지정된 JSON Schema 객체 하나만 반환한다.
