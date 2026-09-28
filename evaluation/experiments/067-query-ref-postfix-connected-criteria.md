# 067 — 採택한 exact-ref Schema 수정의 실제 MainGraph 사후 확인

## 이번 확인의 이유와 제한

066 T3는 실제 Production에서 invalid bare ID FIRST/revision을 모두 보존한 실패 기록이다.
이후 Product commit `b7c449fa`가 generation Schema를 기존 validator의 exact-ref authority와
일치시켰고 직접14/관련1,698 검사로 구조 회귀를 확인했다. 실제9B+upstream MainGraph에서
이 수정 경계를 거쳤는지는 아직 확인하지 않았다. 이번 실행은 **그 변경 후 고정1 Trial**이며
기존 T1/T2/T3 실패를 대체하거나 같은 코드에서 성공할 때까지 재실행하지 않는다.

066의 '새 RU 변형은 근거 부족' 판단은 유지한다. 새 Prompt/Schema 후보를 추가하지 않는다.
이미 채택한 코드의 미검증 연결을 닫는 것은 새로운 RU random search와 구분한다.

직접 Query 입력 replay를 만들지 않는다. T3 Prompt projection은 TASK_LIST discovery도
coarse TASK로 표기한다. 이 projection을 frozen Route로 역캐스팅하면 authority를 바꾸므로,
원 StartRun/compiled MainGraph가 새 Route와 Query projection을 직접 만들게 한다.

## 사전 고정

- 기존 변경 없는 `scripts/evaluate_production_snapshot_workflow.py`, candidate=None.
- Canonical CORE005, 신규 Trial **1회**, actual wire 최대20/외부 wall600초.
- 원문/Gold/selected identity/parent/계정-bound local scope/snapshot 변경0.
- 원 historical-fact Case reference_time=null 유지. 실제 Run UUID/시각은 별도 기록한다.
- qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  Ollama0.34.0, seed20260923, ctx16384, think=false. owner별 실제 sampler 불변.
  미전송 temperature를0으로 기록하지 않는다.
- 실행 HEAD/Product tree/Prompt tree/Registry/Dataset/snapshot/Python/dependencies는
  commit 후 기존 build_plan으로 봉인한다. 원 T3 파일 hash 불변을 종료 후 확인한다.
- 로컬 snapshot READ만 사용. 실제 Provider READ/WRITE, 승인/confirmation resume0.
  사용자 DB/서버/브라우저/credential 접근0. release/activation 변경0.
- 모델 동시1. 실행 중 편집·pytest·다른 모델0. 시작자원 RAM여유19.54GiB/GPU0/8188MiB·42°C.
- 결과는 별도 `evaluation/results/067-query-ref-postfix-connected-t1/`에 보존한다.

## 판정

1. 원문→Work/Goal/Source/Output→Route의 첫 차이를 보존한다. 다른 upstream 해석이 나오면
   Query fix의 효과로 단정하지 않는다. Query에 미도달하면 수정의 실제 모델 연결은 미검증이다.
2. Query 도달 시 실제 first schema가 해당 Route의 exact ref를 enum에 포함하는지,
   FIRST/ref/revision과 validator/build 결과를 확인한다. bare ID를 사후 보정하지 않는다.
3. snapshot READ 대상/상태/예정일의 provenance와 실제 답변까지 별도로 확인한다.
   Query 구조 성공을 업무 성공으로 승계하지 않는다. 미요청 WRITE 의미가 생기면 별도 실패다.
4. 미완료 상태와 date-only 예정일을 정확히 답하고 요청하지 않은 외부 변경을 만들지 않아야
   업무 의미 PASS다. 표현·정상 조회 순서 차이는 허용한다.
5. 실패/상한/대기/환경 오류도 원 기록으로 남기고 추가 Trial을 만들지 않는다.
   결과 이후 확정 코드 결함은 해당 owner에서 처리할 수 있지만 이 기준의 횟수는 늘리지 않는다.

이는 단발 현재 경로 확인이지 반복 안정성/Canonical92 전체 평가/Live E2E가 아니다.
RU 잔여 의미 실패·후속 업무 성공과 Query identity 계약을 분리해 보고한다.
