# 062 — Request Understanding semantic authority 구조 후보

Issues: #287 / #288

## 결론

061의 수정 판정 `32 PASS / 3 PARTIAL / 57 FAIL`을 기준선으로 삼아, 실제
`qwen3.5:9b`와 compiled Request Understanding → Tool Route에서 evaluation-only
후보를 비교했다. 가장 나은 후보는 WorkUnit의 원문 결속을 token range로 선택하고,
Goal과 사용자 결과 모달리티 및 Output을 한 semantic authority에서 생성한
`ru-goal-output-modality-authority-v4`였다.

| 범위 | 061 기준선 | v4 후보 | PASS 변화 |
| --- | ---: | ---: | ---: |
| CORE 60 | 17 / 2 / 41 | 35 / 1 / 24 | +18 |
| HOLDOUT 12 | 6 / 1 / 5 | 7 / 0 / 5 | +1 |
| STRESS 20 | 9 / 0 / 11 | 11 / 0 / 9 | +2 |
| **전체 92** | **32 / 3 / 57** | **53 / 1 / 38** | **+21** |

표의 값은 `PASS / PARTIAL / FAIL`이다. 엄격 성공률은 `34.8% → 57.6%`,
PASS+PARTIAL은 `38.0% → 58.7%`로 증가했다. Graph 예외 없이 끝난 Case는
`72 → 80`, Route가 생성된 Case는 `69 → 77`이었다.

그러나 기준선 PASS 9건이 FAIL로 회귀했고, Source 누락/계약 실패가 28건 남았다.
따라서 최종 판단은 **HOLD**다. 결과 모달리티와 Output을 같은 의미 판단에 두는 구조는
유효하지만, 이 후보를 그대로 Production에 적용하지 않는다.

이번 결과는 RU → Tool Route 의미 판정이다. Retrieval → Planning, Provider 실행,
STRESS fault recovery 또는 E2E 성공으로 승계하지 않는다.

## 비교 결속

- 기준 Product source SHA: `50ff0879c1cbdbdde0fd0b6969c664e9670b2404`
- 후보 실행 SHA: `7056682a4aa755aec05e1d50e8292e9992d4769f`
- 두 SHA 사이 Product source 변경: `0` (평가 runner/test/report만 변경)
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Fixture SHA-256: `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`
- Prompt manifest SHA-256: `29161dcc93325b50655571c91b7e7cebc0eac07214f4617216ba541009ed2ea9`
- Model/digest: `qwen3.5:9b` /
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Temperature/seed: `0.0 / 20260923`
- Provider READ/WRITE/SEND: `0 / 0 / 0`

Core 후보 선택은 사전에 고정한 성공·실패·반례 21개를 Case당 2회 실행했다.
Holdout/Stress는 후보 수정에 사용하지 않고, v4 고정 뒤 Canonical 92 단발에서만
확인했다. 실패 Trial을 성공 Trial로 대체하지 않았다.

## 구조 후보와 선택 과정

### v2 — Goal + prohibition + Source + Output 원자화: REJECT

한 호출이 모든 의미 owner를 대신하게 했더니 Source 후보가 과선택되고,
`CALENDAR_EVENT`가 표현할 수 있는 9개 fact kind와 Product schema의 `maxItems=8`이
충돌했다. 단순 READ에 모든 WRITE를 붙이는 preflight 회귀도 있었다. 서로 다른
전문 책임까지 하나의 호출로 합치는 축은 폐기했다.

### v3 — Goal + Output authority: 개선, 그러나 HOLD

Source와 prohibition은 기존 owner에 남기고 Goal → Output의 중복 재해석만 제거했다.
Core 21 두 Trial 모두 `13 PASS / 1 PARTIAL / 7 FAIL`이었다. Draft와 SEND 혼동은
줄었지만 CORE-004/009/051 같은 READ를 외부 변경으로 해석하는 오류가 남았다.

### v4 — Goal + result modality + Output authority: 최종 후보

`ANSWER_ONLY`와 `EXTERNAL_CHANGE`를 Goal/Output과 같은 호출에서 선택하고 schema가
빈 Output/외부 Output의 일관성만 검증한다. 어떤 결과가 맞는지는 모델이 선택하며,
Case 명사·표현별 규칙은 없다.

Core 21 결과는 다음과 같다.

| 비교 | PASS | PARTIAL | FAIL | 오류 | Route | calls | input | output | latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 061 기준선 | 7 | 2 | 12 | 3 | 18 | 145 | 366,593 | 13,506 | 851,616 |
| v4 Trial 1 | 15 | 1 | 5 | 0 | 21 | 135 | 326,459 | 16,715 | 746,680 |
| v4 Trial 2 | 14 | 1 | 6 | 1 | 20 | 136 | 333,915 | 17,242 | 772,324 |

