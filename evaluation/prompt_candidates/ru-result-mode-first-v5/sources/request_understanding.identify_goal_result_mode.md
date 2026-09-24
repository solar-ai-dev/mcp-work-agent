사용자 원문과 이미 확정된 WorkUnit만으로 사용자가 원하는 업무 목표와 최종 결과 종류를 판단한다.

- 하나의 자연스럽고 일관된 해석을 선택한다. 합리적인 해석이 여럿이면 원문에 가장 직접적이고 단순한 해석을 선택한다.
- 정보를 찾아 확인·정리·요약·분석해서 사용자에게 답하는 결과는 `ANSWER_ONLY`다.
- 외부 Resource를 만들거나 바꾸거나 보내거나 삭제해 달라는 결과는 `EXTERNAL_CHANGE`다.
- 입력 자료나 조사 대상의 Resource 명칭을 요청 결과로 바꾸지 않는다.
- goal, completion_conditions, constraints, analysis_requirement와 requested_result_mode는 같은 해석을 표현해야 한다.
- Source, Tool, Query, 구체적인 Output Resource/effect, 승인, 실행 순서는 판단하지 않는다.

지정된 JSON Schema 객체 하나만 반환한다.
