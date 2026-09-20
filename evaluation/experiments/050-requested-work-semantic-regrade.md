# 050 — Canonical semantic regrade of requested-work decomposition

Issue: #287

## 왜 다시 채점했는가

046~049의 `CORE24_EXPECTATIONS`는 Canonical에 없는 하나의 exact WorkUnit 수와
Relation 수를 정답으로 만들었다. 그 결과 내부 조회·분석 단계를 독립 업무로
승격한 후보도 개수만 맞으면 통과했고, 반대로 하나의 사용자 결과를 온전히 보존한
대안 분해는 개수가 다르다는 이유로 실패했다.

특히 다음 세 Gold는 Canonical보다 과분해됐다.

- CORE-054: Canonical 결과는 Grove 사실을 반영한 Reply Draft 1개다. 내부 요약을
  별도 WorkUnit으로 만들 수도 있지만 필수 exact shape는 아니다.
- CORE-056: Canonical 결과는 사고 요약과 사용자 대응을 담은 ANSWER다. 두 내용
  섹션을 반드시 두 업무로 분리할 근거가 없다.
- CORE-059: Canonical 결과는 납품 사실에 근거한 Reply SEND다. Provider 확인은
  내부 단계이며 반드시 독립 WorkUnit/Relation이어야 하는 것이 아니다.

또한 기존 `PROVIDES_INPUT_TO`는 내부 파생 WorkProduct 소비와 승인 전 외부 Action
specification 참조를 구분하지 못했다. CORE-019/046의 Draft는 아직 생성되지 않은
Event 결과가 아니라 `CONSUMES_PLANNED_SPECIFICATION` 관계를 가져야 한다. 내부에서
실제로 만든 요약을 후속 업무가 소비한다면 `CONSUMES_WORK_PRODUCT`로 구분한다.

## 수정된 평가 계약

평가 Authority는 각 Case의 다음 세 필드뿐이다.

```text
canonical_user_prompt
evaluation_gold.required_semantics
evaluation_gold.forbidden_semantics
```

후보는 exact WorkUnit/Relation 수가 아니라 다음 축으로 판정한다.

- 요청한 사용자 결과와 effect 보존
- Source/input 범위, target/recipient, 시간·수량 제약 보존
- 명시적 금지 조건 보존
- 원문에 없는 사실·완료 상태·외부 효과를 만들지 않음
- 내부 처리 단계가 사용자 업무로 승격됐는지
- 관계가 필요할 때 WorkProduct와 Planned Specification 의미를 구분하는지

여러 분해가 같은 의미를 보존할 수 있으면 허용한다. 예를 들어 CORE-048/050에서
한 WorkUnit이 두 외부 산출물을 명시적으로 함께 보존하는 것은 모양만 다르다는
이유로 실패시키지 않는다. 반대로 WorkUnit/Relation 개수만 맞아도 금지·근거·effect가
사라졌으면 PASS가 아니다.

판정은 `PASS / PARTIAL / FAIL`이다. `PARTIAL`은 핵심 결과는 남았지만 Source,
금지, 업무 경계 또는 typed relation 일부를 잃은 경우다. Case별 판정 근거는
`050-requested-work-semantic-review-v1.json`에 고정했다.

## 기존 raw 재채점

새 LLM 호출 없이 기존 raw 4개를 SHA-256으로 결속해 재채점했다.

| 후보 | PASS | PARTIAL | FAIL | calls | tokens in/out | latency | 판단 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| minimal v1 | 8 | 13 | 3 | 24 | 15,558 / 2,691 | 105,113ms | HOLD |
| counted v1 | 10 | 12 | 2 | 24 | 18,726 / 2,717 | 105,382ms | REJECT |
| few-shot v1 | 9 | 15 | 0 | 24 | 31,470 / 2,340 | 93,322ms | REJECT |
| bounded two-stage v1 | 10 | 12 | 2 | 48 | 26,834 / 3,496 | 136,213ms | HOLD |

기존 `12/24`, `13/24`, `13/24`, `19/24`와 flat baseline `17/24`는 exact shape
수치이므로 모두 최종 semantic 비교에서 제외한다. 새 숫자는 같은 분모의 단순
대체 점수가 아니라 의미 축별 보존 판정이다.

