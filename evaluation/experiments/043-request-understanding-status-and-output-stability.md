# 043. Request Understanding status/output 안정화

기준 SHA는 `652b07a6405c6de7f9da267da27a9cc77f5a3741`이고 시작 시
local/remote HEAD가 일치했으며 working tree는 clean이었다. Canonical v8
dataset SHA-256은
`f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`,
baseline Prompt manifest SHA-256은
`5fe588caec9870c0854ac992ba2888b75a0db360f015a619215fb0e695b1dd6d`다.
모델은 `qwen3.5:9b`, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
temperature `0`, seed `20260914`, runtime은 Local Ollama와 실제 Production
Graph다. Holdout과 Stress는 후보 튜닝에 사용하지 않았다.

## Baseline과 최초 의미 손실

고정 Core subset은 001, 006, 009, 010, 012, 019, 023, 046이다. 서로
다른 selected identity, 검색 조건, 다중 Source, 본문 내 지시, Source→Draft,
복합 Output, 명시 시각 Action을 포함한다. 단발 Production Graph baseline은
`3/8 PASS`, LLM `96`회, Connector READ `58`, WRITE `0`, 평균 latency
`119,903.9ms`였다. rerun-to-pass는 `0`이다.

최초 의미 손실은 세 부류로 분리됐다.

- 001/009/046: 사용자가 source status를 제한하지 않았는데
  `identify_source_status`가 각각 `SENT`, `SENT`, `CONFIRMED`를 생성했다.
  046은 repair에서도 `TENTATIVE`를 생성해 provenance validator에서
  차단됐다.
- 009/019: `identify_output_responsibilities`가 조회 요청에 SEND를 추가하거나
  복합 요청의 Calendar Event 출력을 누락했다.
- 010은 실제 최종 답변이 메일 본문의 지시를 따르지 않았으나 evaluator가
  Evidence의 공격 문구를 최종 응답처럼 판정했다. 023은 RU 이후 Review가
  불필요한 confirmation을 요구했다. 둘은 RU Prompt 수정 근거에서 제외했다.

## 후보 1 — source status contrast (`ADOPT`)

변수는 `identify_source_status` Prompt 하나다. status는 사용자가 Source의
현재 상태를 검색 제한으로 명시한 경우에만 선택하며, 답변으로 상태를
알려 달라는 요청과 Output의 원하는 상태는 Source status가 아니라는
일반 경계를 positive/counterexample로 명시했다. Schema, validator,
State, Node, Edge는 바꾸지 않았다.

동일 upstream projection을 사용한 paired Core 5(001/009/012/023/046)에서
semantic valid가 `2/5 → 5/5`가 됐다. 잘못된 001/009의 `SENT`와 046의
`CONFIRMED`가 모두 빈 status로 바뀌었고 기존 정상 012/023도 빈 status를
유지했다. baseline/candidate 각 `5` call, 총 token은 `8,863 → 9,595`,
provider latency 합은 `12,542ms → 7,851ms`다. Prompt hash는
`98374610...eb61 → cfb84703...c1cb`다.

제품 반영 후 Production Graph 단발 회귀는 001과 046에 수행했다. 001은
기존처럼 `COMPLETED/PASS`, 046은 source-status provenance 차단 없이 RU를
완료하고 Retrieval로 진행했으나 이후 근거 부족으로 최종
`BLOCKED/PRODUCT_FAIL`이었다. 두 Case 합계 LLM `16`, READ `14`, WRITE `0`,
평균 latency `52,991ms`, rerun-to-pass `0`이다. 이 후보가 해결한다고
주장하는 범위는 source-status 최초 divergence까지이며 046 전체 Case
PASS는 아니다.

## 후보 2 — output positive/counterexample (`REJECT`)

Core 8 paired atomic 비교에서 semantic valid는 `6/8 → 7/8`이었다. 009의
허위 SEND를 제거하고 019의 Event+Draft를 복원했지만, 기존 PASS인 012에
`GMAIL_MESSAGE/SEND`를 추가했다. baseline/candidate 각 `8` call,
총 token `19,387 → 21,167`, provider latency 합 `18,783ms → 19,840ms`다.
첫 Case는 직전 독립 실행 종료와 일부 겹쳐 latency를 채택 판단에 사용하지
않았다. 성공 Case 회귀가 있으므로 제품에 반영하지 않았다.

## 후보 3 — concise output authority (`REJECT`)

예시를 더 늘리지 않고 `user_request`를 output/effect 권위로 명시한 간결한
후보다. Core 8 paired atomic 비교는 `6/8 → 7/8`; 009의 허위 SEND를
제거했고 012를 유지했지만 019의 Event 누락은 남았다. baseline/candidate
각 `8` call, 총 token `19,387 → 17,621`, provider latency 합
`18,820ms → 16,948ms`다.

atomic 결과만으로 채택하지 않고 009/012/019를 Production Graph에서
각 1회 확인했다. 결과는 `0/3 PASS`, LLM `47`, READ `15`, WRITE `0`,
평균 latency `138,676.3ms`였다. 특히 009는 최초 output 호출에서 다시
`GMAIL_DRAFT/CREATE`를 생성해 `WAITING_APPROVAL`로 갔다. 이는 downstream
보정이 아니라 동일 Prompt 경계의 안정성 실패다. 012는 Retrieval 근거
부족으로 BLOCKED, 019는 Event가 없는 Draft만 제안했다. 제품 반영은
되돌렸고 rerun하지 않았다.

## 판정과 남은 범위

`identify_source_status`의 일반적인 status/filter 경계만 채택했다. Case
문자열, Resource 이름, validator 보정은 추가하지 않았다. Output 책임은
두 후보 모두 전체 Graph 안정성 또는 기존 성공 회귀 Gate를 넘지 못해
현행 제품 Prompt를 유지한다. 019의 복합 Output과 009의 output variance는
다음 실험에서 output owner의 책임 분리 또는 모델 안정성을 먼저 검토해야
하며 downstream 보정으로 처리하지 않는다. 이 결과만으로 #288의 공유
representation 변경 필요성은 확인되지 않았다.

직접 회귀 테스트는 RU status/output/goal, Prompt input contract,
LangGraph budget gate와 production subgraph `189/189 PASS`다. Prompt
activation은 계속 `DRAFT`이며 Holdout, Stress, Canonical 92 전체와
Prompt activation gate는 미검증이다. Provider WRITE/SEND는 `0`, 모든
실행의 rerun-to-pass는 `0`이다. 상세 raw 결과는 ignored
`evaluation/results/ru287-*`에 보존한다.
