# 095 — Task enum 표시 대체: 상태 개선, 부분조회 범위 회귀

## 결론

[고정 기준](095-task-status-presentation-criteria.md)의 신규 FIRST2회 결과는
**1 PASS / 0 PARTIAL / 1 FAIL**이다. [094 결과](094-product-task-field-scope-result.md)의
0 PASS / 1 PARTIAL / 1 FAIL과 비교해 FULL은 개선됐지만 PARTIAL 입력은 실패가 남았다.
기준094의 실패 raw를 교체하거나 새 Trial로 재실행하지 않았다.

두 입력 모두 `needsAction → incomplete` 표시 대체 뒤 모델의 `진행 중` 과잉해석이
사라졌다. 그러나 PARTIAL 답변은 `작업 A의 상태만` 요청에 A 기한까지 추가했다.
**상태 표현의 국소 효능은 관측됐지만 전체 답변 범위 선택은 안정화되지 않았다.**
이 view는 Product에 채택하지 않는다. [093의 formatter 범위 guard](093-task-work-field-handoff.md)
ADOPT는 유지하며, 실패한 자연어 의미를 후처리하거나 Snapshot에 덮어쓰지 않는다.

## 고정 조건과 실제 변경

- 실행 코드 HEAD: `3039e9641d9d6d06a673e34cf59260e12bdc37be`.
- 역사 기준 HEAD: `befbb77afd7131b23e41c170b67985ca2f28474a`의094 native FIRST2개.
- 요청은 그대로 `작업 A의 상태만 알려주고, 작업 B는 예정일만 알려줘.`이다.
  FULL은 A/B snapshot, PARTIAL은 A만 있는 동일 합성 fixture를 재사용했다.
- 입력 변환은 approved Task snapshot과 원래 합성 excerpt 직렬화가 전체 일치할 때만
  기존 `_task_status(..., korean=False)`의 `needsAction → incomplete`를 적용했다.
  `completed → completed`는 no-op이다. 임의 본문에서 `status:`를 찾아 고치지 않는다.
- 변경은 두 native wire 입력 복사본의 Evidence **표시용 excerpt의 status 값**뿐이다.
  원문, Intent/Source/조건, outline, target/date, 조회 상태, refs/handles는 그대로다.
  원본 Evidence·snapshot·segment/version·historical Run은 변경하지 않았다.
- 새 view의 독립 계약은 `evaluation-task-status-presentation-input-v1`이다.
  기존 `planning.compose_answer@1.0.19` PromptRef는 역사 출처로 보존했다.
  Product Registry가 새 view를 resolve했거나 새 normalized artifact가 같은 hash라고
  주장하지 않는다. Prompt ROLE/공통 문맥/Schema/format/옵션은094와 같다.
- qwen3.5:9b, Ollama0.34.0, digest
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
  `think=false`, ctx16384, seed20260923, temperature/presence override 미전송이다.
  모델 설정은 temperature1 / presence_penalty1.5 / top_k20 / top_p0.95로 동일하다.
- FULL→PARTIAL 각1회, concurrency1, timeout180초, 총 신규 generation 최대2,
  repair/retry/대체 Trial0. wall420초는 다음 dispatch 전 검사다.

## 사례별 결과와 최초 차이

| 입력 | 역사094 | 신규095 FIRST | 판정·원인 |
| --- | --- | --- | --- |
| FULL | A를 `진행 중 (needsAction)`으로 과잉해석. B 예정일10/2와 귀속은 정확해 PARTIAL. | `작업 A의 상태는 incomplete입니다. 작업 B는 예정일이 2026년 10월 2일입니다.` | **PASS**. 상태와 B date-only 예정일을 정확히 보존했고 A 기한·B 상태를 추가하지 않았다. 한국어 번역 문구 하나를 Gold로 강제하지 않는다. |
| PARTIAL | A를 `진행 중`으로 과잉해석하고 B 예정일 미확인 설명도 누락해 FAIL. | `확인된 작업 A의 상태는 incomplete이며, 해당 자료에 따르면 기한은 2026 년 10 월 1 일입니다. 다른 작업 정보는 확인하지 못했습니다.` | **FAIL**. 상태는 정확해졌고 다른 작업의 미확인 한정도 생겼다. 그러나 명시적으로 상태만 요구한 A의 기한을 추가했다. 최초 범위 위반은 compose FIRST다. |

PARTIAL의10월1일은 실제 A snapshot에 존재하며 B의 기한으로 주장하지 않았다.
따라서 없는 사실 창작이나 A→B 날짜 교차귀속으로 과장하지 않는다. 문제는 **사실이
존재해도 사용자가 제외한 답변 범위에 추가했다는 것**이다. [088의 명시 범위 판정](088-registered-answer-choice-result.md)과
동일하게, 정확한 추가 값이라는 이유로 PARTIAL/PASS로 완화하지 않는다.

`다른 작업 정보는 확인하지 못했습니다`는 이 두 작업 요청에서 B를 미확인으로 한정하는
표현으로 인정한다. 정확히 `B 예정일`이라는 문자열이나 특정 목록 형식을 요구하지 않는다.
095 PARTIAL의 FAIL을094와 같은 미확인 설명 누락으로 유지하지 않고, **개선된 상태·한정과
새로 관측된 과잉 포함을 분리**한다. 불필요 WRITE/승인/실행 주장0이다.

094 fixture는 `missing_information=[]`를 처음부터 생성했다. 별도 typed B 미확인 항목을
Product가 삭제한 것이 아니다. 원문 B 요청, PARTIAL/HAS_MORE 및 A만 있는 Evidence가
양쪽 입력에 유지됐다. 이번 결과를 typed missing 항목의 producer 손실 수정으로 표시하지 않는다.

