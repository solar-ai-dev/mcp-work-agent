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

## Stress / Holdout 최종 후보 확인

동일한 최종 후보를 저장된 Node 입력으로 별도 재생했다. 노출된 Holdout은 독립 검증으로
주장하지 않는다.

| Split | Node 입력 | deterministic | LLM 대상/dispatch | 첫 호출 semantic valid | revision 회복/실패 | 최종 valid | 호출 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Stress 20 | 14 | 0 | 14/14 | 12/14 | 1/1 | 13/14 | 16 |
| Holdout 12 | 3 | 1 | 2/2 | 1/2 | 0/1 | 2/3 | 3 |

Stress의 잔여 실패는 over-selection 1건, Holdout의 잔여 실패는 explicit anchor loss
1건이다. Stress 관측량은 input `82,584`, output `5,418`, provider latency
`164,657ms`; Holdout은 input `12,680`, output `645`, provider latency
`20,470ms`다.

- `langgraph-node-replay-retrieval-plan-final-stress20-20260916/result.json`
- `langgraph-node-replay-retrieval-plan-final-holdout12-20260916/result.json`

## 후속 비교: Query → Evidence 경계 (2026-09-16)

목표는 초기 Gmail 검색의 `ANY` 강제를 없애되 검증된 exact literal의 provenance를
유지하고, Calendar 기간·시각을 소유 route가 불명확한 상태에서 확정하지 않으며,
합성 Gmail 검색 Preview가 본문 상세를 대체하지 않게 하는 것이다. 특정 Case 문구로
검색어·기간을 보정하지 않는다. 기준 SHA는
`c254b1a0762e959fd0e57e7ab50d77277aac6b2a`, 후보의 제품·평가 코드 patch-id는
`c4d0b1ac72f365944460bfa43e819fe58f7792ca`다.

고정 Core 60 Node 재생은 위와 같은 checkpoint corpus, 9B digest, temperature 0,
seed 1729를 사용했다. 실제 Connector는 실행하지 않았다.

| 비교 | 기준 | 후보 |
| --- | ---: | ---: |
| Node 입력 / deterministic / LLM 대상 / dispatch | 43 / 9 / 34 / 33 | 동일 |
| 첫 호출 schema + semantic valid | 29/34 | 30/34 |
| 최종 Node valid | 38/43 | 40/43 |
| Provider 호출 | 37 | 36 |
| 입력 / 출력 토큰 | 255,833 / 18,042 | 255,108 / 17,864 |
| 관측 Provider 지연 합계 | 504,888ms | 572,292ms |

같은 Case의 변화는 CORE-029·048 실패→첫 호출 유효, CORE-036 첫 호출 유효→Schema
repair 유효였다. 잔여 실패는 FREEBUSY temporal loss 2건과 LLM dispatch 이전의
validated container scope 부재 1건이다. 지연은 개선되지 않았으며 실행 시점 영향도
분리되지 않아 성능 개선으로 주장하지 않는다.

비교 전 정한 반례·성공 포함 6건(`006/024/029/036/048/058`)을 재부팅 후 같은
설정으로 2회 직렬 반복했다. 두 Trial 모두 첫 호출 4/6, 최종 4/6,
Provider 호출 8회였다. `006/024/029/048`은 양쪽 유효, `036`은 양쪽 Schema
repair 실패, `058`은 양쪽 semantic revision 후 temporal loss였다. 전체 Core
1회와 반복 2회의 `024/036` 결과가 달라 단일 Core PASS를 안정화 근거로 쓰지
않는다. 재부팅 전후 Ollama 환경이 같았는지도 확인되지 않았다.

합성 Query→Evidence 연결은 고정 저장 RU·Route에서 `006/008/055`를 실행했다.
검색은 본문을 index할 수 있지만 Fixture에 명시 snippet이 없으면 Preview에는 본문을
복사하지 않는다. 변경 후 `006/055`는 상세 GET까지 진행해 필요한 Evidence를 얻었고,
`008`은 저장된 RU가 여러 의미를 한 exact search term으로 묶어 첫 검색이 0건이었다.
이는 최신 RU를 다시 실행한 결과가 아니다. `015`의 저장된 RU에는 요청된 Task source가
빠져 있었고 후속 Query는 Schema repair에 실패했다. `021`은 검색·목록·FREEBUSY
READ 후 `retrieval_result` 없이 FINALIZE로 이동했다. WRITE는 0이었다.

연결 평가기는 Retrieval만 실행하면서 Action Gold의 실제 생성 여부까지 판정해
`021`에 허위 업무 실패를 부여했다. 후속 평가에서는 downstream output이 있는
요청의 최종 업무 성공을 `미평가`로 두고, `retrieval_result` 부재를 별도 결과로
표시한다. 재부팅 중 중단된 Calendar Trial의 JSON은 손상되어 결과 집계에서 제외하며
PASS로 재분류하지 않는다. 합성 READ와 실제 Provider READ도 동일 근거로 보지 않는다.

| 실패 유형 | 시도 방법·조건 | 결과·회귀 | 판정·재시도 조건 |
| --- | --- | --- | --- |
| exact anchor 누락·초기 과소 검색 | 검증 literal은 유지하고 `match_mode`는 의미에 따라 선택 | Core 첫 호출 +1, 최종 +2; 연결 READ 2/3 유지 | 잠정 채택. 반복 분포·실제 Provider 확인 필요 |
| Calendar 시각의 잘못된 route binding | 단일 확정 날짜만 결합, 복수 temporal 또는 비-Calendar source가 있으면 시각 소유를 강제하지 않음 | 직접 계약 테스트 통과; 저장 92 입력에는 `start_time/end_time` 쌍이 없어 실제 영향 미관측 | 안전 경계 채택, RU의 시간 관계 손실은 별도 조사 |
| Preview에 본문 상세 노출 | 명시 snippet만 노출하고 본문은 상세 GET | 짧은 본문 반례 테스트 통과, 연결 READ 2/3 유지 | 합성 harness 채택; 실제 Provider 경계 미검증 |
| 복합 Schema·시간 손실 | Prompt 지시만 추가 | `036/058` 반복 실패, `024` 실행 간 변동 | 동일 Prompt 덧붙이기 중단; upstream 의미·output 부담·repair 경계 재진단 |

원시 결과는 `evaluation/results/`의
`langgraph-node-replay-retrieval-plan-g-initial-recall-core60-20260916`,
`langgraph-node-replay-retrieval-plan-exact-anchor-free-mode-core60-20260916`,
`langgraph-node-replay-retrieval-boundary-repeat1-20260916`,
`langgraph-node-replay-retrieval-boundary-repeat2-20260916`,
`query-evidence-connected-no-body-fallback-20260916`,
`query-evidence-connected-calendar-boundary-20260916`,
`query-evidence-connected-calendar-stage-after-reboot-20260916`에 있다.
실제 Provider READ, Stress/Holdout 최신 후보, 후속·revision·confirmation resume,
전 Node 안정화는 아직 검증하지 않았다.
