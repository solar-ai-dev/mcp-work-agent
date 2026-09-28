# 087 — 제공할 사실 참조가 없는 입력은 기존 compose authority 보존

085의 새로운 두 입력 중 Task 메모2회는 정확했으나 Calendar2회는 오전10~11시를
오후10~11시로 바꿨다. 065 baseline은 같은 원문/근거에서 올바른 답을 했다. Product
clock/time renderer가 바뀐 것이 아니라 새 choice Prompt/schema를 적용한 FIRST의 회귀다.
이 기록은 그대로 남기며 시간·오전/오후 규칙이나 Case 예제를 추가하지 않는다.

## 변경 책임

사실 참조 후보를 실제로 제공할 수 있을 때만 해당 output capability를 기존 compose에
노출한다. catalog가 없으면 mode 선택지가 없는 기존 PROSE를 새 Prompt로 다시 정의할
이득이 없으므로 **dispatch 전** 원 Product wire를 그대로 선택한다. 이 선택은 요청
단어·정답·모델 결과에 의존하지 않고 기존 검증된 Source facts로 만들 수 있는 closed
pair의 존재만 사용한다. catalog가 있어도 직접 조회라고 판정하거나 PROSE를 금지하지 않는다.

지원하는 입력은083의 의미 선택+084의mode-first를 유지한다. 미지원 입력은 Product
PromptRef/역할/schema/input/options/serialization bytes를 전혀 바꾸지 않는다. 잘못된
응답 뒤에 재호출하는 fallback이 아니며 call 수·Graph Node·semantic retry를 늘리지 않는다.
다른 Run/stale/잘못된 identity를 정상 미지원으로 감춰도 된다는 계약은 아니다. 기존 caller의
Run/version/provenance 검증은 그대로 선행하며 이번 wire 실험은 봉인된 정상 snapshot만 쓴다.

## 모델 추가 없이 검증

- 기존084의 세 입력×2(6개), 085의 정상 Task notes×2(2개)는 새 capability wire가
  각 실제 전송 bytes와 exact equality인지 검사하고 저장 응답을 재사용한다.
- Calendar는 capability wire가 기존065 실제 baseline bytes와 exact equality인지
  검사한다. 기존 baseline은 **1개 응답**이다. 이를2회 실행하거나 신규 성공으로 세지 않는다.
- 085의 실패한 Calendar2개는 기각된 unconditional-choice 결과로 계속 보존한다.
  원 실패를 성공 응답으로 교체해 같은 Trial의 점수를 바꾸지 않는다.
- 총9개의 고유 기존 응답과 wire 연결을 검사하되 신규 모델 호출0. 반환된 schema/답변은
  기존 Product validator로 재검사한다. exact-wire 재사용은 새 반복 신뢰성 실험이 아니다.
- 의미는 기존 원문/사실 기준으로 별도 검수하며 shape 통과를 자동 의미 PASS로 만들지 않는다.

이 변경은 비활성 평가 prototype이며 Product invocation/runtime에 연결되지 않는다.
Product migration 전 Source snapshot을 누가 검증·소비하고 동적 schema를 어느 invoker가
받는지 ownership을 확인한다. Snapshot을 새 LLM input으로 넣거나 Prompt activation을
우회하지 않는다. 그 연결 및 실제 새 upstream Graph가 닫히기 전 Production 채택으로
표시하지 않는다.

Product source/활성 Prompt/State/Graph/Dataset 변경0. Provider READ/WRITE0.
raw는 evaluation/results/087-*에 기존 결과를 덮지 않고 별도로 남긴다.
