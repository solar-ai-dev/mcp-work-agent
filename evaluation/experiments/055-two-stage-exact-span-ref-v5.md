# 055 — isolated request-local exact span ref 비교

Issue: #287

## 범위

`span-bound v3`의 업무 경계 규칙, optional typed 의미, two-stage 호출과 relation 계약을
유지하고 `request_spans` 표현만 바꿨다.

- v3: 모델이 사용자 원문 substring을 다시 생성
- v5: 모델이 request-local token ID 범위를 선택하고 projection이 원문 character
  offset으로 exact substring을 복원

shared/local Source·조건 State는 사용하지 않았다. Identify Prompt의 변경은 위 span
표현 한 줄뿐이고 relation Prompt는 v3와 동일하다. 규칙, few-shot, Node 수, Product
State/Schema/Prompt/Node/Edge는 변경하지 않은 evaluation-only 후보다.

고정 Core 24를 temperature 0, seed 20260920에서 1회 실행했다. Holdout/Stress,
Tool 선택, Query, Retrieval, Provider 연결은 사용하지 않았다.

## 결속

- Product SHA: `5bc9ee8dc85373078f329a8bd91aff1c335a3cb4`
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Canonical authority SHA-256: `958bf846f3abba243f5b1f98f4962e53435a90b4149dc41855f50002a40f2189`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Stage 1 Prompt SHA-256: `a2769b555828b9c8ef90d8f661b1cf2dba3329cfb21f2772bf90fb9cd043ae55`
- Stage 2 Prompt SHA-256: `8cc6f56afed02a76f028c67fffe58273ae0f5365863b7c7c6156e7351bee63cd`
- Raw result SHA-256: `9ce397c3d1cad0ea5c6783aae77f4e7388229c96ed47dc32cd550a0a7dc466f0`
- Review SHA-256: `ac73a2f9ce9e513d04976ac422ed41f20b1c7b7dc1c0c811dacd67f05ec637ea`
- Corrected regrade file SHA-256: `69d7c2997518ba2d8cf720934348a8b83a4aac8857e32812d7cbea54dc565435`
- Provider READ/WRITE: `0/0`
- rerun-to-pass: `0`

## span-bound v3와 비교

| 후보 | PASS | PARTIAL | FAIL | exact span/ref | calls | tokens in/out | latency | 판단 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| span-bound v3 | **14** | **10** | **0** | 19/24 | 48 | 32,604 / 3,561 | 149,908ms | HOLD |
| exact-span-ref v5 | 10 | 13 | 1 | **24/24** | 48 | 42,723 / 3,447 | 148,497ms | **REJECT** |

Identify schema, final schema, deterministic carry는 모두 `24/24`였다. input token은
v3보다 약 31% 증가했고 LLM latency는 약 0.9% 감소했다.

## 확인된 개선

CORE-021/026/037/040/046의 `8 월`, `10 시`, `2 일` 같은 재생성 변형이 모두
사라졌다. exact span/ref는 `19/24 → 24/24`가 됐다. Validator가 유사 문자열을 원문으로
보정하지 않았으며 token ID와 저장된 offset만으로 exact substring을 복원했다.

다만 다섯 Case 모두 다른 의미 문제가 남거나 새로 생겨 PASS 전환은 없었다.

- CORE-021: Atlas를 Event target으로 오분류
- CORE-026: 원문에 없는 `내부 점검 일정 제안 대상` 추가
- CORE-037: 원문에 없는 담당자/시스템 target 유지
- CORE-040: target인 기존 작업·메모를 source scope에도 혼합
- CORE-046: Event와 Draft 결합 및 planned specification relation 누락

## 회귀

v3 PASS였던 CORE-006/020/027/028 네 Case가 PARTIAL로 회귀했다.

| Case | 최초 다른 값 |
| --- | --- |
| CORE-006 | 요청 사실인 `최종 출고일`과 `담당자만`을 temporal/quantity constraint로 오분류 |
| CORE-020 | Source 확인 구절 전체를 temporal constraint로 오분류 |
| CORE-027 | 응답 구절을 quantity로, 요청자를 target으로 오분류 |
| CORE-028 | 원문에 없는 `prohibition=없음` 추가 |

CORE-001은 검색 금지를 별도 WorkUnit으로 승격했다. CORE-048은 가장 큰 회귀다.

- 두 WorkUnit 모두에서 `Kestrel` identity가 사라졌다.
- Event 구절에는 `준비` 동작이 결속되지 않아 요청 결과 하나가 불완전해졌다.
- Task/Event 묶음과 Draft 사이에 Canonical 근거가 없는
  `CONSUMES_WORK_PRODUCT` relation을 추가했다.

CORE-050도 span 시작에서 `Echo` identity를 누락했다.

## 최초 divergence와 판단

Projection은 선택된 token ID를 모두 정확히 원문으로 복원했다. 최초 divergence는 그
이전 Stage 1 LLM candidate다. request token catalog와 동적 span-ref schema가 추가되자
업무 경계 및 기존 optional field의 값도 v3와 다르게 생성됐다. 즉 shared State를 제거해도
현재 한 호출에서 span 선택과 optional typed 의미 생성을 함께 수행하는 한 exact binding
representation이 다른 의미 축에 대해 중립적이지 않았다.

`exact-span-ref v5`는 **REJECT**한다.

- request-local ref의 exactness 효과는 재확인됐다.
- 그러나 v3 대비 PASS/FAIL과 의미 보존을 회귀시키므로 이 후보 전체를 채택하지 않는다.
- Production flat baseline과 decomposition 비교 기준 `span-bound v3`를 유지한다.
- WorkUnit 표현이 안정됐다는 종료 조건을 충족하지 못했으므로 typed relation 실험으로
  넘어가지 않는다.
