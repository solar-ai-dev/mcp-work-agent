# 049 — Bounded two-stage requested-work decomposition

> **Corrected evaluator notice (2026-09-20):** 이 문서의 `19/24`, Stage 1 exact
> count, relation count 판정은 Canonical에 없는 단일 분해 모양을 Gold로 사용해
> 폐기했다. 의미 보존 재채점 결과는 `PASS 10 / PARTIAL 12 / FAIL 2`, 전체 판단은
> `REJECT`에서 `HOLD`로 정정했다. 근거는
> `050-requested-work-semantic-regrade.md`다.

Issue: #287

## 범위와 구조

Production flat baseline과 Product Node/Schema/State/Prompt는 변경하지 않았다.
Evaluation 안에서 `minimal v1`의 의미 책임을 다음 두 호출로만 분리했다.

```text
user_request
→ Stage 1: independent user results
→ Stage 2: exact WorkUnit carry + WorkRelation
```

Stage 1은 독립적인 사용자 결과만 식별한다. Stage 2는 Stage 1의 ID와 objective를
병합·분할·수정하지 않고 WorkUnit으로 옮긴 뒤, 원문에 명시된 산출물 소비 관계만
판단한다. 새로운 lexical rule과 few-shot은 추가하지 않았다.

## 고정 조건