Trial 2의 추가 실패 CORE-037은 후보 Output이 아니라 기존 Source-status provenance
revision에서 발생했다. 두 Trial 모두 기준선 PASS 7건은 유지했다.

### v5 — 후보 목록을 감춘 result-mode-first: REJECT

Registry Output 후보를 보기 전에 결과 모달리티를 선결정하면 CORE-009는 고쳐졌지만,
명시적 Draft/SEND 요청인 CORE-012/059도 `ANSWER_ONLY`로 낮췄다. 5개 반례에서
`3 PASS / 0 PARTIAL / 2 FAIL`이었다. 후보 affordance 오염은 일부 원인이지만,
맥락 없이 모달리티를 먼저 닫는 구조도 채택하지 않는다.

## Canonical 92 판정

### CORE

- PASS(35): 001, 002, 003, 004, 005, 006, 007, 008, 010, 011, 012,
  015, 016, 017, 018, 020, 021, 022, 028, 029, 030, 031, 033, 035,
  037, 040, 043, 047, 050, 051, 052, 054, 055, 059, 060
- PARTIAL(1): 056 (`실행하지 마`가 SEND prohibition만 보존됨)
- FAIL(24): 009, 013, 014, 019, 023, 024, 025, 026, 027, 032, 034,
  036, 038, 039, 041, 042, 044, 045, 046, 048, 049, 053, 057, 058

### HOLDOUT

- PASS(7): 001, 002, 003, 004, 005, 006, 011
- FAIL(5): 007, 008, 009, 010, 012

### STRESS

- PASS(11): 002, 003, 008, 010, 011, 014, 015, 016, 017, 018, 019
- FAIL(9): 001, 004, 005, 006, 007, 009, 012, 013, 020

Stress 판정은 fault 주입 전 RU/Route 의미만 본다. 실제 fault recovery 성공을 뜻하지
않는다.

## 해결된 실패군

기준선 FAIL에서 후보 PASS로 바뀐 30건은 다음과 같다.

- CORE(21): 004, 011, 012, 016, 017, 018, 020, 021, 028, 029, 030,
  031, 033, 035, 037, 040, 043, 050, 051, 052, 060
- HOLDOUT(1): 004
- STRESS(8): 002, 011, 014, 015, 016, 017, 018, 019

주요 효과는 다음과 같다.

- 불필요 WRITE 의미 실패: 기준선 22건에서 후보 2건(CORE-009/042)으로 감소
- Draft CREATE와 SEND 분리: CORE-011/012/054/059에서 보존
- Goal 시간/Effect 변형 감소: CORE-030/035/060 등 복구
- exact span 문자열 재생성 제거: 모델은 token range만 선택하고 실제 substring은
  deterministic하게 materialize
- Output owner는 Goal 의미를 다시 생성하지 않고 같은 호출의 Output을 소비

## 회귀와 남은 실패군

기준선 PASS → 후보 FAIL 회귀는 9건이다.

- CORE-025/045/058: 필요한 Calendar availability/Event Source를 잃음
- STRESS-001/004/005/006/007/009: 필요한 Source를 잃거나 모두 비워 계약 차단

기준선 PARTIAL → 후보 FAIL은 CORE-027과 HOLDOUT-008이다. 둘 다 안전한
read-only 의미 일부가 남았지만 필요한 Source를 잃었다.

후보의 38 FAIL 최초 경계는 다음처럼 분류했다.

| 실패군 | 건수 | 대표 Case | 최초 차이 |
| --- | ---: | --- | --- |
| Source 누락/Source-status 계약 | 28 | CORE-013/045, STRESS-001/009 | Goal 표현 뒤 Source owner가 입력 역할을 누락하거나 전부 비움 |
| 결과 모달리티/Output identity | 6 | CORE-009/032/038/042, HOLDOUT-009/010 | 입력 Resource를 결과로 승격하거나 요청 결과를 누락/다른 Resource로 변경 |
| 시간·필수 확인 손실 | 2 | CORE-024/053 | 시작/소요시간을 합치거나 missing duration 확인 없이 Route 진행 |
| 표현 불가/중복 계약 | 2 | HOLDOUT-007/012 | 같은 effect의 독립 Draft 2개, 지원하지 않는 Gmail DELETE 의도를 현재 schema가 표현 못함 |

HOLDOUT-007은 첫 출력과 repair 모두 duplicate Output을 한 WorkUnit에 결속해
`uniqueItems`를 통과하지 못했다. HOLDOUT-012는 사용자의 DELETE 의도를 Registry가
허용한 SEND enum 안에 넣을 수 없어 repair 후에도 실패했다. 지원하지 않는 요청도 RU가
의도로 보존한 뒤 Tool Route/Policy가 거절할 수 있어야 하므로, Registry capability를 RU
표현 가능 범위로 쓰는 현재 계약은 #288 검토 대상이다.