## 봉인·admission·관측 경계

- 역사 raw 전체 SHA와094 plan 파일 SHA를 확인하고 원본 FIRST와 snapshot을 그대로 사용했다.
  현재 raw의 `historical_reference_results`는094 calls2개와 정확히 같다.
- 각 원본 snapshot의 handle/version/hash가094의 같은 local Run에서 실제 RESOLVED된
  관측과 일치한다. 같은 Run이라는 사실은 과거 sealed lineage로 검증했으며 새 store를
  실행하거나 현재 Run의 snapshot authority를 만든 것은 아니다.
- 독립 검수에서 역사 payload 일치2/2, 원본 snapshot 불변2/2, status-only view2/2,
  양쪽 wire 입력 view 일치2/2, 입력 외 body/system·format/options 불변2/2를 확인했다.
- 신규 input hash, object-wire hash, 실제 transport byte hash와 dispatch 기록2/2 일치,
  lineage trial hash와 plan hash 재계산 일치. `binding_unchanged=true`다.
- FIRST2개 모두 JSON/기존 OutputSchema VALID, done_reason=`stop`, 반환2/2다.
  admission은 생성 answer/refs를 그대로 보존하며 의미를 고치지 않았다.
- 이번은 **미등록 direct-wire 진단**이다. Product normalizer, `_with_partial_scope`의
  prefix 추가, actual registered router, compiled Planning/Supervisor는 실행하지 않았다.
  따라서094의 Graph 반환과095의 schema admission을 같은 연결 검증으로 표시하지 않는다.

## 호출·토큰·지연

| 입력 | 신규 FIRST / repair | input / output tokens | reported latency | HTTP wall |
| --- | --- | --- | --- | --- |
| FULL | 1 / 0 | 3,507 / 64 | 11,542ms | 11,562ms |
| PARTIAL | 1 / 0 | 3,132 / 66 | 4,307ms | 4,328ms |
| 신규 합계 | **2 / 0** | **6,639 / 130** | **15,849ms** | 호출 wall 합계 **15,890ms** |
| 역사094 합계 | 2 / 0 | 6,643 / 114 | 13,971ms | 다른 registered component 실행 범위 |

missing usage0, 미전송0, retry0, rerun0이다. FULL load duration7,120ms가 reported latency에
포함됐다. 역사 기준의 cold-load/Graph 실행 범위가 다르므로 토큰4개 감소나 지연 차이로
제품 성능 개선/회귀를 단정하지 않는다. completed-only 입력은 status 대체가 no-op이어서
새 모델 호출하지 않았고, 그에 대한 반복 무회귀 점수도 추가하지 않았다.

Provider READ/WRITE/SEND0, Graph0, registered router0, Product source/Prompt activation0.
사전 직접33 tests PASS 및 scoped Ruff/mypy PASS는 변환·봉인·반례 검사이며 모델 의미 점수에
합산하지 않는다. 이번 결과 문서 검수에서 모델·테스트를 재실행하지 않았다.

## 재현 자료

- 신규 raw: `evaluation/results/095-task-status-presentation-t1/raw.json`
- 신규 raw SHA256: `5b9aea4c54d680b1cbc01a1482afa39c4cd311ca0e20378cd687553e08e6b23a`
- 신규 plan object hash: `8afc8639aa2d02830a2090c659ea225631b4a12dfa78aa0cc9fe3f3755bd332f`
- 역사094 raw SHA256: `c105a18762ceda2b070dea3b82995e502d4aec447a3f3376a1940c11f4676f14`

| 입력 | 신규 input SHA256 | 실제 transport byte SHA256 |
| --- | --- | --- |
| FULL | `b9b689585599dd4c045aff02056b19f955d2323a0d2d9e35b25a89192008d054` | `4df2ba1819959114d098e7fb30914c9ebeef0fc961aa1d84e8a45546b7224f36` |
| PARTIAL | `394f4dd9c63b2354a1d26ccb814a8b92d04665785e8832a28cff0fa4f7ba2353` | `fde3542f85adf937e9d8e436a99e03e7f32feb33957648016063d91b51a7121f` |

원본 raw의 `semantic_verdict=NOT_REVIEWED`는 보존하고 독립 의미 판정은 이 문서에 기록한다.
상세 raw는 기존 ignored 로컬 결과 정책이며, 원격에는 이 비민감 결과 요약이 남는다.

## 판단과 미검증 범위

**Product 채택은 하지 않는다.** enum 표시를 기존 확정 의미로 전달하는 축은 두 입력에서
긍정적인 관측을 얻었지만, 동일 원문의 답변 범위 선택까지 해결하지 못했다. 아직
등록된 input contract/실제 compiled 경로·반복 안정성·다른 Task/Calendar·본문 조건은
검증하지 않았다. Source 목록을 곧바로 답변 허용 필드로 만드는 새 정책도 채택하지 않는다.

이 결과는 과거068의 보조 fact 추가와 달리 enum 표시 자체를 대체한 비교지만, 한 번씩의
성공으로 원인 전체가 규명됐다고 말할 수 없다. 값의 의미 표현과 요청별 포함/미확인 판단은
구분해 다음 구조 검토의 근거로만 보존한다. 부분조회 FAIL을 재실행해 교체하거나 새 규칙으로
즉시 가리지 않는다. Canonical92·실제 RU/Retrieval upstream·Main/API/terminal DB·Live Provider·
Approval 이후 Execution/Verification·release는 미검증이다.
