# 064 v35 — Work selector codec connected gate 사전 기준

현재 Product를 기준으로 CORE-005/017/049 × production / work-span-codec-v35를
각 1회, 총 6 arms 순차 실행한다. 실패 Trial을 대체하지 않으며 두 arm은 동일
Product Work Prompt·Schema·sampling과 기존 Goal/Source/Output owner를 사용한다.
joint Goal/Output v4와 token-ref v34는 적용하지 않는다. 실제 모델 호출 전에 작성했다.

## 가설과 판정

- 가설: Work selector의 비공백 문자는 같지만 공백이 달라진 출력을 원문의 유일한
  구간에 결속하면, 생성된 업무 의미를 바꾸지 않고 실제 RU → Tool Route에 전달할 수 있다.
- 현재 Canonical 원문·Gold·selected identity·fixture·기준시각은 변경하지 않는다.
- 005는 exact 선택의 기존 성공 control이다. 선택 Task 상태·기한 조회와 CREATE 금지를
  보존해야 한다. Work 결과가 같다면 후속 Source/Output 변동을 codec의 의미 개선으로
  계산하지 않는다. UPDATE/SEND 등 요청하지 않은 결과는 별도 의미 실패다.
- 017은 Task + 해당 날짜 Calendar를 근거로 지정 수신자에게 충돌 안내 Draft를 준비하는
  요청이다. 049는 메일 근거의 인계 Task / 점검 Event / 안내 Draft라는 결과와 서로 다른
  시간 조건을 보존해야 한다. Work 개수나 하나의 분해 모양을 Gold로 강제하지 않는다.
- 원문 → Work FIRST / repair → exact typed provenance → Goal/Source/Output/금지
  FIRST / repair → RequestIntent → Route를 확인한다. 문자열 결속, 의미 보존, 실제
  component 연결을 각각 판정한다. codec은 missing meaning을 채워 넣지 않는다.
- Source/Output/조건의 의미 평가는 `064-connected-core8-review-criteria.md`의 공통 기준과
  `064-work-ref-v34-review-criteria.md`의 해당 Case 의미 기준을 동일하게 적용한다.
- 미제공 사실·시각·상태를 발명하거나 명시 WRITE/금지/수신자를 바꾸면 FAIL이다.
  정당한 확인은 별도 stop으로 기록하며, 확인이 있다는 사실만으로 FAIL 처리하지 않는다.

## 실행과 채택 한계

실제 snapshot composition, Product router/subgraph, admission/예산을 사용하고
Retrieval 전에 종료한다. Goal/Source/Output FIRST와 repair를 구분하며 기존 bounded repair
이외 model retry를 추가하지 않는다. 각 arm의 상한은 기존 20 dispatch / 600초다.
Provider READ/WRITE/SEND는 0이며 실제 업무 성공·Preview/실행 성공률은 미검증이다.

plan에 SHA·dataset/fixture·Case·Prompt·코드·모델 digest·실제 runtime·기준시각을 결속한다.
raw/calls와 codec 결속 관측은 `evaluation/results/`에 보존한다. 모델은 한 프로세스씩
실행하고 pytest/mypy 등 무거운 검사를 겹치지 않는다. 시작 전 RAM/GPU 여유를 확인한다.

구조가 닫히면 owner-local Product 채택의 근거로 검토할 수 있지만, 3개 1회 결과를
전체 요청 의미 안정성이나 Canonical92 점수로 승계하지 않는다. 이후 범위는 실제 새로
드러난 최초 손실과 기존 raw를 기준으로 결정한다.
