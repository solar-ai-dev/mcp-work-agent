# 00. Project Source Guide

**목적:** 제품 의미를 소유한 Canonical과 선행 읽기 순서를 정한다.

**Authority:** concern ownership, cross-document precedence, 문서 변경 원칙

**상태:** CANONICAL

**수정일:** 2026-09-07

## 권위와 우선순위

현재 확정 제품 요구가 제품 동작의 기준이다. 현재 코드와 검증 근거는 구현 상태를 판정하는 자료이며, 과거 Issue·댓글·Canonical은 최신 결정과 상충하지 않는 상세만 제공한다. Repository Architecture는 구조와 책임의 불변조건을 소유한다.

충돌 시 문장을 절충해 양쪽에 남기지 않는다. 해당 의미의 owner를 최신 결정에 맞추고 downstream 문서는 실제 소비 의미가 바뀔 때만 수정한다. 제품 코드에 남은 결함이나 compatibility를 정상 제품 계약으로 승격하지 않는다.

## Concern owners

| Concern | Owning Canonical |
| --- | --- |
| 제품 목표·범위·비기능 요구 | `01 Requirements PRD` |
| 사용자 관점 기능과 완료 조건 | `01-A Functional Definition` |
| 결정적 allow/block/approval/safety 정책 | `01-B Policy Definition` |
| 화면·상호작용·표시 의미 | `02 UI/UX Design` |
| 시스템 경계·layer·runtime topology | `03 System Architecture` |
| 영속 모델·DB 불변조건·migration 규칙 | `04 Domain·Database Design` |
| lifecycle state·command·guard·resume target | `04-A Domain State Transition Contract` |
| Retrieval query/evidence/coverage 의미 | `05 Context Retrieval` |
| Agent·Supervisor·LangGraph orchestration | `06 Agent Workflow` |
| API·Port·MCP·typed/wire contract | `07 Tool·MCP·Internal Interface` |
| cross-boundary 호출 순서 | `08 Sequence Design` |
| credential·consent·security boundary | `09 Security·Auth` |
| startup·runtime·release environment | `10 Infrastructure·Environment` |
| Activity·Trace·Audit·logging | `11 Observability·Logging·Audit` |
| 검증 전략과 test gates | `12 Test Design` |
| lifecycle regression matrix | `12-A State Transition Test Matrix` |
| evaluation dataset·grader·promotion | `13 Evaluation·Experiment` |
| 운영·진단·복구 절차 | `14 Operations·Troubleshooting` |
| Agent capability·Prompt·failure contract | `15 Agent Capability·Failure·Prompt Contract` |
| directory ownership·naming·dependency·single authority | `16 Repository Architecture` |

## 선행 읽기

모든 변경은 이 Guide와 제품 owner를 먼저 읽는다. lifecycle·persistence·external effect 변경은 04-A와 04를 함께 읽고, Agent/Graph 변경은 06과 15를 함께 읽는다. API/Connector 변경은 07, credential은 09, startup/runtime은 10을 추가한다. 마지막으로 16을 적용해 repository placement와 dependency를 결정한다.

## 문서 관리 규칙

- 한 의미의 완전한 정의는 owner 한 곳에 둔다.
- 다른 문서는 자기 관점의 local consequence와 개념 참조만 둔다.
- 현재 계약을 설명하는 본문에 변경 이력, SHA, 완료표, audit ledger, spec-to-code inventory를 두지 않는다.
- 문서 버전과 실행 계약 버전을 혼동하지 않는다. 연결 문서 버전 변화만으로 다른 문서 버전을 올리지 않는다.
- 새 요구를 반영할 때 같은 문서의 낡은 문장과 중복을 함께 제거한다.
- 구현되지 않은 요구는 요구로 기술할 수 있지만 구현·테스트·Live 검증 완료로 표현하지 않는다.
- runtime Prompt source, manifest/schema/hash, typed contract, evaluation dataset/runner/grader, fixture, 적용 migration은 문서 정리 산출물과 구분해 보존한다.
