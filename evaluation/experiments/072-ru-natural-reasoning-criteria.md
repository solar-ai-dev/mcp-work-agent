# 072 — 짧은 자연어 의미 입력에서 native reasoning 대조

## 새 근거와 비교 축

071의 Schema/catalog/생성 Goal 없는 실제9B FIRST에서도 017의 Task 범위 축소와
reference time 오전09시→오후09시 변형, 049의 Task 기한→인계 시작 의미 혼동이 남았다.
Source 이름만 복원된 것을 전체 의미 성공이라고 하지 않는다.

과거 064 v12/v13의 think=true는 Product Source의 큰 입력/출력 계약에서 완료 응답을
얻지 못했다. 이를 재실행하지 않는다. 이번에는 이미 실행한 **짧은 자연어 입력과 출력**에서
native reasoning만 켜 보고, 추론 예산이 이 조건에서도 부적합한지 확인한다.
새 Prompt 규칙, 예제, Field, Product 수정이나 모델 교체 실험이 아니다.

## 고정 계획

- 071 raw `evaluation/results/071-ru-semantic-capability-t1/raw.json`, SHA256
  `fe18703f5bc62bdd7b0be56f615d248d22df1fd81f4abb0ff4a99d853796c9df`.
- 그 raw에 결속된 exact plan/input/options/runtime을 사용한다. 071의 Product wire/기록은
  바꾸지 않는다. 시작·종료 HEAD/code/model/dataset/fixture hash를 별도로 잠근다.
- Core017 → 049 → 005, 각 신규 FIRST1, 총 상한3. 실패군2+기존 성공control1.
- 바뀌는 payload key는 `think: false → true` 하나다. system/user text·sampling·모델·
  stream=false·출력 무Schema는071과 동일하다. 원문·선택·기준시각 외 자료/정답을 넣지 않는다.
- timeout180초, 직렬 동시1. repair/retry/rerun-to-pass0. timeout/transport/model drift/
  미완료 응답에서는 미실행 Case를 기록하고 종료한다. 실패를 다른 Trial로 바꾸지 않는다.
- final response만 검수한다. hidden reasoning 원문은 저장·검수하지 않고 존재/크기와
  reported token/latency 등 사용량 metadata만 관측한다.
- generation 중 코드 편집·pytest·다른 모델0. 실행 후 자원 snapshot을 기록한다.

## 사전 판정·다음 판단

071의 같은 Case 의미 기준을 그대로 적용한다. 새로운 문장 일치·WorkUnit 수·정답 분해를
요구하지 않는다. 최초 출력의 Source 범위, Task 기한/Event 시작, 주어진 clock, 요청한
최종 결과와 금지를 비교한다. 기존005 의미 회귀와 불필요 WRITE 추가를 별도로 확인한다.

017/049의 변형이 줄고005를 유지하면, 무거운 Product Schema 생성과 분리한 의미 owner
연결 후보를 검토한다. 단발3개 진단만으로 Product think=true 활성화나 전체 노드 개편을
채택하지 않는다. 효과가 없거나 응답 비용이 과하면 이 조건의 native reasoning을 기각하고
인식/생성 차이 또는 독립 학습자료 기반 adaptation 등 다른 축을 선택한다.

이번 결과는 자연어 이해 control이지 RU→Tool Route·최종 업무·Canonical92 점수가 아니다.
실제 Provider READ/WRITE0, 승인0, Graph0, Product/Prompt/State/Schema 변경0.
Holdout/Stress·외부 학습·모델 다운로드는 포함하지 않는다.
