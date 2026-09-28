# 077 — 단일 Source 판단에서 Goal 파생 조건의 영향

076에서 membership8/8이 맞았지만049 TASK가 새로 만들 Task의 현재 정보를 조회하려
했다. 같은 Source 입력의 Goal.constraints에는 신규 Task 제목·수신자·시각이 기존
조회 조건과 구분되지 않은 search_terms/period로 들어 있다. 원문은 그대로 남아 있다.

**재시도 이유를 구분한다:** constraints 제거 자체는 과거003에서 기각된 방법이다.
이번은076의 단일 Resource 판단에서 membership/새Draft오인이 개선된 뒤 남은
details 대상 혼동과 Goal 조건 오염의 인과를 검사한다. 새로운 해결법으로 포장하거나
003 실패를 지우지 않는다. 효과가 없으면 이 방법을 다시 후순위로 돌린다.

## 고정4회

- Core017/TASK →049/TASK →005/TASK →합성DraftUPDATE/GMAIL_DRAFT 각FIRST1.
- 076 frozen raw `f59b013d514e5fd5ef805a8c5a086341db1442afff5eef1cef05bcc1fb7131d5`와
  current 재구성 exact wire를 대조한 뒤 `input.goal_candidate.constraints`만{}로 변경.
  SYSTEM/USER 양쪽 input 동일변경, 나머지role·Schema·Goal텍스트·Work·원문·selected·clock·
  catalog·focus·model·sampling 모두 그대로. Gold/정답/사람교정자료전달0.
- 합성UPDATE는constraints가이미{}라 wire변경없는고정성공control1회다. 기존실패대체나
  재실행선별이아니며이번진단의명시된반복control이다. 이전Trial을덮어쓰지않는다.
- temp0.05,seed20260923,ctx16384,think=false,기존9Bdigest/Ollama/runtime불변.
- 신규4회,직렬1,timeout180,repair/retry0. generation중편집/pytest/다른모델0.

## 판정·범위

076과같은부분Source의미기준으로채점한다. 049의새Task목표가기존AtlasTask근거로
정정되는지,017목록범위와005선택대상/상태·기한,합성Draft보존값조회가유지되는지본다.
조건없애기가사용자원문제약무시로이어지면개선으로채택하지않는다. 옛Case/Gold변경0.
구조검증과실제의미판정,Source종류선택과details대상,부분Source와전체업무를분리한다.

영향이확인돼도Goalconstraints를Product에서전역삭제하지않는다. 관련owner/Projection의
Source·Output귀속문제를검토하고다른조건·실제upstream·Revision회귀를검증해야한다.
Provider/WRITE/Approval/Graph0,Productsource/활성Prompt/State/Node변경0.
