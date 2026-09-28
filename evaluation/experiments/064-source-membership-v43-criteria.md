# 064 v43 — exact Source membership → 세부 요구 handoff

## 가설과 범위

v41 지시 축소와 v42 presence 변경은 각각 필수 Source 손실/과선정 회귀로 기각했다.
현재 첫 Source 출력은 Resource 필요성, 필요한 사실, 범위, Work 귀속을 함께 생성한다.
membership과 fact inventory 복사가 함께 변하는 관측은 있으나 원인이라고 입증된 것은 아니다.
이번에는 Source owner 내부에서 **개별 Resource membership 확정 → 그 Resource의 세부
요구 작성**으로 책임을 분리해 어느 단계에서 오판하는지 확인한다.

- Stage1: 원문·원 Goal projection·선택 ref·Work·기존 catalog를 보존하고 각 Resource의
  REQUIRED/NOT_REQUIRED만 exact map으로 반환한다. 모든 key가 필수이며 누락을 NOT_REQUIRED로
  보정하지 않는다. facts/scope/Work를 이 단계에서 생성하지 않는다.
- Stage2: 같은 원 입력과 실제 Stage1의 검증된 membership을 받는다. REQUIRED key 각각의
  `required_information / target_scope / work_unit_ids`만 생성한다. Source 추가·삭제·재선택은
  허용하지 않는다. 선택 0이면 Stage2 호출 0이다.
- 결정적 투영은 명시 membership과 해당 세부값만 기존 Source decision에 전달하며 기존
  Product Source schema/owner validator로 검증한다. 틀린 membership도 그대로 실패다.
- 단계별 일반 책임 설명과 Schema가 함께 달라지는 **하나의 구조 후보**다. 지시 축소나
  exact map 하나의 독립 효과를 입증했다고 하지 않는다. 사례별 규칙/예시/few-shot은 넣지 않는다.

v7은 생성된 need 문자열을 후단의 새 입력으로 삼았지만 이번 후보는 원 입력을 유지하고
새 need를 생성하지 않는다. v15/v18은 family 후 subtype 필요성을 재판정했지만 이번에는
개별 Resource membership을 확정한다. v9 optional key-map은 details까지 한 번에 생성했고,
v28은 같은 Resource의 복수 requirement 표현으로 selection/details 분리를 하지 않았다.
같은 방법의 이름만 바꾼 재시도로 보지 않되, 새 구조의 유효성도 선결론 내리지 않는다.

## 실행 전 고정 집합·해석 기준

Core는 v42의 원 FIRST input 005/009/017/049/059를 그대로 사용한다. v42의 **실제 신규
baseline(default presence=1.5) 5개**만 재사용하며 presence=0 출력은 사용하지 않는다.
기존 report의 의미 기준과 현재 Canonical request/required_semantics/forbidden_semantics를
같이 대조한다. 새 정확 Resource 개수/문장/Tool 순서를 Gold로 만들지 않는다.

| 집합 | 의미와 반례 |
| --- | --- |
| CORE-005 | 선택 Task의 상태·기한, 단일 대상과 Work 보존. Source 증가로 회귀하지 않는지 |
| CORE-009 | 명시 메일+Task 진행 근거 모두 유지. Source 이름만 복구하고 필요한 내용을 잃지 않는지 |
| CORE-017 | Task/Event 사실로 새 Draft 작성. 기존 Draft를 조회해야 한다는 혼동과 필수 Task 손실을 함께 확인 |
| CORE-049 | 명시 메일/Task/Calendar 사실과 신규 복수 결과 역할 구분 |
| CORE-059 | 실제 현재 Canonical은 메일 SEND. Thread/Message 근거 유지, 과거 Quartz Draft UPDATE Smoke를 섞지 않음 |
| SYNTHETIC-DRAFT-UPDATE | 선택 기존 Draft에 literal 편집 및 다른 값 보존. 기존 Draft의 본문/보존값이 필요한 반대 경계 |
| SYNTHETIC-DRAFT-CREATE | 작성값이 충분하고 외부 자료 조회를 제외한 새 Draft. 새 Output을 기존 Source로 고르면 오판 |

현재 Core에는 Draft UPDATE Case가 없으며 CORE-002는 READ다. CORE-058의 Event CREATE와
CORE-057의 Task CREATE에는 각각 conflict/duplicate 검증 Gold가 있어 “READ 0” 정답으로
바꾸지 않는다. 필요한 두 반례는 `064-source-membership-v43-controls.json`의 합성 owner
입력으로 분리한다. 기존 Dataset/Fixture/Gold를 변경하거나 새 Canonical ID를 만들지 않는다.