## 첫 출력과 repair

v4 Canonical 92에서 후보 schema repair는 3건이었다.

- HOLDOUT-005: 첫 출력은 `EXTERNAL_CHANGE`인데 Output이 비어 schema 실패;
  1회 repair로 Calendar Event UPDATE를 복구
- HOLDOUT-007: repair 후에도 duplicate Draft Output 실패
- HOLDOUT-012: repair 후에도 허용되지 않는 Gmail DELETE effect 실패

나머지 후보 출력은 first-pass schema valid였다. 기존 Product Source/status revision은
후보 repair와 별도로 raw의 atomic input/output에 보존했다.

## 호출·토큰·지연

| Canonical 92 | 061 기준선 | v4 후보 | 변화 |
| --- | ---: | ---: | ---: |
| 실제 LLM calls | 607 | 575 | -32 (-5.3%) |
| input tokens | 1,545,043 | 1,410,689 | -134,354 (-8.7%) |
| output tokens | 58,313 | 73,892 | +15,579 (+26.7%) |
| reported latency | 3,357,449ms | 3,261,362ms | -96,087ms (-2.9%) |

Output 재해석 호출을 cache projection으로 제거해 call/input은 감소했지만, 결합 schema의
출력이 길어져 output token이 증가했다. 지연 개선은 작으므로 성능만으로 채택할 수 없다.

## Raw 근거

로컬 raw는 ignore 정책에 따라 버전관리하지 않고 아래 경로와 hash로 결속한다.

| 실행 | 경로 | SHA-256 |
| --- | --- | --- |
| 061 기준선 | `evaluation/results/ru-tool-route-canonical92-20260924-50ff0879/raw.json` | `2ee8b74d4c175b96ad70c0eb1456955c7c861d1bf9d1c6d8cb62853af2eb0460` |
| v3 Core21 T1 | `evaluation/results/ru-goal-output-v3-core21-trial1-20260924/raw.json` | `7370e650c4c7d69d52d712a2046be6a93bbfc3f72989b6538d03472d63e32aca` |
| v3 Core21 T2 | `evaluation/results/ru-goal-output-v3-core21-trial2-20260924/raw.json` | `9180baf44632a76ab03aa9122685a4673ed3c9652ead51b97a3736832daaed7b` |
| v4 Core21 T1 | `evaluation/results/ru-goal-output-modality-v4-core21-trial1-20260924/raw.json` | `922c6ee2cfa476ced30aa857ce625d6b30b2a9219f342490001c1a15d6a1ae76` |
| v4 Core21 T2 | `evaluation/results/ru-goal-output-modality-v4-core21-trial2-20260924/raw.json` | `c875331c7bca356842ec3fc0de03e9c77b76133536092e69a637c9166ce8c2e9` |
| v4 Canonical92 | `evaluation/results/ru-goal-output-modality-v4-canonical92-trial1-20260924/raw.json` | `c5dac5ee0c1e6ebea6b4b71c7a3ca5a670d8004b40603e49f800708c5770ef5f` |
| v5 preflight | `evaluation/results/ru-result-mode-first-v5-preflight-20260924/raw.json` | `0d2af439f5532c71dfb09b1229818932ec1db084a1196e859bbd4555b36fed28` |

## #288 후속 구조 범위

추가 Prompt patch보다 ownership/handoff 검토가 먼저다.

1. v4의 `requested_result_mode + requested_outputs` 일관성은 유지한다.
2. Source owner가 생성형 Goal 문장을 semantic authority로 재해석하지 않도록,
   WorkUnit의 원문 provenance와 item-owned `work_unit_ids`를 직접 소비하는 입력 계약을
   검토한다. Source 문자열을 WorkUnit에 복제하거나 shared/local category를 만들지 않는다.
3. RU의 requested Output intent와 현재 Registry의 executable capability를 분리한다.
   지원하지 않는 intent도 보존하고 Tool Route/Policy가 typed rejection을 소유하게 한다.
4. 같은 Resource/effect의 독립 사용자 결과는 서로 다른 WorkUnit identity로 표현되어야
   한다. exact WorkUnit 개수를 Gold로 강제하지 않되, 두 독립 Draft를 한 결과로 합치는
   것은 허용하지 않는다.
5. Approval/Policy/Execution/Verification 경계는 변경하지 않는다.

이 contract가 닫히기 전에는 v4를 Production Prompt/Schema에 활성화하지 않는다.
