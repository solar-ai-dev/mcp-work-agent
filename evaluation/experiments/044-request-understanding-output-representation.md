# 044. Request Understanding Output representation 비교

기준 Product commit은 `938bee091473d13139ec58bc24e16f66538ff4d0`이고
Canonical v8 dataset SHA-256은
`f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`다.
모델은 `qwen3.5:9b`, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
temperature `0`, seed `20260914`다. 모든 비교는 Canonical Core 입력과 Local
Ollama만 사용했고 Provider READ/WRITE는 `0`이다. Holdout과 Stress는 튜닝에
사용하지 않았다.

## 실패 signature와 안정성

현재 flat `RequestIntentV2`의 최초 잔여 divergence는
`identify_output_responsibilities`다. 조회 요청인 CORE-009가 Message SEND로
과선택되고, 복합 요청인 CORE-019는 Event CREATE를 누락한다. 같은 요청 객체와
동일 Prompt/model/seed를 고정한 3회 안정성 측정에서 CORE-009/019는 각각
`0/3`, 정상 대조군 CORE-037/059는 각각 `3/3`이었다. Case별 prompt input과
goal candidate hash는 세 Trial 모두 하나였으므로 rerun variance가 아니라 재현 가능한
consumer 판정 오류다. 총 `36` LLM call, `78,747` token, provider latency 합
`123,325ms`, rerun-to-pass `0`이다.

시간 의미가 필요한 Case만 Dataset의 fixed `run_reference_time`을 사용하고 나머지는
현재 Run 시각을 사용하는 Canonical 계약도 확인했다. Output projection에서 시각만
제거한 후보는 Core 12에서 `11/12 → 10/12`로 악화되어 시각 필드 단독 원인은
아니었다.

## 후보 비교

| 후보 | 범위 | baseline → candidate | call 변화 | 판정 |
| --- | ---: | ---: | ---: | --- |
| goal projection 제거 | Core 21 | 19/21 → 19/21 | 21 → 21 | CORE-019 개선과 CORE-035 회귀가 교환되어 REJECT |
| bounded goal projection | Core 21 | 20/21 → 19/21 | 21 → 21 | CORE-009 회귀, CORE-019 잔여로 REJECT |
| Resource별 분해 | Core 8 | 6/8 → 2/8 | 8 → 40 | 단일 후보 노출을 요청으로 오인하여 REJECT |
| explicit REQUESTED/NOT_REQUESTED | Core 8 | 7/8 → 6/8 | 8 → 8 | 019 개선, read-only 009/010 회귀로 REJECT |
| change gate → explicit disposition | Core 23 | 22/23 → 20/23 | 23 → 39 | Task/Event/Draft mapping 회귀와 비용 증가로 REJECT |
| exact Output provenance span | Core 12 | 10/12 → 6/12 | 12 → 12 | exact span 존재가 Source/Output 의미를 보증하지 못해 REJECT |
| Output에서 reference time 제외 | Core 12 | 11/12 → 10/12 | 12 → 12 | 009 회귀와 019 잔여로 REJECT |
| change span 추출 → mapping | Core 12 | 11/12 → 9/12 | 12 → 21 | 019 개선 대신 006/035/037 회귀로 REJECT |
| WorkUnit/WorkRelation v1 | Core 12 | 11/12 → 10/12 | 12 → 12 | 019 개선, 023/037 누락으로 REJECT |
| WorkUnit + contrastive boundary | Core 23 | 22/23 → 22/23 | 23 → 23 | 실패가 019에서 059로 이동해 REJECT |

WorkUnit contrast 후보의 총 token은 `56,156 → 80,171`, provider latency 합은
`43,403ms → 167,254ms`였다. Source→Output 관계가 필요한 요청을 포함했지만 relation은
23개 중 1개 Case에서만 생성됐고 일부 Source Resource도 잘못 분류됐다. 따라서
output pair 한 축의 일시적 개선을 근거로 `WorkUnit[]/WorkRelation[]`을 공유
Runtime contract로 승격할 수 없다. #288 shared ownership 변경은
`NOT YET JUSTIFIED`다.

첫 two-stage gate 실행은 Prompt input contract 필수 필드 누락으로 모델 호출 전
중단됐고, 필드를 보존한 새 결과 경로에서 정식 비교했다. 이 중단은 Trial이나
성능 결과로 세지 않았다. 모든 결과 파일은 별도 경로에 보존했고 기존 결과를
덮어쓰지 않았다.

## Decision

현재 output Prompt/Schema/State/Node/Edge는 유지한다. 비교한 Prompt, projection,
two-stage, WorkUnit 후보는 어느 것도 여러 Resource 유형에서 baseline을 넘고 회귀를
피하지 못했다. 잔여 CORE-009/019 output 오류는 `HOLD`이며 downstream 보정이나
validator 의미 생성으로 숨기지 않는다. 더 많은 Case 예시를 Prompt에 누적하거나
shared contract를 바꾸지 않는다.

043에서 채택한 source-status 경계 수정은 그대로 유지한다. 이번 단계의 production
변경은 `0`, Provider WRITE/SEND는 `0`, rerun-to-pass는 `0`이다. Raw paired 결과는
ignored `evaluation/results/ru287-*` 아래에 보존한다.
