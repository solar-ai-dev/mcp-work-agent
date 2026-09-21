# 058 — RequestedWork relation semantic owner

Issue: #287 / #288, 선행 결정: 056 item-owned binding, 057 downstream handoff

## 결론

WorkRelation owner는 optional relation 목록을 직접 생성하는 v1보다, 확정된 WorkUnit의 모든
directed pair를 `NONE | fixed allowed relation kind`로 한 번씩 판정하는 v2가 안정적이었다.

v2는 bounded Core diagnostic에서 precision/recall `1.0/1.0`, Case exact match `8/8`,
validator 통과 `8/8`, semantic input 무변경 `8/8`이었다. 단일 WorkUnit control 3개는
relation LLM을 호출하지 않았다.

추가 Prompt/Few-shot 실험은 중단한다. 057의 connected handoff와 이번 relation owner를
합쳐 `RequestIntentV3 → Tool Route → Retrieval → Planning` atomic Production migration을
구현할 수 있는 상태다. 아직 Product contract나 Production code에는 적용하지 않았다.

## 입력 Authority와 진단 집합

입력 WorkUnit과 기존 RU semantic item은 고정했다. Relation 단계는 Source, effect,
constraint 또는 WorkUnit 경계를 다시 판단하지 않았다.

Holdout/Stress는 사용하지 않았다. Canonical Core에서 다음 bounded set을 사용했다.

| Case | 고정 WorkUnit 형태 | relation authority |
| --- | --- | --- |
| CORE-019 | Event 계획 + 일정 안내 Draft | `CONSUMES_PLANNED_SPECIFICATION` |
| CORE-046 | Event 계획 + “그 일정” 안내 Draft | `CONSUMES_PLANNED_SPECIFICATION` |
| CORE-054 | 결과 정리 + Reply Draft | `CONSUMES_WORK_PRODUCT` |
| CORE-047 | Task UPDATE + Event CREATE | 관계 없음 |
| CORE-048 | Task UPDATE + Event CREATE + Reply Draft | 관계 없음 |
| CORE-001/041/056 | 단일 WorkUnit control | 호출 없음, 관계 없음 |

CORE-054의 2-WorkUnit 형태는 corrected semantic review가 허용한
`derived_summary_then_reply_draft`를 조건부 입력으로 사용했다. 이를 유일한 Canonical
decomposition으로 승격하지 않는다.

모든 WorkUnit provenance는 현재 Canonical user request의 exact substring offset으로
검증했다. endpoint는 현재 WorkUnit ID의 closed set이며 self relation과 duplicate pair는
validator가 거절한다.

## v1 최초 실패

v1은 관계가 있을 때만 배열 항목을 생성하고 relation kind도 모델이 선택했다.

| Case | 실제 출력 | 문제 |
| --- | --- | --- |
| CORE-019 | `event → draft / CONSUMES_WORK_PRODUCT` | endpoint는 맞지만 고정 Event Output을 내부 산출물로 다시 판단 |
| CORE-046 | 관계 없음 | 명시적인 “그 일정” 계획 명세 관계 누락 |
| CORE-047 | `task → event / CONSUMES_WORK_PRODUCT` | 독립 결과의 순서를 입력 의존으로 과장 |
| CORE-054 | summary → draft / WORK_PRODUCT | 정상 |
| CORE-048 | 관계 없음 | 정상 |

v1 결과:

- exact match `5/8`
- validator 통과 `6/8`
- TP/FP/FN `1/2/2`
- precision/recall `0.333/0.333`

최초 문제는 Prompt 지식 부족보다 representation이었다.

- 관계 없음이 명시적 결정으로 남지 않아 empty-list omission과 false relation을 구분하기
  어려웠다.
- Source WorkUnit의 외부 Output 책임으로 이미 결정할 수 있는 relation kind를 모델이 다시
  판단했다.

## v2 contract

v2는 Node나 LLM call 수를 늘리지 않았다.

```text
finalized WorkUnit[]
+ item-owned semantic items
→ deterministic directed WorkUnit pair set (self 제외)
→ source WorkUnit의 fixed Output responsibility로 allowed relation kind 결정
→ one LLM call: pair별 NONE 또는 allowed kind
→ exact pair coverage validator
→ positive decision만 WorkRelation[]로 materialize
```

핵심 경계:

- Output responsibility가 있는 source WorkUnit의 허용 kind는
  `CONSUMES_PLANNED_SPECIFICATION`이다.
