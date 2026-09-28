# 064 v44 — 기존 Source 계약의 대조 예시만 비교

## 가설·새 비교 근거

v43의 membership/details 분리는 기존 Draft 오선택과 신규 작성값→기존 사실 혼동을
해결하지 못했고, 목록을 SINGULAR로 좁혔다. 실제 FIRST가 이미 잘못됐으며 materialize가
정상 값을 변형한 증거는 없다. 현 Source schema에는 필요한 Source와 CRITERIA 및 자유로운
필요 정보 표현이 있어 이번 오류를 표현 불가능으로 단정하지 않는다.

003의 Goal constraints 제거는 의미1/6→1/6과 필수 Source 누락으로 기각됐다. 이 축은
반복하지 않는다. 보존 실험/후보/코드 검색에서 Source dependency owner의 입력·Schema·
기존 role을 유지한 contrastive 입출력 예시만 비교한 기록은 찾지 못했다. 043 SourceStatus,
043/044 Output, 048/050 Work decomposition 결과는 이 owner의 근거로 승계하지 않는다.

이번 가설은 기존 설명에 이미 있는 구별 기준을 일반 입출력 예시로 보여 주면 Source
역할/범위 선택이 개선되는가이다. **원 Product one-call role + 소수 예시**만 바꾼다.
기각된 v43 분리나 v41 간결화/v42 penalty를 합치지 않는다. 새 규칙·field·Node·Schema,
Goal 제거, runtime 변경, validator 보정은 없다. 사례 예시 추가를 무한 반복하지 않는다.

예시는 제공값만으로 새 Draft 작성 / 선택 기존 Draft 일부 편집 / 복수 기존 Task·Event
내용으로 새 Draft 준비의 일반 경계다. 고유 프로젝트명·실제 Fixture·Core 원문/Gold를
복사하지 않는다. 예시 결과는 현재 Source schema/owner를 통과해야 하지만 평가 정답을
제품에 주입하는 용도가 아니다. 실제 현재 Run input은 변경하지 않는다. 예시가 어떤
효과를 냈는지는 raw 결과로 확인하며 채택을 선결론 내리지 않는다.

## 고정 집합·예산

v43과 동일 Core005/009/017/049/059 및 별도 합성 Draft UPDATE/CREATE를 각 후보 1회.
Core는 v42 default FIRST5, 합성은 v43 baseline FIRST2를 exact wire/input/Prompt/model/
Dataset/Fixture hash 검증 후 재사용한다. v43 후보 결과를 baseline으로 사용하지 않는다.
**신규7 calls / baseline7 재사용 / trial1 / 동시성1 / repair·retry·codec·rerun0**.
qwen3.5:9b digest6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7,
Ollama0.34.0, temp0.05/seed20260923/ctx16384/think=false/기본presence1.5/180초.

원문/Goal/선택ref/Work/기준시각/catalog/schema/format/options를 그대로 유지하고
system의 기존 role 뒤·기존 context 앞에 예시만 추가한다. 후보 PromptRef는 실제 합성
role+예시의 hash로 결속한다. HEAD/code/criteria/examples/baseline row/wire를 봉인한다.
실제 generation 전에 partial을 저장하고 timeout/실패도 남긴다. 기존 plan의 재실행을
배타적으로 차단한다. 모델 실행 중 테스트·파일 편집·다른 모델 실행을 겹치지 않는다.
시작·종료 RAM/VRAM/온도 snapshot을 남기되 peak/다른 프로세스의 사용으로 단정하지 않는다.

## 평가·중단 기준

현재 Canonical 원문과 required/forbidden semantics, v43에 고정한 의미 기준을 사용한다.
Core5와 합성2 분모를 합치지 않는다. Source 이름/개수/Tool 순서만으로 PASS하지 않는다.

- 005: 선택 Task 상태·기한, 단일 대상 유지.
- 009: 메일과 Task의 진행 근거 둘 다 보존.
- 017: 현재 Task 목록과 Event 사실 → 새 Draft. 기존 Draft 조회 혼동/목록 축소 금지.
- 049: 기존 메일/Task/Calendar 사실과 새 Task/Event/Draft 결과의 역할 구별.
- 059: 실제 Canonical reply SEND의 메일 내용/이력. 과거 Draft UPDATE를 섞지 않음.
- 별도 합성 UPDATE: 현재 선택 Draft 본문/보존값 조회 필요.
- 별도 합성 CREATE: 명시 입력값과 조회 제외 보존. Source0은 Policy/Approval 생략이 아님.

첫 구조·첫 의미·미실행 업무 성공을 분리한다. 정상 parent/대안 Source를 개수만으로
감점하지 않고 필요한 사실·scope·Work 손실 및 무관한 필수 조회를 각각 기록한다.
기존 PASS 회귀나 신규 역할 혼동이 남으면 전체 채택하지 않는다. 개선이 명확하면
실제 upstream 연결/다중 Work/반대 경계를 고정한 다음 비교로 넓힌다. 효과가 없으면
예시를 늘리지 말고 첫 손실 책임과 미검증 축을 재검토한다.

재사용 baseline은 동시 paired 지연이 아니므로 load/cache 영향을 인과 효과로 보고하지
않는다. 호출/입출력token/실제latency를 그룹별로 제시하고 1회 결과를 안정성이라 하지 않는다.
Product/활성Prompt/State/Node/승인·실행 계약 변경0. Graph/Provider/WRITE/SEND0,
Holdout/Stress tuning0, 전체92 실행0. Source-only 진단을 RU→Route 또는 최종 업무 성공으로
표현하지 않는다. raw는 evaluation/results에, 비민감 결론은 추적 보고서에 남긴다.

## 실행 전 직접 검증

후보·실행기 및 기존 membership/format 회귀를 단일 pytest 프로세스로 검사해
**175 PASS / 35.28초**. Ruff check와 두 새 모듈 mypy PASS. 이는 입력·Schema·wire 보존,
예시 계약, 실패 raw·exclusive claim 검증이며 모델 의미 개선은 아직 검증 전이다.
