# 045 — connected work product handoff

> 범위 정정: 이 실험은 실제 중간 산출물 materialization과 consumer handoff까지
> 결합한 downstream 계약 실험이다. #287의 첫 단계인 사용자 원문 업무 분해 후보를
> 채택·기각하는 근거로 사용하지 않는다. 아래 결과와 `REJECT`는 결합 후보에만
> 적용하며 최소 decomposition 가설에는 적용하지 않는다.

Issue: #287 (구조 실험), #288 (채택 시 공유 계약), #294 (구조 채택 후 Prompt 최적화)

## 결론

`IntermediateWorkProduct`를 Retrieval Evidence나 `WorkAnalysisResult`와 분리하고,
same-run `product_ref`로 후속 업무에 전달하는 bounded compiled gate는 성립했다.
그러나 현재 Request Understanding 분할 후보는 단순 요청 과분해와 기존 responsibility 누락을
동시에 일으켰다. 따라서 제품 적용은 `HOLD`, 현재 후보는 `REJECT`다.

제품 State/Node/Edge/Schema/Prompt는 변경하지 않았다. 중간 산출물의 production owner도
Work Analysis 또는 Planning으로 선결정하지 않았다. 평가 gate에서는 독립된
`INTERMEDIATE_WORK_PRODUCT_MATERIALIZER` 경계로만 표현했다.

## 고정 조건

- 시작 SHA: `1dd60dca0011722b2be792e6706effc13db861a1`
- Dataset: Canonical 92 v8, SHA-256
  `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Fixture SHA-256:
  `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`
- Model: `qwen3.5:9b`
- Model digest:
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature `0.0`, seed `20260920`, Case당 1회, Holdout 미사용
- checked-in Provider fixture와 synthetic read만 사용, Provider WRITE `0`

## Baseline

Core 6개(`001/009/012/019/023/046`)를 현재 production RU부터 synthetic
Work Analysis 경계까지 1회 실행했다. 총 672,376ms, retrieval 구간 LLM 19회,
connector read 19회, Provider WRITE 0이었다. `planning_review_requested=true`였지만
`planning_executed=false`였고, 업무 1의 실제 파생 결과를 업무 2가 typed ref로 소비하는
계약은 없었다. 장시간 baseline 결과는 그대로 보존했고 재실행하지 않았다.

결과: `evaluation/results/ru287-connected-work-baseline-core6-20260920/result.json`

## 후보 비교

| 후보 | Core | 결과 | calls | input/output tokens | latency | 판정 |
|---|---|---:|---:|---:|---:|---|
| v1 단일 정의 | 001/012/046 | 1/3 completed | 4 | 8,629 / 2,116 | 80,045ms | relation/condition contract 불안정, REJECT |
| v2 분해+조건 귀속 | 001/012/046 | 2/3 completed | 12 | 26,396 / 3,758 | 138,374ms | A′ 전달 확인, 단순 요청 과분해·Resource/effect 오류, REJECT |
| v3 constraint ref | 001/012/023 | 2/3 completed | 12 | 31,239 / 5,233 | 191,424ms | 기존 output 밖 SEND 생성·relation 불일치, REJECT |
| v4 responsibility ref+relation 귀속 | 001/012/023 | 2/3 completed | 16 | 27,231 / 5,505 | 189,213ms | extra output 차단, 단순 요청 과분해·source 누락, REJECT |

v4의 Case별 결과:

| Case | 업무/관계/산출물 | calls | 결과 |
|---|---:|---:|---|
| CORE-001 | 3 / 2 / product 2 | 6 | 단순 READ를 3개로 과분해하여 회귀 |
| CORE-012 | 4 / 3 / product 3 + planned spec 1 | 7 | 실제 product ref 전달 및 `PLANNED_NOT_EXECUTED` 확인 |
| CORE-023 | 정의 단계 실패 | 3 | validated source responsibility 미배정 |

각 후보는 고정 Case당 1회만 실행했다. 실패 Trial을 성공 Trial로 교체하지 않았다.

## 최초 divergence

baseline에는 중간 업무 산출물을 표현할 artifact와 consumer projection이 없다. 후보에서는
`decompose_requested_work`가 최초 divergence였다. v3는 검증된 output responsibility를
다시 자유형 Resource/effect로 생성했고, v4는 stable responsibility ref로 이를 막았지만
simple READ를 불필요한 product chain으로 과분해하고 복합 Case의 source responsibility를
누락했다.

이는 product materializer나 consumer 문제가 아니라 RU의 업무 경계 producer 문제다.
Validator로 의미를 보정하지 않았으며 잘못된 정의는 거절했다.

## Bounded compiled gate

직접 component test 10개와 기존 Request Understanding 인접 unit suite를 함께 실행해
총 251개가 통과했다. 직접 gate는 다음을 고정한다.

- `decomposition → actual IntermediateWorkProduct → product_ref → consumer` 연결
- consumer가 raw user request를 받지 않고 결속된 product를 소비
- 단순 요청은 product 없이 한 단위 유지
- 외부 Action 전에는 `PLANNED_NOT_EXECUTED` specification만 전달
- Provider result는 승인 전 존재한다고 가정하지 않음
- external write count `0`
- 미등록 constraint ref, relation/binding 불일치, relation cycle 거절
- 일치하는 Evidence 없는 product materialization 거절
- 위조된 product lineage와 승인 전 `EXECUTED` 주장 거절

## 결정

- IntermediateWorkProduct 표현/전달 경계: 구조적으로 유효
- 현재 RU 업무 분할 후보: `REJECT`
- production 적용 및 #288 Canonical/Schema 변경: `HOLD`
- #294 Prompt/Few-shot 최적화: 구조 채택 전이므로 미진행
- 미검증: production compiled workflow 통합, Holdout, Canonical 92 전체

다음 후보가 필요하면 단순 요청의 atomicity와 모든 validated responsibility의 완전 귀속을
먼저 만족시켜야 한다. 이번 결과만으로 새 production owner를 결정하지 않는다.
