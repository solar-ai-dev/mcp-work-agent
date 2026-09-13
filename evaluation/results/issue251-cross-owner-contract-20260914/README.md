# Issue 251 cross-owner contract 정리

- 브랜치: `codex/issue-251-connected-contract`
- Start HEAD: `ea0169d3000c672cec38394b071828066a089d37`
- Product Final SHA: `34e147312a4b0fd9ad653c0ad4443a8f1a8cba69`
- 기준 모델: `qwen3.5:9b`
- 모델 digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature / seed: `0.0` / `null`
- 자동 LangSmith tracing: 비활성

## 수정한 contract class

| Contract class | 문제 producer | 문제 consumer | 수정 owner | 변경 |
| --- | --- | --- | --- | --- |
| confirmation propagation | target confirmation resume | 후속 source dependency 판단 | Request Understanding | stable identity가 없고 prior source가 비었을 때만 기존 `identify_source_dependencies`를 재사용하고, goal/output/status/provenance는 보존 |
| derived state recomputation | resource responsibilities | hints 및 `required_information` constraint | Request Understanding | responsibility 변경 뒤 기존 canonical derivation으로 effect/resource hint와 source information 재생성 |
| semantic vs dependency route | registry dependency expansion | Retrieval completeness | Tool Routing | route reason code 기반 단일 dependency 분류 helper 제공; route와 `required=True`는 유지 |
| sufficiency accounting | required tool routes | Sufficiency 및 read-evidence gate | Retrieval | business-required source projection을 공통 사용해 execution dependency를 Evidence completeness에서 제외 |
| 추가 발견 결함 | 새 responsibility | stale `required_information` constraint | Request Understanding | 이전 source 정보가 남지 않도록 현재 responsibility에서 owner-local 재생성 |

Prompt, Schema, 전역 State, Graph Node/Edge는 변경하지 않았고 새 LLM 호출도 추가하지 않았다. dependency route의 실행 prerequisite 의미, semantic source 미완료 fail-closed, Juniper EXHAUSTIVE coverage, q19 detail-first, Atlas/Quartz planning 경계를 유지했다.

## 직접 검증

- 관련 pytest: `391 passed`
- Ruff: 통과
- mypy: 변경 production source 4개 통과
- 필수 matrix: confirmation propagation, stable identity, Calendar/Task/Gmail/Freebusy dependency accounting, EXHAUSTIVE gate, q19 detail-first, Atlas source, Quartz exact update를 포함

## Calendar Gate 단발 결과

| 항목 | 결과 |
| --- | --- |
| Domain Run | `3492909d-bea9-4988-b9e8-f2ee3d47a9ec` |
| 최초 요청 | `WAITING_CONFIRMATION` |
| 같은 Run confirmation | `프로젝트 검토 회의`, 1회 |
| Connector READ | 23 |
| Evidence draft | 0 |
| terminal | `BLOCKED` |
| reason | `RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID` |
| 제품 판정 | **FAIL** |

조건에 따라 Calendar를 재실행하지 않았고 최종 6 Smoke도 실행하지 않았다. 승인, action, execution attempt, Provider WRITE/SEND는 모두 0이다.

## 이전 Run과의 최초 divergence

비교 대상:

- 이전 answer-producing resume Trace: `01a09cb0-7fe8-7ff2-9b04-bf819d5b7928`
- 이번 failed resume Trace: `01a09cc7-f2d3-7e92-84db-882a1d52c48f`
- 이전 initial Trace: `01a09cb0-1347-7c73-ad7b-dd6ca9ab9a31`
- 이번 initial Trace: `01a09cc7-8394-7591-a1af-75f34026afdf`

최초 차이는 Retrieval/Sufficiency가 아니라 initial Request Understanding의 `identify_source_dependencies` LLM structured output이다.

- 두 initial 호출의 safe semantic input SHA-256: `af30f5bd640161a385c2e8f9c9259f6ebea2d9bbc03d060f9874718e932290cb`로 동일
- 모델, Prompt `request_understanding.identify_source_dependencies@1.0.2`, Prompt hash `92c90bd0370f91a9ce79ac59ce32a1a502795a89206a4a79c72d41aa4b8c1b24`, output schema가 동일
- 이전 output: `CALENDAR_EVENT = SOURCE_REQUIRED`, required information 2개
- 이번 output: 모든 source `SOURCE_NOT_REQUIRED`

분류는 **A. 동일 input / LLM output variance**다. 이번 Run은 confirmation resume에서 기존 계약대로 source dependency를 재평가해 `CALENDAR_EVENT`를 복구했지만, 후속 query plan은 `CONTAINER_REF`만 사용했다. 그 결과 이전 `segments/RAG/Evidence = 2/2/2`와 달리 이번에는 `60/24/0`이 되었고, 추가 query가 semantic validator에서 차단됐다.

이는 이번 dependency accounting 수정 전의 upstream divergence다. lexical trigger, Prompt 규칙, validator 완화, retry/budget 증가 없이 deterministic하게 한쪽 LLM 의미를 강제하려면 새로운 제품 정책이 필요하므로 추가 제품 수정은 하지 않았다.

## LangSmith / 안전성

- 이번 initial Trace: root/node/LLM/tool `1/6/6/0`
- 이번 resume Trace: root/node/LLM/tool `1/31/5/23`, 오류 span 3
- root → node → LLM/tool span 생성 확인
- rerun-to-pass: `0`
- Provider WRITE/SEND: `0`
- 승인/action/execution attempt: `0/0/0`
- 비밀키, OAuth token, 메일/일정 원문은 기록하지 않음
