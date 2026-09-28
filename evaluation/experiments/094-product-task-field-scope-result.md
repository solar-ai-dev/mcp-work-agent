# 094 — Product Task 필드 범위 위임의 실제 모델 결과

## 결론

[사전 기준](094-product-task-field-scope-criteria.md)에 고정한 합성 입력2개를 각각1회 실행했다.
독립 의미 검수는 **0 PASS / 1 PARTIAL / 1 FAIL**이다. 실제 registered router와 compiled
Planning 연결은2/2 반환했지만, 이를 업무 의미 성공2/2로 계산하지 않는다.

[093 Product 수정](093-task-work-field-handoff.md)의 **ADOPT는 유지**한다. 이질적인 Source
필드를 모든 Task에 교차 적용하던 결정적 formatter를 중단하고 원문과 기존 typed 입력을
작성 owner로 전달하는 수정은 유효하다. 094에서는 A 예정일을 B 답변으로 바꾸거나 B 상태를
추가하지 않았다. 다만 위임된 모델이 `needsAction`을 두 번 모두 `진행 중`으로 해석했으며,
부분조회에서는 B 예정일의 미확인 설명도 빠졌다. **코드의 범위 전달 개선과 모델의 사실
해석 실패는 다른 실패군**이다. 이 결과는 Prompt 변경이나 새 모델 후보의 채택 근거가 아니다.

## 조건과 실행 범위

- 실행 HEAD: `befbb77afd7131b23e41c170b67985ca2f28474a`.
- 요청: `작업 A의 상태만 알려주고, 작업 B는 예정일만 알려줘.`
- 같은 Work1에 status/due Source2개를 둔 정상 V3 합성 입력이다. 이 decomposition을
  정답으로 강제하지 않는다. Goal 요약은 원문과 다르며 원문도 실제 compose 입력에 보존됐다.
- FULL: A=`needsAction`, 예정일2026-10-01 / B=`completed`, 예정일2026-10-02.
- PARTIAL: A만 관측했고 B Evidence/snapshot은 없다. 조회 상태는 PARTIAL/HAS_MORE다.
- 같은 Run의 EvidenceStore와 exact snapshot/version, 실제 Planning·Supervisor projection을
  사용했다. 입력은 합성 component 자료이며 실제 RU/Tool/Provider가 생성한 upstream이 아니다.
- Product Prompt `planning.compose_answer@1.0.19`, input contract3,
  output schema `planning-answer-draft-v2`를 유지했다. Prompt content SHA256은
  `9139d83cf3a2cf1e0ccb87b77e7e4fb532d8482043d9619e46c81327741c39f1`이다.
- qwen3.5:9b / Ollama0.34.0. 모델 digest:
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
- 실제 wire는 `think=false`, `options={num_ctx:16384, seed:20260923}`다.
  temperature/presence override는 보내지 않았다. 모델 설정은 temperature1,
  presence_penalty1.5, top_k20, top_p0.95이며 temperature0 실험으로 표시하지 않는다.
- FULL→PARTIAL 순서, 각 FIRST1, 총2회, concurrency1, 호출 timeout180초다.
  Product NORMAL budget(LLM limit14 / execution900000ms)은 유지하고 평가 dispatch cap1을
  각 입력에 적용했다. wall1200초는 다음 dispatch 전 검사이지 실행 스레드 강제 종료가 아니다.
- 088 FACT/PROSE, 091 alias omission, 092 temperature 후보는 모두 적용하지 않았다.

## 사례별 의미 판정

| 입력 | 실제 FIRST와 보존된 부분 | 최초 오류 및 판정 |
| --- | --- | --- |
| FULL | `작업 A의 상태는 진행 중 (needsAction)입니다. 작업 B는 예정일인 2026년 10월 2일입니다.` A/B 식별, B 예정일, Evidence refs2개가 맞고 A 예정일·B 상태를 추가하지 않았다. | `needsAction`은 미완료이지 진행 착수를 증명하지 않는다. 오류는 compose FIRST에서 생겼다. 날짜·대상·귀속은 맞으므로 **PARTIAL**. |
| PARTIAL | `확인된 작업 A의 상태는 진행 중입니다. 작업을 수행해야 할 것으로 보입니다.` A Evidence ref1개만 인용했고 없는 B 날짜를 만들지는 않았다. | 유일한 관측 상태를 과잉해석했고 명시 요청한 B 예정일의 미확인 설명도 없다. 수행 필요성에 관한 추측은 요청되지 않았다. **FAIL**. 이 추측을 외부 WRITE 실행으로 계산하지는 않는다. |

PARTIAL 최종 답변에는 기존 deterministic 처리로 다음 안내가 정상 추가됐다.

> 확인한 범위의 부분 결과입니다. 요청한 전체 범위를 확인한 것은 아닙니다.

이 안내는 조회 범위 경고를 보존하지만 A 상태의 오류를 고치거나 B에 대한 답변을 대신하지
않는다. A의2026-10-01을 B의 예정일로 사용하는 오류, 없는 B 사실 생성, 미승인 WRITE는0이다.

### 기존 판정과의 일관성

- [067 결과](067-query-ref-postfix-connected-result.md)와
  [068 결과](068-task-completion-fact-result.md)는 정확한 대상·날짜를 유지하면서
  `needsAction`을 `진행 중`으로 표현한 답변을 PARTIAL로 판정했다. FULL은 같은 기준이다.
- [065 기준](065-read-answer-handoff-model-criteria.md)은 일부 보존과 요청 누락을 구별한다.
  PARTIAL 입력은 단순 표현 차이가 아니라 A의 사실 오류와 B 요청의 미확인 설명 누락이
  결합되어 FAIL이다. 두 오류를 숨기고 일반 부분조회 prefix만으로 성공 처리하지 않는다.