합성 입력은 Goal을 원문 그대로, 조건을 비워두고 exact Work span 및 가짜 selected ref를
명시적으로 만든 component control이다. 실제 upstream 모델/Provider의 결과라고 하지 않는다.
등록 catalog는 Core와 같은 값을 전달한다. case_id/review/expected/fixture 메타는 Prompt에
넣지 않는다. no-source는 업무 사실 의존성의 판정이지 Approval·권한·정책 검사 생략이 아니다.

정상 Thread/Message 대안이나 parent 경로를 exact-count 오답으로 판정하지 않는다. 필수
Source/내용/단일 대상/Work 손실, 무관한 필수 Source를 각각 기록한다. raw 구조 점수와
Source 의미 점수 및 미실행 업무 결과를 분리하며 **Core5와 합성2의 분모를 합치지 않는다**.

## 고정 예산과 재현

- Core005 → 009 → 017 → 049 → 059: 후보 각 1회, Stage1 + 필요한 경우 Stage2, **최대10 새 호출**.
- 이어 합성 UPDATE → CREATE: 각 baseline1회 + 후보1회(최대2call), **최대6 새 호출**.
- 합계 **최대16 새 호출 / baseline5 재사용**, 모델 동시성1. repair/retry/codec/semantic revision0.
  실패 Trial을 교체하지 않는다. 구조 실패 시 해당 Case Stage2는 실행하지 않고 원 실패를 남긴다.
- 모델은 qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  Ollama0.34.0, temp0.05/seed20260923/ctx16384/think=false/default presence1.5/180초.
  v42의 기각한 penalty override는 사용하지 않는다. 현재 model/version/기본 설정을 재조회해 결속한다.
- input·후보 역할·Schema·PromptRef·wire·실제 Stage1 부모 hash·코드/HEAD·Dataset/Fixture·기준시각/
  fault·과거 baseline 원 row/파일 hash를 plan/raw에 남긴다. execution claim은 배타적이다.
- 첫 raw, 구조 검증, 결정적 투영을 구분한다. 잘못된 필요정보를 validator로 고치지 않는다.
  Generation 전에 호출 기록을 보존하고 단계별 실제 calls/tokens/latency/load를 집계한다.
- 재사용 baseline은 동시 paired 지연 비교가 아니며 모델 load/cache 차이를 일반 속도 효과로
  해석하지 않는다. 합성 baseline은 신규이며 별도 집계한다. 1회 결과는 반복 안정성이 아니다.
- 모델 실행 중 테스트/파일 편집/다른 모델 실행을 겹치지 않는다. 시작·종료 RAM/VRAM/온도를
  확인하고 자원 부족 시 이미 완료한 raw를 보존한다. frontend/backend/E2E 재시작 없음.

## 성공·기각·다음 판단

필수 Source 회복과 기존 성공/역방향 반례 보존이 함께 개선될 때만 실제 upstream 연결과
다중 Work 등 인접 범위를 다음 고정 비교로 넓힌다. Stage1에서 같은 과선정이 지속되거나
Stage2의 정보/범위 손실로 이득이 없으면 호출 증가를 채택하지 않는다. 실패 단계에 case
규칙이나 정답 membership을 주입하지 않고 원인군과 이전 실패 방법을 다시 비교한다.

Product Source·Prompt manifest·Node/State/activation·budget/권한/승인 계약 변경 0. Canonical15에
비활성 구조 비교 범위만 선언한다. Graph/업무 Provider/WRITE/SEND0, Holdout/Stress 튜닝0,
전체92 실행0. 이번 FIRST 진단만으로 Production migration이나 최종 업무 PASS를 선언하지 않는다.

## 실행 전 직접 검증

후보·실행기·기존 format 진단 회귀를 한 pytest 프로세스로 실행해 **145 PASS / 20.67초**.
Ruff check/format, mypy(`--explicit-package-bases`) PASS. 실제 보존 raw와 현재 metadata를
사용한 memory-only dry plan도 Core5/합성2/신규최대16/기존baseline5 결속을 통과했다.
이 준비 단계의 신규 모델 generation/Graph/업무 Provider는 0이다. 독립 읽기 검수에서
Gold 미유입·closed handoff·partial 기록·재실행 차단을 확인했으며 의미 개선은 아직 미검증이다.
