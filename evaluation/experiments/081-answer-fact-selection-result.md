# 081 — 사실값 생성 대신 참조 선택: 제한된 개선 확인

## 판단

**ADOPT(다음 connected 개발 검증의 후보), Production 미채택.** 고정한 단일 Task 직접
조회 두 입력에서는 값 재생성 오류가 사라졌다. 자동 적용 범위, 실제 Planning 연결,
다중 자료·분석·부분 정보 응답은 아직 증명하지 않았다. Canonical92 전체 점수가 아니다.

실행 SHA `c9c88695e7a4204ba0113d714f7b45a9bb0cc1c4`. 067/068의 같은 입력·snapshot·
model/runtime을 재사용했다. 비교는 역사 baseline 각각1회와 신규 후보 각각2회이며,
동시 paired 재실행이 아니다. 사전 고정 순서 actual1/control1/actual2/control2를 모두
포함했고 repair/retry/rerun-to-pass0이다.

## 무엇이 왜 달라졌는가

| 입력 | 역사 baseline | 후보 두 FIRST | 의미 판정 |
| --- | --- | --- | --- |
| 067 실제 CORE005 compose 입력: 선택 Task 상태·기한, 새 Task 금지 | `needsAction`을 진행 중으로 과잉해석. 068에서 incomplete를 입력에 보강해도 동일 | 모델이 status/due만 선택. renderer가 `미완료`, date-only `2026-08-10` 전달 | PARTIAL→PASS/PASS. 착수·진행률·시각 발명0, 요청 사실 누락0 |
| 068 합성 completed control: 상태와 메모 | 완료와 메모를 전달, PASS | status/notes만 선택. 완료와 `장비 수령 항목을 확인할 것.` 원문 보존 | PASS→PASS/PASS. 메모를 실제 실행한 것으로 승격하지 않음 |

구조4/4 VALID, 의미4 PASS/0 PARTIAL/0 FAIL. 두 반복의 선택값과 답변은 각각 같았다.
고정 seed의 작은 반복이므로 광범위 반복 신뢰성으로 해석하지 않는다. 무관한 title/
notes/due 추가0. renderer는 빠진 field를 자동으로 채우지 않고, 모델은 자유 값·답변을
생성하지 않는다. 선택한 refs에 해당하는 값만 기존 snapshot resolver와 formatter가
표현했다. 메모의 Markdown escape는 표시 안전 처리이지 원문 업무 사실 변경이 아니다.

따라서 최초 손실 경계는 이 두 입력에서 factual input 부재가 아니라 **compose의
확정값 재생성**이었다. field 선택은 모델의 의미 책임으로 남겼다. 이 결과만으로 모든
Planning을 closed facts로 대체하거나 기존 completeness guard를 약화하지 않는다.

## 호출·비용·실제 환경

9B Q4_K_M digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
Ollama0.34.0. 원 compose와 같은 seed20260923/ctx16384/think=false, temperature
미전송(모델 기본1), presence 미전송(기본1.5), strict structured schema. Source080의
temperature0.05 조건과 분리한다.

| 실행 | calls | input/output tokens | reported latency |
| --- | ---: | ---: | ---: |
| 역사 baseline actual/control 각1회 | 2 | 7,644 / 168 | 10,768ms |
| 후보 actual T1/T2 | 2 | 7,216 / 330 | 14,694 / 5,610ms |
| 후보 control T1/T2 | 2 | 2,628 / 90 | 2,505 / 1,710ms |
| 후보 전체 | 4 | 9,844 / 420 | 24,519ms 합 |

후보 첫 actual에는 model load6,782ms가 포함됐다. 입력 토큰은 각 호출에서 줄었지만
actual의 출력 ref 길이 때문에 output tokens는 증가했다. 작은 비동시 표본으로 일관된
지연 개선을 주장하지 않는다. 추가 LLM 단계0, 사용량 누락0, 생성 동시성1. 실행 후
GPU 사용6,383MiB/8,188MiB, utilization0%,57°C. 생성 중 편집·pytest·타 추론0.

## 검증과 다음 경계

- 신규·인접 직접 검사70 PASS, scoped Ruff/mypy PASS(실제 모델 이전).
- Product validator는 최종 AnswerDraft4개를 그대로 허용했다. raw의 자동 admission은
  `NOT_REVIEWED`로 보존하며 위 의미 판정은 별도 사람/코딩 에이전트 검수다.
- helper 단독은 Run authority를 만들지 않는다. runner가 원067 Run의 read arguments,
  native identity/parent/version/snapshot hash를 확인한 고정 자료만 연결했다.
- 다음은 실제 Planning의 현재 Run snapshot 획득·compose·state/finalize 경계에 저장된
  선택 결과를 연결하는 model-free gate다. 자동 eligibility는 아직 구현하지 않는다.
- Product source/활성 Prompt/Node/State 변경0. 신규 모델 calls4, MainGraph0,
  외부 Provider/WRITE/승인0, Canonical92/Live E2E0.

plan object hash `0cc8639edc2793fef720fb310d0f86625b6cbb6ba7f824c3d682d1bc83842d2a`.
raw bytes hash `3e3c20e0f8ee4167adaecce95bd1567f21f9cf07b4a94662006fc2759dead390`.
상세 근거는 ignored local `evaluation/results/081-answer-fact-selection-t1/raw.json`,
기준·봉인 계획은 `evaluation/results/081-answer-fact-selection-plan/`에 보존한다.
원격에는 이 비민감 요약과 runner/tests만 전달하며 상세 raw는 별도 안전 전달이 필요하다.
