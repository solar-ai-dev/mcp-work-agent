# 064 — Source 판단을 Goal 검색 슬롯이 덮는 소비 경계 수정

## 원인과 판단 변경 근거

기준 SHA `21ebde2c99cfcfeee67df297ec4900ab199de392`.
`064-source-guard-authority.md`의 component에서는 정상 제공자료 답변을 막는 오류와
guard 제거 시 실제 Source 누락도 admission되는 위험을 함께 확인했다. 그 결과만으로는
삭제를 채택하지 않았다. 이후 두 근거를 추가 대조했다.

1. **기존 Canonical15:186**은 deterministic guard가 Source 누락/READ 의미를 새로
   판단하지 못하도록 명시한다. Canonical06의 Goal/Source 책임 분리도 동일하다.
   단순 search_terms/business_concepts nonempty로 Source0을 거절하던 구현은 이
   계약과 일치하지 않는다. 이 문자열 슬롯이 외부 사실 필요성을 확정한다는 계약은 없다.
2. 사전 제한한 대표 기록 **29 JSON/11,265,082 bytes**를 읽어 guard 발생을 확인했다.
   061 Canonical92의 CORE041/044, 062 v4 Canonical92의 CORE041/044/045 및
   HOLDOUT008/STRESS004/005/009, 총9 Case-run에서 **첫 Source0 → revision Source0 → ERROR**.
   Source 복구0/추가 revision9회다. 다른 Core21 T1/T2 및 064 대표 connected 기록에는
   일치가 없었다. 전체 역사에 복구가 없다는 주장이나 Holdout/Stress Prompt tuning이 아니다.

따라서 **모델 의미 개선 후보가 아니라 명시된 owner 계약에 어긋난 결정적 소비의 수정**으로
범위를 좁혔다. v44의 실패 후보는 계속 REJECT다. Source 누락을 해결하거나 기존 FAIL을
PASS로 바꾸는 변경이 아니다. Model Source 판정이 잘못되면 그 첫 의미 실패는 그대로 남는다.

## 수정 범위

- 일반 `identify_goal` 및 budget caller 모두에서 Goal 문자열로 Source 결과를 재판정하는
  호출과 그 전용 semantic revision branch를 제거한다.
- 사용되지 않게 된 helper/exception만 제거한다. Source schema·candidate exact set·scope·
  Work binding과 실제 Source owner의 FIRST/구조 검증은 변경하지 않는다.
- 금지된 Output의 revision, Goal 자체의 typed validation/revision, 실제 dispatch budget,
  SourceStatus owner, selected identity projection, same-Run target confirmation의
  at-least-one Source schema는 유지한다.
- 비활성 frozen connected 평가 caller도 삭제된 API를 호출하지 않도록 정합화한다.
- 기존 code reason은 과거 진단용 목록에 보존한다. persisted artifact/State/schema/Node/
  Edge/graph checkpoint 형상은 바꾸지 않는다. 새 semantic authority나 fallback은 없다.
- 제품 Prompt/manifest/activation/Release gate는 변경하지 않는다.

이 수정은 예컨대 제공 메모에 있는 승인 요청을 정리할 때 정당한 Source0을 그대로 전달한다.
반면 외부메일을 요청했는데 Source owner가0을 출력하면 이제 Goal의 일반 검색어를 근거로
재판정하지 않는다. **이 경우 업무 의미는 여전히 FAIL이며, 자동으로 답변이 정당해지지 않는다.**
안전 검사/Review가 반드시 이를 복구한다고 주장하지 않는다. Source 의미 안정화와 이후
connected 품질 검증이 필요한 잔여 위험을 명시한다.

## 재현·검증 경계

과거 실제 caller를 고정한 평가 fixture와 현재 Product caller를 비교한다. 제공자료 반례와
외부조회 누락 위험을 모두 보존하며, 실제 LLM 판정이 아니라 Fake owner 결과를 소비하는
component다. 역사 fixture는 `21ebde2c`의 caller/guard/exception 세 정의만 AST 원문·hash로
고정하고 현재 helper와 결합한다. 과거 전체 빌드 재현은 아니다. current arm은 guard를
monkeypatch하지 않고 실제 수정 Product를 실행한다.

검증 결과(단일 pytest 프로세스, 실제 모델0):

- 최초 직접 실행: 248 PASS / 2 FAIL. 과거 exception fixture의 `deepcopy` import global이
  빠진 평가 장치 결함이었다. 당시 실패를 숨기지 않고 해당 namespace만 수정했다.
- 수정 후 직접 확인: **250 PASS / 1.29초**. 역사 비교11, Source/Goal/confirmation,
  Tool Route, frozen connected 평가 caller를 포함한다.
- 인접 확대 회귀: **2,098 PASS / 9.89초**. `tests/unit/application/agents`,
  `tests/unit/application/use_cases/run`, `tests/unit/adapters/langgraph`와 위 평가2파일.
  직접 확인과 중복된 검사가 있으므로 두 숫자를 합산하지 않는다. 전체 pytest는 아니다.
- 변경 Python6파일 Ruff check PASS. 신규 평가파일 Ruff format PASS. Product2파일 mypy PASS.
  `git diff --check` PASS.
- active `src/scripts`의 제거된 guard 참조0. 독립 코드 검토에서 다른 Source typed guard,
  선택 identity/confirmation, Output prohibition revision, 실제 dispatch budget 변경 없음 확인.
- 자원 snapshot: RAM 여유19.61/31.71GiB, GPU0/8,188MiB·사용률0%·46°C.
  전체 기간 peak 측정은 아니며 모델 실행과 테스트를 겹치지 않았다.

이전 guard가 요청하던 Source revision1회는 해당 조건에서 없어지지만, 기존 조기차단 요청이
이후로 진행하며 downstream 호출이 늘 수 있다. **전체 tokens/latency 개선은 미측정**이다.

모델/Graph/업무 Provider 신규 실행0. Canonical92 전체의 새 점수는 아직 없으며 061/062나
v44의 숫자를 이번 Product의 점수로 승계하지 않는다. Core/합성/역사 검색 분모도 합치지 않는다.
외부 Provider WRITE/SEND0. 프론트/백엔드 재시작0. 단일 테스트 프로세스만 사용한다.

역사 raw hash:

- 061 `2ee8b74d4c175b96ad70c0eb1456955c7c861d1bf9d1c6d8cb62853af2eb0460`
- 062 v4 `c5dac5ee0c1e6ebea6b4b71c7a3ca5a670d8004b40603e49f800708c5770ef5f`

추가 검토한 fact-origin 3분류 후보는 실행하지 않았다. REQUEST_VALUE와 PLANNED_RESULT는
사용자가 지정한 새 Task 제목처럼 겹칠 수 있으며, 누락된 정보 항목에 origin을 붙일 수는 없다.
동일 모델의 새 라벨을 독립 진실 증거로 취급하지 않는다. v6/v7의 필요정보 재생성 실패와
구분되는 이득이 아직 명확하지 않아 새 model call/Schema/Prompt를 추가하지 않았다.
