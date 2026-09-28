# 064 v42 — Source presence penalty 단일 변수 진단

## 가설과 실행 전 근거

v41의 지시 축소는 필요한 Source/선택 범위가 회귀해 REJECT다. 이를 기반 Prompt로 쓰지 않는다.
이번에는 원래 Product Source Prompt와 실제 historical FIRST 입력을 그대로 사용한다.

실제 Ollama 0.34의 qwen3.5:9b 모델 설정은 presence_penalty=1.5이고 Source wire에서는
이 옵션을 보내지 않는다. 현재 llama-server의 v41 5개 sampling 로그에도 presence=1.500,
frequency=0, repeat_penalty=1, repeat_last_n=64가 관측됐다. 예전 Go runner가 옵션을
무시했다는 과거 보고를 현재 버전의 사실로 사용하지 않는다. version-pinned 구현과 실제
backend 로그의 소비를 별도 runtime audit로 보존한다.
근거 문서는 `064-source-sampler-runtime-audit.md`이며 계획의 hash 결속에 포함한다.

동일 키/enum/사실을 반복해야 하는 structured 출력이 penalty 영향을 받는지는 아직
가설이다. Source 누락이나 새 Output/기존 Source 혼동의 원인이라고 선결론 내리지 않는다.
기존 v31은 prohibition temperature 비교이며 presence는 양 arm 모두 모델 기본값이었다.
기존 raw/문서에서 Source presence만 통제한 비교는 발견하지 못했다.

## 비교 동조건 확인에 따른 실행 전 확정

원래 고려한 역사 baseline 재사용은 실행 전에 철회한다. 과거 3개 plan/calls에는 Ollama
version/backend build/개별 호출 wall timestamp가 없고, 서버 로그와 exact wire의 결속도 없다.
모델 digest/입력이 같아도 penalty의 인과 비교에서 backend까지 같다고 간주하지 않는다.
아직 v42 generation/실행 plan 생성은 0인 시점에 **현재 baseline 5 + 후보 5**로 확정했다.
기존 5개 raw는 입력 출처와 역사 참고이며 이번 paired 점수·호출량 합산에서는 제외한다.

## 고정 범위

- Core005 → 009 → 017 → 049 → 059, 각 Case의 현재 baseline/후보를 각 1회 **신규 최대 10회**.
  005 기본값→0, 009 0→기본값, 017 기본값→0, 049 0→기본값, 059 기본값→0 순서다.
- 원 출처·각 Case 입력·해석 기준은 `064-source-concise-v41-criteria.md`와 동일하다.
  그 파일의 축소 Prompt는 사용하지 않으며 의미 기준/데이터만 재사용한다.
- Baseline은 같은 원 payload 그대로 새로 실행하고 Candidate만 `options.presence_penalty=0.0`을 명시한다.
  baseline의 미전송/default 1.5를 explicit 0이라고 표기하지 않는다.
- Product Source instruction/PromptRef/hash, input, output Schema, top-level format,
  temperature 0.05, seed 20260923, ctx 16384, think=false, timeout 180초 모두 유지한다.
  후보는 sampling arm 이름과 실제 wire/config hash로 구별한다. Prompt artifact는 바뀌지 않는다.
- 모델 digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
  실행 전 실제 model/show·HEAD·코드·Dataset/Fixture·원 row/wire hash를 plan에 다시 결속한다.
  현재 `/api/version` 응답도 결속하고 신규 dispatch UTC 시각을 raw에 기록한다.
  이 시각은 Fixture reference time과 구별하며 Prompt/input에 넣지 않는다.
- strict JSON/Schema/기존 Source owner validation 사용. repair/retry/codec/semantic revision 0.
  Graph와 실제 업무 Provider 호출, WRITE/SEND 0. 원 upstream 의미를 Gold로 고쳐 넣지 않는다.

## 평가와 자원

005의 selected SINGULAR, 009의 mail+Task 상태 근거, 017의 Task/Event 충돌 근거,
049의 mail/Task/Calendar 사실과 새 Output의 구분, 059의 기존 Reply 근거를 같은 기준으로
검수한다. required_information의 exact 표현이나 Resource 개수는 Gold가 아니다.
필수 Source/내용/Work/범위 손실과 불필요 Source를 따로 기록하고, 구조·의미·실제 업무를
분리한다. 기존 v41의 역사 baseline 2 PASS/2 PARTIAL/1 FAIL은 이번 새 baseline 점수로 승계하지 않는다.

현재 baseline vs 후보의 raw 첫 출력/검증값, 호출·토큰·지연·load와 누락 usage를 기록한다.
같은 SHA의 직렬 paired라도 cache/load 차이는 남으며 이를 penalty의 효과로 단정하지 않는다.
1회 성공을 반복 안정성으로 취급하지 않는다. 미실행 downstream을 PASS로 채우지 않는다.

모델 동시성 1. 실행 중 pytest/다른 모델/파일 편집을 멈추고 RAM/VRAM/온도를 시작·종료에
확인한다. 자원 부족이면 원 결과를 보존하고 추가 dispatch를 보류한다. 실패를 재실행하거나
성공 Trial로 교체하지 않는다. 유력하지 않으면 penalty 수치를 연속 탐색하지 않는다.

## 판단

명시 Source/선택 범위/불필요 acquisition이 악화되면 채택하지 않는다. 유력하면 먼저
독립 성공·반례 및 실제 upstream 연결을 검증하며 5개 FIRST만으로 Product runtime을 바꾸지 않는다.
새 실패가 남으면 처음 값이 달라진 경계와 기존 실패군을 비교하고 다음 근거 있는 축을 선택한다.
Prompt activation, Holdout tuning, 전체 Canonical92, Provider 실행은 이번 범위에 없다.

## 실행 경로

준비 명령은 generation 없이 metadata/plan만 만든다. code/criteria/audit를 커밋해 동결한
뒤 생성하며 두 번째 명령에는 첫 명령이 출력한 object hash를 그대로 전달한다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_output_format_ablation --owner source --candidate-mode presence_zero --result-dir evaluation/results/064-source-presence-v42-plan
.venv/Scripts/python.exe -m scripts.evaluate_output_format_ablation --owner source --candidate-mode presence_zero --result-dir evaluation/results/064-source-presence-v42-t1 --execute-plan evaluation/results/064-source-presence-v42-plan/preregistered-plan.json --expected-plan-sha256 <printed-plan-object-hash>
```

동일 plan의 성공/실패/부분 결과는 exclusive claim으로 재실행하거나 덮어쓰지 않는다.

## 실행 전 도구 검증

runner 직접 테스트 106 PASS(14.00초), 이후 UTC alias의 스타일 수정 관련 5 PASS(1.61초),
Ruff check/format·mypy PASS. 집계는 중복 합산하지 않는다. fresh10/reused0/history5 미집계,
교차 순서, 원 Prompt 불변, 옵션 한 키, version/hash drift 거절, strict-only 및 기존 모드
보존을 합성 HTTP로 확인했다. 이 단계의 실제 API 조회·모델·업무 Provider generation은 0이다.
