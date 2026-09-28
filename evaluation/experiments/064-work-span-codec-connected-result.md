# 064 v35 — 동일 Work FIRST의 원문 결속과 실제 후속 연결

## 기준·범위

- 실행 HEAD: `3142c5c3636aa02ef53925c699d6d75c570d2f50`.
- Trial: `584561c8-e8fb-4445-b0c9-08431889be88`.
- 사전 기준: `064-work-span-codec-connected-criteria.md`.
- 005/017/049 × Production / codec 각 1회, 총 6 arms. 실패 대체·추가 모델 retry 0.
- 모델 `qwen3.5:9b`, digest
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  seed20260923, ctx16384, think=false, local timeout180초.
- 실제 sampling: Goal0.1, Source0.05, Output/ambiguity0.0. Work/금지/status/temporal은
  temperature 미전달(None)이며 0이라고 기록하지 않는다.
- Dataset/fixture/Prompt/schema/runtime/Case별 reference time은 immutable plan에 결속.
  과거 v4 공동 Goal/Output 또는 v34 token-ref 변경은 사용하지 않았다.
- 실제 snapshot composition과 Product RU/Tool Route, admission/Run budget을 사용했다.
  Retrieval/Planning/Approval/Execution은 실행하지 않았다.

## 판정

| Case | Production | codec | 최초 다른 경계 / 남은 의미 오류 |
|---|---|---|---|
| 005 | 연결 완료, 의미 FAIL | 연결 완료, 의미 FAIL | Work FIRST/typed Work는 동일. 양쪽 Output FIRST가 단순 Task 조회에 TASK UPDATE와 GMAIL_MESSAGE SEND를 추가했다. CREATE 금지는 둘 다 보존됐다. |
| 017 | Work 문자열 결속에서 중단, 이후 의미 미관측 | 연결 완료, PARTIAL | 같은 Work FIRST의 띄어쓰기만 원문에 결속해 Goal/Source/Output/Route까지 전달했다. Task+Calendar와 Draft CREATE/날짜/수신자는 보존하지만 Source FIRST가 별도 필요성이 없는 기존 GMAIL_DRAFT/SINGULAR을 필수로 추가했다. 실제 조회 차단 여부는 미검증이다. |
| 049 | Work 문자열 결속에서 중단, 이후 의미 미관측 | 연결 완료, 의미 FAIL | 같은 Work FIRST를 정확한 원문에 결속했다. Goal FIRST가 Task의 `13시까지`를 해당 시각 생성 완료조건으로 바꾸고 `scheduled_date=2026-08-13T14:00:00+09:00`을 추가해 final State에 남겼다. 세 CREATE 결과는 보존됐지만 Task 시간과 Event 종료 역할이 섞였다. 기존 Draft 과잉 Source도 남았다. |

구조 연결은 **1/3 → 3/3**, gate 종합은 **0 PASS / 0 PARTIAL / 3 FAIL →
0 PASS / 1 PARTIAL / 2 FAIL**이다. baseline017/049의 FAIL은 구조 실패이며 아직
실행되지 않은 semantic owner까지 오답이라고 추정한 숫자가 아니다.

017의 추가 READ만으로 전체 업무 실패라고 단정하지 않았다. 필요한 Source/Output은
보존됐지만 잘못된 필수 의존성이 추가된 PARTIAL이다. 049의 미래 완료조건을 승인 전
실제 Provider 생성이 완료됐다는 현재 사실 주장으로 분류하지 않았다. 문제는 시간 역할이다.
Work 개수 하나나 exact Tool 순서를 Gold로 사용하지 않았다.

## 인과·회귀·호출 비용

세 Case의 양 arm Work FIRST는 input/content/schema/PromptRef/wire hash/options가 모두
동일하다. 따라서 exact-string-only admission → selector materialization의 구조 효과는
구분된다. 기존 raw21개 재판정(14 accepted typed 불변, 7 공백 결속 복구)과 일치한다.

005의 Goal 입력부터는 새 Run의 selected-ref UUID가 다르다. Provider Task/parent는 같지만
후속 Goal/Source 입력은 bit-identical하지 않다. Production만 근거 없는 INCOMPLETE
source filter를 추가하고 codec에서는 사라진 차이를 codec의 의미 개선으로 세지 않았다.
codec은 금지·상태·Source·Output을 생성하지 않는다.

| 실제 측정 | Production | codec |
|---|---:|---:|
| LLM dispatch / actual wire | 9 / 9 | 22 / 22 |
| input tokens | 19,826 | 66,509 |
| output tokens | 793 | 2,526 |
| provider-reported LLM latency 합계 | 45,653ms | 127,033ms |
| arm wall latency 합계 | 50,734ms | 133,609ms |
| repair / usage 누락 | 0 / 0 | 0 / 0 |

Production017/049는 Work 1call 뒤 중단했으므로 위 합계를 동일 업무의 성능 저하/향상으로
해석하지 않는다. 005는 7→7calls이고 wall40,984→32,375ms이나 한 paired trial의
고정 순서·cold/warm·후속 입력 변동이 있어 지연 개선을 확정하지 않는다.
Provider READ/WRITE/SEND 및 해당 dispatch attempt는 모두 **0**이다.

31개 input hash와 dispatch/wire/usage 일치, 6개 raw hash를 확인했다. 원 raw의
UNREVIEWED 표식은 유지하고 이 문서에서 별도 의미 판정을 기록한다. 과거 실행 결과를
성공으로 덮어쓰거나 이번 결과를 Canonical92/최종 업무 성공률로 승계하지 않는다.

## 판단과 다음 owner

**Work selector→exact provenance 경계만 ADOPT 후보.** Product 반영은 fresh RU에
한정하며 기존 persisted provenance validator·Confirmation·reconsideration을 확장하지 않는다.
Source/Output/Goal 의미 품질을 함께 채택했다고 주장하지 않는다. 후속 실제 Product
구현·직접 회귀 결과와 채택 commit은 별도로 남긴다.

남은 실패군은 기존 Output의 요청하지 않은 WRITE, Source의 Output/기존 자료 혼동,
Goal의 시간 역할 변형이다. 원문과 Work가 이미 제공된 실제 FIRST에서 발생하므로
원문 추가나 downstream 단어 보정으로 해결됐다고 할 수 없다. 새로운 후보 전에 현재
Goal/Source/Output 입력/authority와 이미 기각된 방법의 차이를 확인한다.

자원은 RAM31.7GB 중 시작 시20.3GB 여유, RTX4060Laptop8GB에서 모델 순차1개였다.
관측 GPU 사용 약6,385MiB, 온도 최대 관측67°C. 모델 중 pytest/mypy를 겹치지 않았고
다른 사용자 프로그램을 종료하지 않았다.

## 로컬 원 근거

- `evaluation/results/064-work-span-codec-v35-connected-t1-plan.json`
  SHA256 `4163a93be350fc02b38b5505a1a938dd79fd8d6a3e9488e9b13d716424518ff4`.
- `evaluation/results/064-work-span-codec-v35-connected-t1/{CASE-ID}/{arm}/raw.json`,
  `calls.json`, `summary.json`.
- 상세 raw는 기존 ignore 정책상 로컬에만 있고, 원격에는 이 비민감 요약·실행기·사전 기준이
  남는다. 전체 raw가 필요하면 별도의 안전 projection 전달이 필요하다.
