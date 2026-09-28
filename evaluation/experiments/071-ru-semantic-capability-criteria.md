# 071 — 제품 표현을 요구하지 않는 요청 의미 capability control

## 가설과 범위

현재 기준 HEAD는 `d03aa884fca5707136937da79bc0ed50de21434a`다. 기존 Source 실패가
자연스러운 요청 이해에서도 나타나는지, Product 표현을 생성할 때 나타나는지 구분한다.
이는 Product 후보나 새로운 최종 정답 생성 단계가 아니라 **능력 진단 대조군**이다.

기존 046/047/049는 WorkUnit/Relation Schema를 요구했고, 063 v7은 기존 WorkUnit과
information-needs 표현을 사용했다. 064 v36/v39는 API format만 제거했으므로 Prompt의
Schema가 남아 있었다. 이번에는 Product Schema/catalog와 생성된 Goal/Work 자체를
입력하지 않는다. 여러 부담을 함께 제거하는 diagnostic이므로 효과를 단일 필드나
노드 수의 인과 효과로 주장하지 않는다. 기존 실패 결과와 기각 판단은 보존한다.

## 고정 실행

- Core 005/009/017/049/059, 각 FIRST 1회, 신규 모델 호출 계획/상한 5회. repair/retry 0.
- 원천은 Canonical v8과 hash-bound 064 v42의 schema_constrained 5개 입력이다.
  exact user_request, selected_resource_refs, run_reference_time만 전달한다.
- system: `사용자 요청의 업무 의미를 해석한다. 요청한 최종 결과, 그 결과에 필요한 자료, 명시된 조건을 간단한 한국어로 설명한다. 실제 조회나 실행을 수행하거나 그 결과를 지어내지 않는다.`
- 자유 한국어 출력. Product PromptRef, JSON Schema, Resource/Tool 후보, Gold,
  Case ID, 이전 오답, hidden reasoning을 입력하거나 요구하지 않는다.
- 기존 v42 FIRST의 모델 digest/options/think=false/stream=false를 보존한다.
  새로운 temperature/num_predict/top-p 조정은 하지 않는다. 요청별 timeout 180초.
- transport 오류·timeout·다른 모델·미완료 응답이면 미실행 나머지를 기록하고 중단한다.
  서버에서 끝나지 않은 생성과 후속 호출을 겹치거나 실패 Trial을 대체하지 않는다.
- prepare와 execute의 HEAD/code/dataset/fixture/model/plan hash를 결속한다.
  실행 claim과 raw는 배타적으로 생성하며 실패 Trial도 보존한다.
- loopback Ollama만 사용한다. Provider READ/WRITE, Graph, 승인, Product 변경은 0.
  실행 중 모델은 하나만 사용하고 테스트·편집·다른 모델을 병렬 실행하지 않는다.

## 사전 의미 판정

개수·분해 모양·문장 일치가 아닌 원문 의미를 판정한다. 아래 기준은 모델에 제공하지 않는다.

| Case | 보존할 의미와 반례 |
| --- | --- |
| 005 | 선택 Task의 상태·기한만 확인. 새 Task를 만들지 않음. 실제 상태·날짜를 지어내지 않음 |
| 009 | 메일과 Task가 필요한 근거이며 최종 결과는 현재 진행 상황 답변. 새 Task/Event/회신을 요청한 것으로 만들지 않음 |
| 017 | Task 목록과 8월 12일 Calendar를 확인해 지정 수신자용 충돌 안내 Draft 준비. 없는 검토회의 시간이나 실제 충돌을 확정하지 않음. 기존 Draft 조회는 출력이라는 이유만으로 필수 근거가 아님 |
| 049 | 메일·Task·Calendar 입력, 새 Task의 8월 13일 13시 기한, 13시 시작 1시간 Event, 지정 수신자 안내 Draft라는 서로 다른 결과를 보존. SEND나 기존 Draft를 필수로 추가하지 않음 |
| 059 | 납품 일정 확인 사실을 알리는 답장 SEND 의도와 원 메일 맥락 필요성을 보존. 확인해 달라는 질문이나 Draft만으로 축소하지 않고 실제 발송했다고 주장하지 않음 |

명시 의미를 모두 보존하면 PASS, 행동 반전 없이 일부 의미가 누락되면 PARTIAL,
요청하지 않은 효과·금지 위반·Source 대체·사실 발명·핵심 결과 반전이면 FAIL이다.
불확실한 합리적 해석은 별도 근거를 남기고 임의의 exact decomposition으로 실패 처리하지 않는다.
출력 유무/완료 여부와 사람이 검수한 의미 판정은 분리한다.

## 비교와 다음 선택

역사 v42 Source-only 기준은 2 PASS / 2 PARTIAL / 1 FAIL이다. 신규 대조군은 최종 결과와
조건도 설명하므로 **같은 Product task 성공률로 점수를 직접 승계하지 않는다**.
공통 Source 보존 축, 새 결과·조건 관측, calls/input-output tokens/load/inference/wall latency를
각각 보고한다. 역사 SHA와 신규 SHA, 실제 Runtime을 분리한다.

자연어에서도 실패하면 반복 오류의 학습 가능성/인식-생성 차이/모델 비교를 검토한다.
자연어가 더 정확하면 표현 생성·binding 경계의 최소 구조 후보를 선택한다. 어느 결과도
LoRA 필요성이나 전체 노드 재구성의 타당성을 단독으로 확정하지 않는다. 효과가 있는
후속 후보는 deterministic 연결과 실제 consumer 검증 전 Production에 반영하지 않는다.
Holdout/Stress 학습·튜닝, 전체92, 외부 유료 학습, 대규모 모델 다운로드는 이 진단에 포함하지 않는다.