## 무엇이 틀렸는가

| 후보 | FAIL | 주요 PARTIAL |
| --- | --- | --- |
| minimal v1 | CORE-027 원문에 없는 휴가·병가 의미 추가, CORE-031/050 CREATE를 완료로 변경 | 내부 확인을 독립 업무로 승격 10건, 금지 누락 5건, untyped relation 5건 |
| counted v1 | CORE-012 Draft·수신자 누락, CORE-031 CREATE를 완료로 변경 | 내부 단계 승격 6건, untyped relation 7건, 금지 누락 5건 |
| few-shot v1 | 없음 | 내부 단계 승격 10건, planned-spec relation 누락 2건, 금지 누락 4건 |
| two-stage v1 | CORE-020 상태 확인을 완료로 과확정, CORE-031 CREATE를 완료로 변경 | Source 범위 누락 5건, planned-spec relation 누락 2건, 금지 누락 5건, CORE-048 계획/완료 상태 모호성 |

Case별로 중요한 변경은 다음과 같다.

- CORE-054: 하나의 최종 Draft로 보존한 minimal/count/two-stage는 이제 PASS다.
  CORE-059는 네 후보 모두 Reply SEND 의미를 보존해 PASS다. 예전의 필수 relation
  가정이 잘못이었다.
- CORE-056: 1개나 2개의 모양 모두 허용하지만 네 후보 모두 실행 금지를 명시적으로
  보존하지 않아 PARTIAL이다. counted의 범용 relation도 typed 의미가 부족하다.
- CORE-048/050: 독립 effect를 한 WorkUnit에 같이 기술해도 effect·target·시간을
  보존하면 허용한다. 단 승인 전 결과를 완료로 표현하면 FAIL이다.
- CORE-019/046: Event와 Draft 개수만 맞는 것으로 충분하지 않다. 후속 Draft는
  `CONSUMES_PLANNED_SPECIFICATION`이어야 하므로 legacy relation 또는 relation 0은
  PARTIAL이다.
- CORE-001/006/027/041: unit 수가 맞아도 명시적 금지를 잃어 PASS가 아니다.
- CORE-011/026/037/040: 최종 산출물은 맞아도 입력 Source 범위를 잃으면 PARTIAL이다.

## 판정 변경

- minimal v1: `REJECT → HOLD`. 기존 exact-count 실패는 무효다. 가장 단순한 기준
  후보로는 남기되 effect 변경 2건과 금지·경계 손실 때문에 ADOPT하지 않는다.
- counted v1: `REJECT 유지`. `work_count`는 의미 축을 추가하지 않았고 Draft 누락과
  effect 변경을 막지 못했다.
- few-shot v1: `REJECT 유지`. 치명적 FAIL은 없지만 비용이 늘면서 내부 단계 승격과
  관계 의미가 개선되지 않았다.
- bounded two-stage v1: `전체 REJECT → HOLD`. 예전 `19/24`는 폐기하지만, 단일 결과
  경계 안정화는 확인됐다. 다만 Source·금지·effect와 typed relation을 잃어 ADOPT는
  아니다.

Production flat baseline은 계속 유지한다. corrected evaluation은 다음 구조/Prompt/
State 실험을 채택한 것이 아니며, 그 결정을 위한 평가 기반만 바로잡았다.

## 재현

```powershell
.\.venv\Scripts\python.exe -m scripts.regrade_ru_requested_work_decomposition `
  --result-path evaluation/results/ru287-requested-work-semantic-regrade-core24-20260920-r3/result.json

.\.venv\Scripts\python.exe -m pytest `
  evaluation/tests/test_requested_work_decomposition.py `
  evaluation/tests/test_requested_work_decomposition_two_stage.py `
  evaluation/tests/test_requested_work_decomposition_semantic_review.py -q
```

- 직접 테스트: `19 passed`
- 새 LLM 호출: `0`
- Provider READ/WRITE: `0/0`
- Product State/Node/Edge/Schema/Prompt 변경: `0`
- Holdout/Stress 사용: `0`