- Candidate Product HEAD: `a088a9a829a6b49697ec8e979a0cee680d3ce91a`
- Canonical 92 v8 SHA-256:
  `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Core 24 expectation SHA-256:
  `999322c76a7f090c8c9d83db93ebada850d5933176711c26d4158ec9e35506f2`
- Stage 1 Prompt SHA-256:
  `0601d93ef5352b09711f4e8de10b59265d856a8dd008b0dcf32223bb4e85fd23`
- Stage 2 Prompt SHA-256:
  `ccaf8203571723a289d3bb960d7b8aaf0fb3798240d807dfeb4bb97ca3491b75`
- Model: `qwen3.5:9b`
- Model digest:
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature `0.0`, seed `20260920`, Case당 각 Stage 1회
- Holdout/Stress 미사용, Provider READ/WRITE `0`

기준 minimal v1은 같은 Dataset·expectation·model·temperature·seed의 기존 고정
Core 24 결과를 사용했다. 그 뒤의 commit은 Evaluation artifact만 변경했으며
Product runtime behavior 변경은 없다.

## 결과

| 비교 | 전체 구조 | 단순 unit 수 | 복합 unit 수 | 관계 필수 Case | Schema | calls | tokens in/out | latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flat baseline | 17/24 | 17/17 | 0/7 | 0/4 | 현재 계약 | 0 | 0 / 0 | 0ms |
| minimal v1 | 12/24 | 8/17 | 4/7 | 1/4 | 24/24 | 24 | 15,558 / 2,691 | 105,113ms |
| bounded two-stage | 19/24 | 17/17 | 2/7 | 0/4 | 24/24 + 24/24 | 48 | 26,834 / 3,496 | 136,213ms |

two-stage는 v1 대비 9건이 새로 구조 일치했고 2건이 회귀했다. 호출은 두 배,
input token은 11,276개, output token은 805개, 누적 latency는 31,100ms 증가했다.

## 단계별 의미 손실

| 관측 | 결과 |
| --- | ---: |
| Stage 1 Schema valid | 24/24 |
| Stage 1 독립 결과 개수 일치 | 21/24 |
| Stage 2 Schema valid | 24/24 |
| Stage 1 ID/objective exact carry | 24/24 |
| 최종 구조 일치 | 19/24 |
| 필수 relation 구조 일치 | 0/4 |

### Stage 1 최초 실패 — 독립 결과 경계 3건

| Case | 기대 | 실제 Stage 1 | 왜 틀렸는가 |
| --- | --- | --- | --- |
| CORE-054 | Grove 결과 정리 → 그 결과로 답장 초안 | 정리와 초안을 결과 1개로 합침 | 명시적인 내부 파생 산출물을 독립 결과로 보존하지 못함 |
| CORE-056 | 메일 요약 + 사용자 대응 정리 | 두 결과를 하나로 합침 | 서로 구분되는 사용자 산출물을 합침 |
| CORE-059 | 일정 확인 → 확인 결과로 답장 | 확인과 답장을 결과 1개로 합침 | 선행 확인 결과가 후속 답장의 입력이라는 의미를 잃음 |

### Stage 2 최초 실패 — WorkRelation 2건

| Case | Stage 1 | 실제 Stage 2 | 왜 틀렸는가 |
| --- | --- | --- | --- |
| CORE-019 | 워크숍 일정과 안내 초안 2개 정확 | WorkUnit은 그대로 전달했지만 relation 0 | 생성할 일정이 안내 초안의 입력이라는 관계 누락 |
| CORE-046 | 점검 일정과 그 일정 안내 초안 2개 정확 | WorkUnit은 그대로 전달했지만 relation 0 | “그 일정”의 실제 산출물 소비 관계 누락 |

Stage 2는 모든 Case에서 Stage 1의 ID와 objective를 정확히 전달했으므로
projection/carry 손실은 없었다. 그러나 전체 24건에서 WorkRelation을 한 건도
생성하지 않아 false positive는 없지만 필수 relation recall은 0/4다.

## minimal v1 대비 변화

새로 구조 일치한 Case:

- CORE-011/012/020/021/027/028/031/036/040
- 공통 개선: 자료 확인 절을 독립 WorkUnit으로 승격하지 않고 최종 사용자 결과
  하나로 유지했다.

기존 v1 성공에서 회귀한 Case:

- CORE-019: v1은 relation까지 맞았으나 two-stage Stage 2가 relation을 누락했다.
- CORE-056: v1은 독립 결과 2개를 유지했으나 two-stage Stage 1이 하나로 합쳤다.

계속 실패한 Case:

- CORE-046: Stage 1 경계는 고쳤지만 Stage 2 relation 실패
- CORE-054/059: Stage 1에서 선행 결과와 후속 업무를 합침

## 구조 일치 안의 의미 손실

19/24는 WorkUnit/Relation 개수 기준이며 전체 의미 성공이 아니다. objective를
직접 검토하면 최소 다음 손실이 남아 있다.

- CORE-001: 다른 메일 검색 금지 누락
- CORE-006: 다른 준비 업무 분석 금지 누락
- CORE-010: 메일 안의 지시를 따르지 말라는 금지 누락
- CORE-011: Atlas 준비 작업·인쇄소 슬롯이라는 입력 근거 누락
- CORE-020: 상태 확인 요청을 “온보딩 작업 완료”로 과확정
- CORE-026: Atlas 출고와 두 준비 작업이라는 입력 근거 누락
- CORE-027: 일정 생성 금지 누락
- CORE-031: 작업 생성 요청을 작업 완료로 변경
- CORE-037: Atlas 출고 메일·인쇄소 슬롯 입력 근거 누락
- CORE-040: Kestrel 메일·캘린더 입력 근거 누락
- CORE-041: 새 항목 생성 금지 누락

따라서 구조 수치 상승을 전체 RU 의미 품질 상승으로 해석하지 않는다.

## 판단

- 전체 two-stage Candidate: `REJECT`
- Stage 1 boundary split: `HOLD` — 단순 경계는 17/17이지만 복합 결과 3건과
  명시적 조건 보존이 부족함
- Stage 2 relation generation: `REJECT` — 필수 relation 0/4
- Production flat baseline 유지: `YES`
- decomposition 기준 minimal v1 유지: `YES`
- 추가 규칙·few-shot 누적: `NO`
- Product State/Node/Edge/Schema/Prompt 변경: `0`
- rerun-to-pass: `0`

두 단계 분리는 과분해가 주로 Stage 1 책임임을 확인하고 carry 손실을 제거했지만,
복합 결과와 relation을 희생했다. 현재 결과로 #288 shared contract나 Production
Node를 변경할 근거는 없다. 다음 실험을 한다면 규칙을 더 붙이는 대신, relation
판단을 같은 Local Model에 맡기는 접근 자체와 독립 결과의 조건 보존 capability를
별도 후보로 재검토해야 한다.

Raw result:

- `evaluation/results/ru287-requested-work-decomposition-two-stage-v1-core24-20260920/result.json`
