# mcp-work-agent — Codex Instructions

이 AGENTS.md는 저장소 루트 전체에 적용한다.
하위 AGENTS.md는 경로별 규칙을 추가할 수 있지만 이 파일의 현재 제품 요구, Canonical authority, semantic maintenance 원칙, safety·ownership 규칙을 약화시키면 안 된다.
- 현재 Repository는 solar-ai-dev/mcp-work-agent다.
- 작업 기준은 현재 checkout된 branch의 local/remote HEAD와 working tree다. 특정 과거 branch 이름을 장기 작업 기준으로 하드코딩하지 않는다.
- 사용자가 명시하지 않은 branch 생성·전환·merge·rebase·reset·revert는 하지 않는다.
- 과거 SHA, 과거 성공 Run, Issue, Trace, 실험 결과는 ​비교 근거**이지 자동 복원 기준이나 구현 Authority가 아니다.
- 항상 00 Project Source Guide에서 Concern Owner와 선행 읽기 순서를 먼저 확인한다.
- 제품 behavior는 해당 Concern Owner가 소유한다.
- Repository path/file/symbol/import/single-authority 규칙은 16 Repository Architecture가 소유한다.
- Agent·Workflow orchestration은 06 Agent · Workflow, Prompt·Agent capability·failure contract는 15 Agent Capability · Failure · Prompt, Retrieval 의미는 05 Context · Retrieval을 따른다.
- current code는 구현 상태를 보여 주는 근거이지 Canonical behavior를 새로 정의하는 Authority가 아니다.
- 반대로 Canonical 문서에 concrete file inventory가 없다는 이유로 현재 정상 production path를 임의 재설계하지 않는다.
- 적용된 Migration은 수정·재번호·이동·squash하지 않는다. 실제 persistent invariant 변경이 필요하면 forward Migration만 추가한다.
현재 기본 작업 단계는 신규 제품 기능 개발이 아니라 LangGraph semantic maintenance / reliability improvement 단계다.
제품의 주요 구조와 외부 기능은 이미 구현되어 있다고 가정한다.
따라서 기본 목표는 다음이다.
```
기능 추가
X

케이스별 예외 규칙 추가
X

테스트 하나를 억지로 PASS시키기
X

현재 Agent/State/Schema/Prompt/Validator/Router가
사용자 의미를 얼마나 일반적으로 보존하고 전달하는지 개선
O
```
사용자가 명시적으로 새로운 제품 기능을 요구하지 않는 한 새 capability, 새 workflow authority, 새 Agent, 새 lifecycle state, 새 Connector path를 만들지 않는다.
현재 유지보수의 핵심 대상은 다음 semantic pipeline이다.
```
User Request
→ Request Understanding
→ Tool Route
→ Retrieval
→ Work Analysis
→ Planning
→ Review
→ deterministic execution / terminal path
```
문제는 가능한 한 이 pipeline의 최초 의미 손실 지점(first semantic divergence)​에서 수정한다.
LangGraph 품질을 높일 때 가장 중요한 원칙은 규칙 수를 늘리는 것이 아니라 사용자 요청을 더 일반적인 의미 구조로 표현하는 것이다.
좋은 수정은 특정 문장을 알아보는 코드가 아니라 서로 다른 표현과 Resource에서도 재사용되는 semantic dimension을 만든다.
개념적으로 사용자 요청은 다음처럼 해석될 수 있다.
```
사용자 요청
→ 어떤 의미 그룹에 포함되는가
→ 어떤 의미 그룹에는 포함되지 않는가
→ 반드시 보존해야 할 핵심 의미는 무엇인가
→ 아직 결정되지 않은 의미는 무엇인가
→ 그 미해결 의미의 Owner는 누구인가
```
예를 들어 어떤 요청을 이해할 때 필요한 것은 단순히 문자열 "일정"을 발견하는 것이 아니다.
보다 일반적으로는 다음과 같은 서로 독립된 의미일 수 있다.
```
Resource kind
Required business facts
Target scope / cardinality
Target identity resolution
Temporal meaning
Requested effect
User constraints
Explicit exclusions
Remaining ambiguity
```
이 의미 중 일부가 현재 Typed Contract에 없어서 downstream에서 재구성하거나 추측하고 있다면 Contract 표현력 부족을 먼저 의심한다.
단, 위 목록을 그대로 하나의 거대한 공통 Schema로 새로 만드는 것은 금지한다.
각 의미는 현재 Concern Owner가 실제로 필요로 할 때 owner-local typed contract로 표현한다.
새 field, enum, typed disposition을 추가하기 전에 다음을 확인한다.
1. 특정 테스트 문장의 다른 이름이 아니다.
2. paraphrase가 달라져도 같은 의미를 표현한다.
3. 가능한 경우 여러 Resource 또는 여러 scenario family에서 재사용할 수 있다.
4. Resource-specific 의미라면 왜 그 Resource owner에게만 필요한지 명확하다.
5. 기존 field와 의미가 중복되지 않는다.
6. 하나의 field에 두 개 이상의 독립적인 질문을 섞지 않는다.
7. downstream consumer가 이 값을 실제 판단에 사용할 수 있다.
8. USER, CONNECTOR, SEARCHABLE, NEEDS_CONFIRMATION 같은 다른 책임의 의미를 몰래 포함하지 않는다.
9. Retrieval strategy, Confirmation decision, ownership을 semantic fact와 혼합하지 않는다.
10. producer → merge/assembly → Main State → input projection → consumer까지 손실 없이 전달할 수 있다.
다음과 같은 방식은 피한다.
```
required_information
= 필요한 business fact
+ target identity
+ confirmation requirement
+ retrieval strategy
```
서로 다른 의미 축이면 분리한다.
다음 종류의 구현은 기본적으로 금지한다.
```
if "그 일정" in user_request:
    ...

if "전체" in user_request:
    ...

if resource_type == CALENDAR_EVENT and exact failed case:
    ...

regex로 자연어 intent 확정

특정 테스트 ID를 위한 production branch

특정 Fixture title/email/project 이름에 의존한 semantic rule
```
키워드·정규식·deterministic code가 허용되는 영역은 다음과 같다.
- explicit ID
- email / URL / JSON 형식
- exact selected Resource
- registry identity
- allowlist
- state/version
- approval/execution safety
- deterministic date/time transform
- schema normalization
- 명시적으로 구조화된 exact constraint
자연어 intent, 업무 의미, target semantics, 사람 역할, 모호성 여부를 단순 문자열 규칙으로 최종 확정하지 않는다.
LLM이 만든 semantic result를 deterministic heuristic이 조용히 다른 의미로 덮어쓰는 것도 금지한다.
Agent를 선택하거나 Back-edge를 만들 때 사용자 원문 문자열이 아니라 unresolved typed meaning을 사용한다.
개념적으로 다음처럼 판단한다.
```
요청 의미 자체가 미확정
→ Request Understanding owner

어떤 Connector / Resource / Effect가 필요한지 미확정
→ Tool Route owner

Route는 맞지만 실제 자료가 부족
→ Retrieval owner

Evidence는 있으나 업무 관계·중복·충돌·시간 의미 분석이 부족
→ Work Analysis owner

Action/Answer 작성 문제
→ Planning owner

작성된 Plan의 goal/evidence/constraint/route 정합성 문제
→ Review owner
```
새로운 문제를 해결하기 위해 downstream Agent가 upstream 의미를 다시 추론하게 만들지 않는다.
변경이 필요하면 해당 semantic Owner로 명시적으로 Back-edge한다.
다음 의미를 혼동하지 않는다.
```
검색할 수 있다
≠
대상이 식별되었다

업무 개념이 있다
≠
구체 Resource identity가 있다

검색 후보가 있다
≠
단일 target이 확정되었다

검색 조건이 있다
≠
사용자가 특정 Resource 하나를 지칭했다
```
일반적인 concept/category/business term을 concrete target identity anchor로 자동 승격하지 않는다.
반대로 사용자가 명시한 exact resource, selected resource, title, email, repository, explicit identifier는 의미를 잃지 않도록 보존한다.
LangGraph 실패를 수정할 때 먼저 코드를 바꾸지 않는다.
항상 다음 순서로 진행한다.
```
현재 HEAD / working tree 확인
→ 실패 Case를 현재 코드에서 1회 재현
→ Production Graph Trace 확보
→ Node별 input / output / state projection 확인
→ 최초 divergence 찾기
→ 인접 성공 Case와 의미 차이 비교
→ 실패 종류 분류
→ 최초 divergence Owner만 수정
→ 같은 Case 1회 재실행
→ 인접 회귀 Case 실행
→ 필요한 범위까지 Smoke 확대
```
최종 실패 Node가 아니라 최초 divergence를 수정한다.
예:
```
detect_ambiguity가 잘못된 Confirmation을 반환
```
이라고 해서 바로 detect_ambiguity Prompt를 수정하지 않는다.
그 이전 단계에서 target identity, scope, constraint, required fact가 이미 손실됐다면 upstream contract가 first divergence다.
Trace를 확인한 뒤 실패를 최소한 다음 중 하나로 분류한다.
필요한 의미가 upstream에는 있었지만 현재 Node 입력에서 사라졌다.
수정 대상:
```
projection
merge
assembly
state carry
based_on/freshness
```
Prompt를 수정하지 않는다.
현재 Typed Schema 자체가 필요한 두 의미를 구분할 수 없다.
예:
```
business fact
vs
target scope
```
가 하나의 field에 섞여 있다.
이 경우 owner-local typed contract를 최소 범위로 확장한다.
Input과 Schema는 충분하지만 LLM이 잘못된 Candidate를 만든다.
이때 Prompt / atomic responsibility / output schema / model behavior를 검토한다.
LLM Candidate는 맞지만 Validator, merge, assembler가 의미를 삭제·확장·왜곡한다.
Prompt를 수정하지 않는다.
deterministic code가 semantic candidate를 과도하게 보정하거나 heuristic으로 덮어쓴다.
해당 rule을 제거하거나 실제 deterministic responsibility로 축소한다.
Validated artifact는 맞지만 Supervisor/Router가 잘못된 Edge로 보낸다.
이때만 routing을 수정한다.
Request/Route는 맞지만 Query, read, evidence selection, sufficiency에서 필요한 근거를 확보하지 못했다.
05 Context · Retrieval owner 안에서 해결한다.
동일 입력/contract/config에서 결과가 변한다.
이 경우 단일 실패를 구조 결함으로 단정하지 않고 반복 실험을 별도로 수행한다.
first divergence를 찾은 뒤 아래 원칙으로 수정 위치를 정한다.
```
필요한 의미 자체를 표현할 수 없음
→ Typed Contract

의미는 생성됐지만 downstream에서 사라짐
→ projection / merge / state carry

Contract는 충분하지만 LLM이 의미를 생성하지 못함
→ Prompt / structured output / responsibility split

LLM 출력은 맞지만 deterministic code가 깨뜨림
→ validator / assembler / resolver

Validated state까지 맞지만 다음 단계가 틀림
→ Router / Edge
```
더 앞 단계의 문제가 남아 있는데 downstream Prompt나 Router로 보정하지 않는다.
Prompt는 중요하지만 제품 의미의 최종 Authority가 아니다.
Prompt 변경은 다음 경우에 사용한다.
- Typed input이 충분하다.
- Output contract가 필요한 의미를 표현할 수 있다.
- Validator/merge가 정상이다.
- 그럼에도 모델이 해당 semantic responsibility를 안정적으로 수행하지 못한다.
Prompt 작성 원칙:
- 한 LLM call에 가능한 한 하나의 semantic responsibility만 둔다.
- semantic definition과 boundary를 설명한다.
- 예시는 의미를 설명하기 위한 소수의 contrastive example만 사용한다.
- 테스트 Case catalog를 Prompt에 옮기지 않는다.
- 특정 단어가 나오면 특정 Enum을 선택하라는 lexical mapping을 만들지 않는다.
- upstream/downstream Agent의 책임을 대신 수행하게 하지 않는다.
- Prompt에 새로운 policy, lifecycle, routing authority를 넣지 않는다.
Prompt-only 실험에서 한 Case가 좋아지는 대신 다른 Resource가 모두 선택되거나 semantic scope가 폭발하면 그 변경은 실패다.
실패한 Prompt 실험을 production source에 남기지 않는다.
Schema는 단순 JSON 형식이 아니라 Agent 사이의 semantic language다.
따라서 다음 원칙을 따른다.
하나의 field는 하나의 semantic question에 답해야 한다.
좋음:
```
required_information
→ 어떤 business fact가 필요한가

target_scope
→ 하나의 target인가, 조건 집합인가
```
나쁨:
```
required_information
→ business fact
→ target identity
→ ownership
→ confirmation
→ retrieval strategy
```
안정적으로 닫을 수 있는 semantic axis는 Literal, Enum, discriminated union을 우선한다.
자유 문자열로 downstream routing authority를 만들지 않는다.
새 semantic field를 만들었다면 producer만 수정하고 끝내지 않는다.
최소 다음을 확인한다.
```
producer
→ result contract
→ validator
→ assembler / merge
→ parent state artifact
→ downstream projection
→ actual consumer
```
중간 한 단계에서 drop되면 구현 실패다.
편의를 위해 다음과 같은 broad field를 새로 만들지 않는다.
```
metadata: dict
semantic_flags: list[str]
extra_context: dict
hints: list[str]
```
실제 owner와 의미가 있는 typed field를 사용한다.
현재 semantic owner는 유지한다.
```
request_understanding
tool_routing
retrieval
work_analysis
planning
review
```
새 Agent는 현재 문제를 해결하기 위한 기본 수단이 아니다.
Agent 수를 늘리기 전에 먼저 확인한다.
```
기존 owner 안에서 semantic dimension이 누락됐는가?
기존 atomic node responsibility가 너무 넓은가?
projection이 잘못됐는가?
schema가 표현하지 못하는가?
```
Agent → Agent direct call은 금지한다.
Supervisor는 자유형 의미 판단을 하지 않고 validated typed result를 routing한다.
Confirmation은 모델이 자신 없다는 이유로 사용하는 fallback이 아니다.
사용자에게 실제 결정이 필요한 경우에만 사용한다.
예:
- concrete target이 여러 개 남음
- 사용자가 선택해야 하는 필수 값이 없음
- policy가 명시적 사용자 확인을 요구함
- bounded retrieval로 해결할 수 없는 ambiguity가 남음
반대로 다음은 Confirmation 이유가 아니다.
- 이미 사용자가 제공한 값을 Agent가 잃어버림
- upstream projection이 의미를 누락함
- 검색 가능한 값을 아직 검색하지 않음
- generic business concept를 concrete identity로 잘못 계산함
- Prompt가 이해하지 못했으므로 다시 사용자에게 질문함
이미 사용자에게 받은 값을 다시 질문하지 않는다.
Retrieval은 frozen Input Route 안에서 동작한다.
다음은 구분한다.
```
query hypothesis
candidate discovery
resource identity
evidence selection
sufficiency
```
검색 표현은 가설이다.
검색어가 발견됐다는 이유로 해당 업무 사실이나 Resource identity가 확정된 것은 아니다.
새 Connector/Resource가 필요하면 Retrieval이 임의 확장하지 않고 ROUTE_RECONSIDERATION_REQUIRED를 반환한다.
사용자 exact anchor와 semantic requirement는 Query optimization 과정에서 제거하지 않는다.
같은 Query의 무진전 반복으로 Case를 PASS시키지 않는다.
Validator는 모델을 대신해 업무 의미를 새로 생성하는 곳이 아니다.
Validator의 기본 책임은 다음이다.
- Schema validity
- closed enum
- required relationship
- cross-field consistency
- frozen route consistency
- current revision/freshness
- deterministic invariant
Validator가 자연어 의미를 heuristic으로 새로 추론하여 LLM 결과를 고치는 구조를 만들지 않는다.
Validation 실패가 자주 발생하면 먼저 다음을 구분한다.
```
모델 Candidate 오류
vs
Contract가 표현 불가능
vs
Validator가 과도하게 제한
```
한 문제를 고친 뒤 전체 Suite부터 실행하지 않는다.
기본 순서:
```
1. 현재 실패 Case 1회
2. 같은 semantic boundary의 인접 Case
3. 수정 전 이미 성공하던 대표 Case
4. 직접 영향 Core/Smoke
5. 필요할 때만 더 넓은 Suite
```
각 코드 변경 사이에 동일 Case를 반복 실행하여 우연히 PASS한 결과를 선택하지 않는다.
```
rerun-to-pass = 0
```
반복 실행은 모델 안정성 자체를 측정하는 실험일 때만 한다.
그 경우 동일:
- commit
- model
- Prompt bundle
- config
- fixture
를 유지하고 Trial 결과 전체를 기록한다.
Schema / Prompt / temperature / retrieval strategy / top-k 등을 비교할 때 가능한 한 한 번에 하나의 독립 변수만 바꾼다.
실험 결과를 production rule로 바로 승격하지 않는다.
특히 다음은 diagnostic candidate일 뿐이다.
```
temperature 변경
top-k 변경
Prompt example 추가
Prompt emphasis 변경
모델 rerun
```
실험 결과는 다음 질문에 답해야 한다.
```
왜 이 변경이 성공했는가?
어떤 semantic responsibility가 개선됐는가?
다른 Case에서도 같은 이유로 동작하는가?
```
설명할 수 없는 우연한 PASS는 채택하지 않는다.
회귀 분석에서는 실패 Case만 보지 않는다.
가능하면 다음을 비교한다.
```
현재 실패 Case
vs
같은 SHA의 유사 성공 Case

현재 실패 Trace
vs
과거 안정적으로 성공한 Trace
```
비교 대상:
- Node input
- Node output
- typed semantic dimensions
- revision/freshness
- selected route
- Evidence coverage
- validator result
- routing result
단순 최종 terminal status만 비교하지 않는다.
과거 성공 코드를 그대로 되돌리는 것은 최후 수단이다.
현재 구조가 더 일반적이고 올바른데 특정 Case 성공률만 낮아졌다면 원복보다 현재 구조의 semantic gap 수정이 우선이다.
다음 불변조건을 유지한다.
```
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```
- Domain: invariant와 lifecycle/domain semantics
- Policy: deterministic allow/block/approval/safety
- Application: use case와 transaction orchestration
- Workflow/LangGraph: State, Node/Edge/Interrupt/Resume orchestration
- Port: 외부 boundary contract
- Adapter/Connector: concrete integration
- API: protocol validation/translation
- Composition Root: construction/DI/lifecycle wiring only
금지:
- Core → Provider SDK/API direct call
- Application → concrete Adapter
- Domain → Application/Adapter
- FastAPI Route → DB/Adapter concrete
- Agent → Provider API/SDK
- Agent → peer Agent direct call
- Agent/LLM → external Write authority
- speculative abstraction
- second live production authority
- broad generic semantic bucket
- case-specific production rule
- 단순 forwarding만 늘리는 wrapper/adapter chain
LangGraph semantic maintenance 중에도 execution safety는 절대 완화하지 않는다.
- Domain Store는 승인·실행·검증 사실의 기준점이다.
- LangGraph Checkpoint는 workflow resume 위치다.
- UI/SSE/Trace는 Projection이며 Domain truth가 아니다.
- external MCP/Provider/LLM I/O 중 SQLite write transaction을 유지하지 않는다.
- Write는 Canonical Approval → Claim → BeginExecutionAttempt → Connector Write → Verification/Recovery 경계를 따른다.
- BeginExecutionAttempt(applied=true) commit 전 Connector Write는 0이어야 한다.
- UNKNOWN_RESULT에서는 blind resend나 새 Write Attempt를 만들지 않는다.
- Agent/LLM이 approval, policy, state transition, execution success를 최종 판정하지 않는다.
- semantic quality 수정 때문에 write-safety validator나 Domain guard를 약화하지 않는다.
- 테스트를 통과시키기 위해 Approval/Claim/Verification 경로를 우회하지 않는다.
Canonical은 기존 구조 위에 추가되는 새 abstraction layer가 아니다.
Typed Contract 변경이 필요한 경우:
```
semantic owner 확인
→ producer 확인
→ consumer 확인
→ validator 확인
→ projection/carry 확인
→ 직접 영향 test 확인
```
을 먼저 수행한다.
실행 계약의 producer와 consumer는 같은 변경 단위에서 갱신한다.
새 contract를 추가하고 old contract를 동시에 production semantic authority로 유지하지 않는다.
Compatibility가 필요하면 history/checkpoint/wire migration 목적의 얇은 경계로 제한한다.
새 semantic field 추가 때문에 unrelated architecture refactor를 수행하지 않는다.
Canonical 문서는 코드 수정에 맞추기 위해 임의 변경하지 않는다.
반대로 기존 Canonical 의미 안에서 typed implementation contract를 더 정확히 표현하는 것은 허용한다.
새로운 제품 semantics 자체가 필요한 경우에는 코드로 먼저 숨겨 넣지 말고 contract decision으로 보고한다.
테스트는 제품 behavior와 semantic preservation을 검증한다.
테스트 자체가 새로운 제품 Authority는 아니다.
LangGraph maintenance에서 특히 다음을 확인한다.
- Node input projection
- Candidate output
- Schema validation
- semantic validation
- owner field patch
- downstream projection
중요한 user meaning이 다음 과정에서 사라지지 않는지 확인한다.
```
Request
→ owner result
→ merge/assembly
→ Main State
→ next owner input
```
Validated disposition과 실제 Edge가 정확히 대응하는지 확인한다.
기존 Approval/Claim/Execution/Verification safety regression을 유지한다.
새 rule이나 helper를 추가하면서 owner boundary와 dependency direction을 깨지 않는다.
검사를 통과시키기 위해 assertion, allowlist, architecture enforcement, safety validator를 약화하지 않는다.
자동 Unit Test만으로 semantic 문제 해결을 완료 선언하지 않는다.
가능하면 실제 production compiled LangGraph 경로를 사용한다.
Local LLM 작업에서는 실제 선택 Local Model을 우선 사용한다.
Trace에서 최소 다음을 확인한다.
```
node / semantic owner
input projection
LLM candidate output
validated result
state patch
next routing
terminal result
```
LangSmith를 사용할 경우 raw secret이나 금지된 원문을 새로 Trace하도록 제품 관측 정책을 변경하지 않는다.
Trace는 debugging evidence이며 Domain truth가 아니다.
한 semantic failure를 수정하면서 주변 구조 전체를 정리하지 않는다.
금지:
- unrelated cleanup
- broad rename
- formatting-only 대형 diff
- dependency upgrade
- 전체 Agent rewrite
- 전체 Graph redesign
- 새 abstraction framework 도입
- 필요 없는 Canonical 문서 일괄 수정
단, first divergence를 수정하기 위해 producer→consumer contract 전체의 직접 영향 변경은 하나의 coherent change로 처리한다.
작업 시작 시 working tree를 반드시 확인한다.
기존 변경이 있으면 다음을 구분한다.
```
현재 작업자의 변경
다른 작업자의 변경
이전 실험 변경
```
다른 작업자의 변경을 임의 삭제·clean·discard하지 않는다.
실패한 Prompt/Schema 실험은 최종 production commit에 포함하지 않는다.
실험 diff를 보존해야 하면 patch나 evaluation artifact로 보존한 뒤 production working tree에서는 제거한다.
단, 기존 변경의 소유권이 불명확하면 destructive cleanup을 하지 않고 보고한다.
- 현재 checkout된 작업 branch에서 계속 작업한다.
- 명시 요청 없이 branch switch/create를 하지 않는다.
- force push, rebase, reset, destructive clean을 하지 않는다.
- 실패 실험을 commit/push하지 않는다.
- semantic fix와 직접 회귀 검증이 끝난 coherent change만 commit한다.
- 한 commit에는 가능한 한 하나의 semantic correction을 담는다.
- 완료 보고 전에 local HEAD, remote HEAD, working tree를 확인한다.
- 다른 작업자의 미완료 변경을 commit에 섞지 않는다.
좋은 LangGraph 유지보수 수정은 다음을 만족한다.
```
특정 문장을 위한 규칙이 아님

사용자 의미를 더 잘 구조화함

semantic owner가 명확함

하나의 field가 하나의 의미를 가짐

producer→consumer 전달이 완전함

downstream heuristic이 줄어듦

다른 Resource/표현에서도 같은 원리로 동작함

기존 successful Case를 불필요하게 깨지 않음

Canonical safety/ownership을 유지함
```
다음은 좋지 않은 수정의 신호다.
```
if 문이 계속 늘어남
Prompt example catalog가 계속 늘어남
특정 Test ID가 production code에 등장
같은 의미를 여러 Agent가 다시 추론
Validator가 LLM 결과를 자연어 heuristic으로 교정
business concept를 concrete identity로 사용
Confirmation으로 내부 semantic loss를 사용자에게 떠넘김
테스트 rerun으로 우연한 PASS를 선택
```
LangGraph maintenance task는 다음을 만족해야 완료다.
1. 실패를 현재 HEAD에서 재현했다.
2. first semantic divergence를 확인했다.
3. 실패 종류를 분류했다.
4. 수정 위치가 해당 semantic Owner와 일치한다.
5. case-specific lexical rule을 추가하지 않았다.
6. 필요한 경우 typed semantic representation을 더 일반적으로 만들었다.
7. producer → consumer 전달을 확인했다.
8. 원래 실패 Case가 수정 후 1회 실행에서 기대 결과를 냈다.
9. 인접 regression Case가 유지됐다.
10. 직접 영향 Smoke/Contract/Safety Gate가 통과했다.
11. 실패한 실험 코드가 production diff에 남지 않았다.
12. commit/push 범위가 coherent하다.
한 Case PASS만으로 완료하지 않는다.
완료 보고는 길게 작업 일지를 작성하지 않는다.
다음만 명확하게 보고한다.
```
최초 divergence
semantic owner
왜 기존 representation이 부족했는지
```
```
어떤 semantic dimension / projection / validator / prompt를 수정했는지
왜 이 수정이 case-specific rule이 아닌지
```
```
실패 Case
인접 regression Case
기존 성공 Case
직접 영향 test/gate
rerun-to-pass 횟수
```
rerun-to-pass는 기본적으로 0이어야 한다.
```
DONE
TESTED
PENDING
BLOCKED
```
- DONE: 구현 완료
- TESTED: 실제 수행한 검증
- PENDING: 남은 작업 또는 아직 확대하지 않은 회귀 범위
- BLOCKED: 필수 외부 조건이 없어 수행할 수 없는 검증
```
commit SHA
push 여부
local/remote HEAD 일치 여부
남은 working tree 변경
```
별도 status/report 문서는 사용자가 요청하지 않으면 만들지 않는다.
