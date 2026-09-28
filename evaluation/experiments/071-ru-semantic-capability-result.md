# 071 — Schema 없는 해석에서도 시간·대상 관계 변형이 남음

판단: **capability control 완료 / Product 미채택**. 입력 부담을 줄이면 일부 Source 누락은
줄어들지만, Product Schema가 오류의 유일한 원인이라는 가설은 지지되지 않는다.
전체 LangGraph 안정화 완료나 모델 한계/LoRA 필요성의 확정 근거가 아니다.

## 실제 실행과 범위

실행 SHA `292fe99a28519d6916fb571f522df6b784c5086a`. 사전 기준
`071-ru-semantic-capability-criteria.md`대로 Core005/009/017/049/059 FIRST를 각1회 실행했다.
원문·selected refs·기준시각만 입력하고 생성 Goal/Work/catalog/Schema는 제외했다.
모델과 sampling을 바꾼 결과가 아니다. 5/5 완료, repair/retry/rerun0, 종료 binding 동일.

역사 Source 기준은 `e9a09524f398b6e6f34b841fbdb239ed930fc32f`의 v42 FIRST5다.
현재 assembler의 전체 wire·Schema·validator 결과와 원 기록의 일치를 먼저 재구성했다.
Source-only와 자연어 전체 설명은 다른 task이므로 양쪽 점수를 같은 Product 성공률로
직접 승계하지 않는다. 역사2 PASS/2 PARTIAL/1 FAIL은 그대로 보존한다.

## 의미 관측

| Core | 자연어 해석 | 최초 출력에서 확인한 보존·변형 |
| --- | --- | --- |
| 005 | PASS | 선택 Task exact identity, 상태·기한만 답변, 새 작업 생성 금지 보존. 실제 상태/기한을 지어내지 않음 |
| 009 | PASS | 메일과 작업 기록을 근거로 진행 상황을 알려달라는 뜻 보존. 역사 Source에서 빠진 Task 근거가 자연어에서는 남음. 새 행동을 요청한 것으로 바꾸지 않음 |
| 017 | FAIL | Task/Calendar와 Draft 수신자는 유지하지만 현재 작업 목록을 '현재 진행 중인 작업', '8월12일에 예정된' 자료로 축소. 실제 입력 `2026-08-07T09:00:00+09:00`을 오후9시로 변형 |
| 049 | FAIL | 세 input 종류와 Draft 수신자를 보존하나 Task 기한을 '인계 시작(오후1시)'으로 재해석. 최종 결과 설명이 '일정표 생성'으로 축약되고 담당자 직급 등을 필수 정보로 추가 |
| 059 | PASS | 확인 완료 사실을 알리는 답장과 즉시 발송 의미 보존. 실제 발송했다고 주장하거나 Draft 전용으로 축소하지 않음. 정확한 Reply identity binding은 이 진단에서 미검증 |

자연어 해석 **3 PASS / 0 PARTIAL / 2 FAIL**, 독립 재검수도 동일하다. 049의 일정이라는 단어만으로 실패 처리한
것이 아니라 **기한과 시작의 관계를 바꾼 명시 문장**이 근거다. Work 개수/분해 모양은
채점하지 않았다. 005/009/059의 PASS는 조회·작성·발송 성공이 아니라 요청 이해 범위다.
017의 실제 조회 filter나049의 실제 Event/Task Route 생성은 실행하지 않았으므로
downstream에 그 결과가 발생했다고 주장하지 않는다.
009의 '작업 로그 또는 기록'은 자유 한국어에서 타당한 표현으로 허용했다. 049의 '발송할
메일 초안'은 여전히 Draft 목적이므로 SEND 추가로 오판하지 않았다. 059도 첫 문장의
'작성'만 보지 않고 뒤의 명시적 '즉시 발송'까지 확인했다.

5건 모두 필요한 Source의 큰 종류는 자연어에 남고, 기존 Draft를 Source로 반드시
읽겠다는 혼동도 보이지 않는다. 그러나 범위·시간·결과 관계 손실 때문에 이것을
Source 계약5/5 또는 전체 의미5/5로 집계하지 않는다. 불필요 WRITE를 실제 실행한 건0이며,
새로운 외부 행동을 명시적으로 추가한 관측0이다. 049의 결과 유형 축약 위험은 별도 실패다.

## 비용·검증

| 실행 | calls | input/output tokens | reported latency |
| --- | ---: | ---: | ---: |
| 역사 Source FIRST 재사용 | 5 | 20,442 / 1,119 | 51,211ms |
| 신규 자연어 control | 5 | 855 / 1,011 | 39,503ms |

신규 wall합39,559ms/load합6,288ms, usage 누락0. 과제와 출력 계약·첫 load가 다르므로
이 차이를 Product 속도 최적화나 Schema 단독 인과효과로 해석하지 않는다.
qwen3.5:9b/Q4_K_M, digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
Ollama0.34.0, temperature0.05/seed20260923/ctx16384/think=false/stream=false.
presence override 없음(모델 default1.5). 원 기준시각은 Case별 원 입력 그대로 보존했다.

직접14+기존 기록/카탈로그/format 검사127 = **141 PASS**, Ruff/mypy PASS.
generation 직렬1, generation 중 편집/pytest0. 시작 GPU0MiB/47°C/RAM여유19.60GiB,
중간6377MiB/63%/65°C, 후속 snapshot6377MiB/0%/43°C/RAM여유17.65GiB.
이는 peak 측정이 아니라 snapshot이다. 서버 재시작·다른 process 종료0.

Product/활성Prompt/State/Schema/Graph/Dataset 변경0, 외부 Provider READ/WRITE0,
Approval0, 실제 LangGraph0. 현재 HEAD의 전체92 품질은 새로 측정하지 않았다.

## 근거와 다음 선택

- plan object hash `02c7e98248cb2320a51ba6fcc91980fd397d59a9702da6003d91733474c93285`:
  `evaluation/results/071-ru-semantic-capability-plan/preregistered-plan.json`.
- raw bytes hash `fe18703f5bc62bdd7b0be56f615d248d22df1fd81f4abb0ff4a99d853796c9df`:
  `evaluation/results/071-ru-semantic-capability-t1/raw.json`.
- Dataset `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`;
  fixture `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.

071은 과거070의 '새 비교 근거 없음' 판단 이후 기존 실험의 실제 입력을 다시 대조해
찾은 미검증 경계다. 과거 Prompt 안 Schema를 남긴 format 제거와 동일하다고 보지 않는다.
하지만 이번에도 잘못된 의미가 나오므로 그 자연어를 확정 authority로 Source에 넘기는
구조부터 만들지 않는다. **072에서는 같은 짧은 자연어 입력에서 think=true만 대조**한다.
과거 무거운 Source 구조에서 timeout한 조건과 구분하며, 오류군2+기존 성공1을 사전 고정한다.

LoRA/전체 Node 개편도 배제하지 않는다. 현재 로컬은 RTX4060 8GB이고 학습 환경·독립
train/dev 자료가 없다. Unsloth의 공식 Qwen3.5 안내는 bf16 LoRA 예시를2B 약5GB,
9B 약22GB로 제시하고4bit QLoRA를 비권고한다. 이는 이 PC의 실제 학습 검증 수치가 아니다.
[공식 안내](https://unsloth.ai/docs/models/qwen3.5/fine-tune).
9B 학습이 필요하다고 단정하거나 작은2B 적응 결과를9B 개선으로 승계하지 않는다.
설치/다운로드/학습0, Canonical Gold·Holdout·Stress 학습0이다.