- 그렇지 않은 source WorkUnit의 허용 kind는 `CONSUMES_WORK_PRODUCT`다.
- 모델은 kind를 재판단하지 않고 실제 입력 의존 여부만 판정한다.
- 모든 pair를 정확히 한 번 판정해야 하며 누락·중복·self endpoint는 거절한다.
- 단일 WorkUnit이면 pair가 없으므로 LLM 호출은 0이다.
- WorkRelation을 Approval, Execution 결과 또는 Planning Action dependency로 변환하지 않는다.

## 결과 비교

- Product HEAD: `4fd1a8f3f06552ceed9bad612dbe974b9be23795`
- Dataset SHA-256:
  `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Model/digest: `qwen3.5:9b` /
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature/seed: `0.0 / 20260921`
- Holdout/Stress: `0`
- Provider READ/WRITE: `0/0`

| 지표 | optional-list v1 | exhaustive-pairs v2 |
| --- | ---: | ---: |
| Case exact match | 5/8 | 8/8 |
| Validator PASS | 6/8 | 8/8 |
| TP / FP / FN | 1 / 2 / 2 | 3 / 0 / 0 |
| Precision | 0.333 | 1.0 |
| Recall | 0.333 | 1.0 |
| WORK_PRODUCT P/R | 0.333 / 1.0 | 1.0 / 1.0 |
| PLANNED_SPECIFICATION P/R | 0 / 0 | 1.0 / 1.0 |
| Relation LLM calls | 5 | 5 |
| 단일 WorkUnit skipped | 3 | 3 |
| Input tokens | 3,993 | 4,304 |
| Output tokens | 189 | 628 |
| Model latency | 8,455 ms | 23,023 ms |
| semantic input unchanged | 8/8 | 8/8 |

v2는 3-WorkUnit Case에서 6개 directed pair를 모두 명시하므로 출력 토큰과 지연이 늘었다.
이는 의미 안정성과 교환한 비용이다. 현재 WorkUnit 최대 수가 커질수록 pair 수는
`n × (n - 1)`이므로 Production migration에서 기존 WorkUnit 상한, structured-output budget,
latency gate를 직접 고정해야 한다. 이 비용을 줄이기 위한 추가 Prompt 실험은 이번 단계에서
하지 않는다.

## 실행 기록 주의

첫 preflight는 CORE-019 모델 호출 1회 후 runner의 Dataset hash 함수 인자 누락으로 결과 저장
전에 중단됐다. 해당 호출은 성공 Trial로 대체하거나 점수에 포함하지 않았고 별도
`harness-error.json`에 남겼다. runner-only 수정 후 v1과 v2는 각 Case를 한 번씩 실행했다.

- scored run rerun-to-pass: `0`
- harness recovery로 중복 시작된 모델 호출: `1` (출력 미보존, 점수 제외)

## Atomic Production migration 판정

**READY_FOR_ATOMIC_IMPLEMENTATION**

057 범위에 다음 relation owner를 추가한다.

1. RU에서 WorkUnit과 item-owned `work_unit_ids` finalize
2. multi-WorkUnit에만 deterministic pair projection
3. fixed Output responsibility로 pair별 허용 relation kind projection
4. 한 relation semantic call에서 모든 pair를 `NONE | allowed kind`로 판정
5. closed endpoint, self 금지, exact coverage, fixed-kind validator
6. positive decision만 `RequestIntentV3.requested_work.work_relations`에 materialize
7. 057의 Tool Route → Retrieval → Planning handoff로 전달

Producer, validator, RequestIntent State, downstream projection과 consumer를 한 migration에서
변경해야 한다. V2와 V3를 두 개의 live semantic authority로 유지하지 않는다.

## 검증

- relation candidate unit tests: `8 passed`
- RequestedWork binding / connected handoff / two-stage 관련 gate: `47 passed`
- Ruff: PASS
- Mypy (새 evaluation source): PASS

## 산출물

- `evaluation/requested_work_relation_candidate.py`
- `evaluation/prompt_candidates/ru-requested-work-relation-v1/`
- `evaluation/prompt_candidates/ru-requested-work-relation-decision-v2/`
- `scripts/evaluate_ru_requested_work_relations.py`
- `evaluation/tests/test_requested_work_relation_candidate.py`
- `evaluation/results/ru287-288-requested-work-relation-v1-core8-20260921-r2/result.json`
- `evaluation/results/ru287-288-requested-work-relation-exhaustive-v2-core8-20260921/result.json`