- [081 결과](081-answer-fact-selection-result.md)의 좁은 사실참조 성공과
  [088 결과](088-registered-answer-choice-result.md)의 제목·메모 과잉 선택 실패는
  다른 입력/후보의 결과다. 점수나 분모를094로 승계하거나 합산하지 않는다.

## input → FIRST → normalization → Supervisor

1. 원문, full Intent, Source별 요구 필드, Work binding, Evidence와 조회 상태가 실제
   compose input에 남았다. same-Work Evidence ref union을 A/B target authority로 변환하지 않았다.
2. 입력에 보존된 A 상태는 `needsAction`이다. `진행 중`은 실제 모델의 FIRST에 처음 등장한다.
   따라서 이번 잘못된 상태 표현을 snapshot 변조나 downstream formatter 손실로 분류하지 않는다.
3. FULL의 최종 answer는 FIRST와 같다. PARTIAL은 FIRST를 유지하고 정상 범위 경고만 추가했다.
   schema repair, semantic revision, 후보 renderer에 의한 의미 교정은 없다.
4. 두 결과 모두 Supervisor가 `RESPONSE_SYNTHESIS / ANSWER_ONLY_RESPONSE_READY`로 연결했다.
   이 전환과 구조 유효성은 사실 정확성을 보장하지 않는다. 로컬 Run scaffold의 durable status는
   CREATED이며 Main schedule/resume·최종 terminal DB commit은 실행하지 않았다.

## 실제 호출·비용

| 입력 | FIRST / repair | input / output tokens | reported latency | trial wall |
| --- | --- | --- | --- | --- |
| FULL | 1 / 0 | 3,509 / 70 | 10,381ms | 12,389ms |
| PARTIAL | 1 / 0 | 3,134 / 44 | 3,590ms | 4,172ms |
| 합계 | **2 / 0** | **6,643 / 114** | **13,971ms** | 전체 runner **16,875ms** |

missing usage0, done_reason=`stop`2회, 실패/미전송 Trial0, 재시도/대체 Trial0이다.
각 실제 budget·trace는1 LLM call이고 semantic revision0이다. FULL load_duration 약5,813ms가
포함돼 있으므로 두 입력의 지연 차이를 의미 구조의 개선/악화 효과로 해석하지 않는다.

Provider snapshot read attempt/return0, WRITE attempt/denial0, 전체 boundary denial0이다.
같은 Run의 로컬 snapshot resolve는 있었지만 Connector READ 호출은 아니다. 외부 계정 연결,
Provider WRITE/SEND, Prompt activation은0이다.

## 봉인과 재현 근거

원본은 `evaluation/results/094-product-task-field-scope-t1/raw.json`에 보존한다.
raw의 `semantic_verdict=UNREVIEWED`는 수정하지 않았으며 위 판정은 이 문서의 독립 검수다.

- Raw SHA256: `c105a18762ceda2b070dea3b82995e502d4aec447a3f3376a1940c11f4676f14`
- Plan SHA256: `b34b4f06e124c8b7baecc79847c433710e8db488c76111e638a832c55fc963b5`
- `binding_unchanged=true`, `model_binding_unchanged=true`, 실제 input/원본 고정 input/
  native prompt JSON input 동일2/2, 실제 transport byte hash 일치2/2.

| 입력 | actual input SHA256 | actual transport SHA256 |
| --- | --- | --- |
| FULL | `0504bbd0461bfb5ca3a15260b4e7b021dfb35f14c4c2c6fa04b7cab7d99a043f` | `b84862e8baa0f65bc2ca85f2422f157088de45a1a0438b69868631f5baf7bed5` |
| PARTIAL | `40e1d03ff5b7cf1a5d5fba231d34365d0c130785b5484760a253b7de76e092e4` | `a53e9dae2630f617d94dfc8687e9697e9bd1b2e8348939c5909ad7e35ea884dd` |

상세 raw는 기존 로컬 결과/ignore 정책을 따른다. 원격 commit에는 이 비민감 요약과 기준이
남으며 raw 전체가 원격에 올라갔다고 주장하지 않는다. 문서 작성에서 모델/테스트 재실행은0이다.

## 판단·한계·다음 경계

093의 owner-local 범위 guard는 ADOPT 유지한다. 이번094가 새로 확인한 것은 이질적인
field scope를 실제 Product 작성 owner에 전달할 수 있다는 연결과, 그 owner가 여전히 상태를
과잉해석하고 부분조회 요청을 빠뜨린다는 한계다. 이를 formatter rollback이나 코드가 자연어
의미를 사후 교정해야 한다는 근거로 사용하지 않는다.

관측된 입력이 좁고 각각1회이므로 반복 안정성·다른 Task/Calendar 업무·Canonical92 성공률은
미검증이다. RU→Tool→Retrieval 실제 upstream, Main/API/DB terminal, Live Provider,
Approval 이후 Execution/Verification, release는 이번 범위가 아니다. 불필요 WRITE0도
READ-only component 경계의 관측이며 제품 전체 안전성 검증으로 확장하지 않는다.

다음 비교는 이 두 실패를 최초 compose 판단의 서로 다른 문제(확정 상태의 과잉해석,
부분조회에서 명시 미확인 항목 누락)로 보존해야 한다. 같은094 Trial 재실행으로 실패를
교체하거나, Prompt 문장·상태 후처리로 바로 봉합하거나, 093 직접 검사와 합쳐 전체 성공률을
만들지 않는다. 신규 변경/실험의 채택 여부는 별도 기준·입력·실행 근거로 판단한다.
