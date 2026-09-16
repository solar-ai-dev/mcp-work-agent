# 001. retrieval.plan_query Node 분포 최적화

## 목적

전체 Graph E2E를 반복하지 않고, 저장된 Canonical Core 60 checkpoint에서 실제
`RequestIntentV2 + InputToolRouteV1 + current Run user request`를 읽어 production
`retrieval.plan_query`만 재생한다. Connector와 Product Graph는 실행하지 않는다.

주 지표는 deterministic 성공과 분리한 **LLM 경로 대상 34개 중 첫 provider 호출에서
schema와 semantic validation을 모두 통과한 수**다. 실제 provider dispatch가 없었던
pre-dispatch scope 실패 1개는 `llm_path=34`, `llm_dispatched=33`으로 따로 센다.

## 고정 실행 조건

- Checkpoint corpus: `canonical92-v8-5a49aa00-ecf32ffc82`
- Split: Core 60
- Node 입력 존재: 43
- Deterministic success: 9
- LLM path target: 34
- LLM dispatched: 33
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Temperature: `0.0`
- Seed: `1729`
- Connector dispatch: disabled
- Product Graph compile: disabled

## 후보 비교

| 후보 | 변경 | 측정 범위 | 첫 호출 semantic valid | 최종 Node valid | provider 호출 | 판정 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| A | 현재 Run 원문만 추가 | Core 60 | 13/34 | 24/43 | 55 | 기준 |
| B2 | A + provenance exact anchor projection | 영향/대조 24 | 14/24 | 15/24 | 32 | Anchor 개선 확인 |
| C | B2 + 모든 resolved temporal을 필수 projection/schema로 노출 | 동일 24 | 15/24 | 16/24 | 31 | 과잉 binding 회귀로 기각 |
| C2 | Calendar temporal이 실제 해석된 route에만 optional projection/schema 적용 | Core 60 | 25/34 | 34/43 | 41 | 채택 기반 |
| D | C2 + 모든 route의 기존 required kinds를 schema 필수화 | 영향/대조 12 | 11/12 | 11/12 | 13 | 무관 입력 회귀로 기각 |
| E | C2 + Calendar temporal projection이 활성인 route에만 기존 required kinds 결합 | 영향 LLM 13 전부 | 11 first + 1 revision | 12/13 | 14 | 최종 채택 |

E는 C2 full 결과에서 실제 schema가 달라지는 Core LLM 사례 13개를 모두 동일 입력으로
재생해 교체했다. 따라서 최종 Core 분포는 다음과 같다.

```text
Node input                 43
Deterministic success       9
LLM path target            34
  first-call semantic valid 27  (79.4%)
  revision recovered         1
  failed                     6
Final Node valid           37  (86.0%)
Provider dispatch          39
```

A 대비 첫 호출 semantic valid는 `13 → 27`, 최종 Node valid는 `24 → 37`, provider
dispatch는 `55 → 39`다. E 합성 표본의 관측 토큰은 input `268,580`, output `17,494`다.
표본별 runtime 시점이 다른 latency 합계는 후보 promotion 근거로 사용하지 않았다.

## 최종 failure family

| Family | 수 | 비고 |
| --- | ---: | --- |
| explicit anchor loss | 2 | 한 건은 첫 temporal 실패 뒤 revision에서 anchor가 소실됨 |
| temporal loss | 2 | upstream period 표현이 현재 공통 resolver 범위 밖 |
| over-selection | 1 | 같은 route id를 중복 선택 |
| route mismatch | 1 | LLM dispatch 전 validated container scope 부재 |

Schema-valid이지만 semantic-invalid인 첫 출력은 6개이며, schema-valid를 성공으로 세지
않았다. Semantic revision은 6개에 시도되어 1개만 회복했고 5개는 실패했다.

## Projection 안전성

- `required_user_anchors`는 기존 `RequestIntent.constraints` 중 field allowlist와
  `USER_REQUEST | CONFIRMATION_RESPONSE` provenance를 모두 만족한 값만 전달한다.
- `business_concepts`, 시스템 유래 검색어, 정규식 추측으로 새 anchor를 만들지 않는다.
- `required_route_constraints`는 새 State가 아니라 현재 Run의 검증된 typed intent와
  frozen Calendar route로부터 LLM 호출 직전에 만드는 optional prompt projection이다.
- Calendar temporal projection이 존재하는 route에만 기존 route policy의
  `required_constraint_kinds`를 output schema에 결합한다.
- C의 global binding과 D의 global required-kind binding은 성공 증가와 함께 무관
  요청 회귀를 만들었으므로 채택하지 않았다.

## 결과 위치

원시 JSON은 Git에 넣지 않고 `evaluation/results/` 아래에 보존한다.

- `langgraph-node-replay-retrieval-plan-raw-core60-20260916/result.json`
- `langgraph-node-replay-retrieval-plan-b2-anchor-exact-20260916/result.json`
- `langgraph-node-replay-retrieval-plan-c2-core60-20260916/result.json`
- `langgraph-node-replay-retrieval-plan-e-bounded-required-constraints-20260916/result.json`
- `langgraph-node-replay-retrieval-plan-e-remaining-affected-20260916/result.json`
