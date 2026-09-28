# 065 — READ 답변 handoff 실제 FIRST 결과

실행 SHA `8f0b3627b31a62569cba0e5d2efc28707569ff83`.
Product는 `690a80b3`과 동일하며 새 Prompt/Schema/State 후보는 없다.
사전 범위는 `065-read-answer-handoff-model-criteria.md`다.

## 결과와 의미

| 고정 합성 입력 | 실제 결과 | 판정 | 모델 호출 |
| --- | --- | --- | --- |
| 선택 Calendar 시간 | 2026-08-18 오전10~11시, Asia/Seoul. snapshot 기반 기존 formatter 유지 | PASS | 0 |
| 선택 Calendar 시간+장소 | 첫 응답에 2026-08-18 오전10~11시와 한빛회의실을 모두 포함. compose도 그대로 보존 | PASS | 1 |
| 선택 Task 메모 | 첫 응답이 `장비 수령 항목을 확인할 것.`을 정확히 전달. 제목/상태 답변으로 대체하지 않음 | PASS | 1 |

이번 고정 합성 집합은 **3 PASS / 0 PARTIAL / 0 FAIL**이다. 모델을 실제 사용한
subset은2개이고 나머지는 deterministic control이다. 각1회이며 반복 안정성은 미검증이다.
두 FIRST 모두 원래 schema와 citation 범위를 통과하고 consumer 변환에서도 요청 사실이
손실되지 않았다. 근거 없는 완료/변경 사실이나 불필요 WRITE를 주장하지 않았다.

기존 Task/Calendar 코드 결함은 정보가 있어도 formatter가 이를 생략하고 종료하는
문제였다. 수정 후 기존 semantic owner가 그 정보를 소비할 수 있음을 작은 실제 모델
진단으로 확인했다. 모델 답변을 맞추는 새 규칙·few-shot은 넣지 않았다.

## 실제 실행 조건과 비용

- qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
- Ollama0.34.0; `/api/generate`, think=false, ctx16384, seed20260923,
  temperature=None(모델 기본값1), presence_penalty 기본값1.5. 기본값을0으로 기록하지 않음.
- 실제 application `outline_answer → compose_answer`, 기존 evaluation Prompt assembly 및
  Product Ollama transport. 각 FIRST schema validation과 compose consumer 실행.
- 모델 호출2, repair/retry/model judge/rerun-to-pass0, 직렬 실행.

| 실제 모델 입력 | 입력/출력 토큰 | reported / wall 지연(ms) | load(ms) |
| --- | --- | --- | --- |
| Calendar 시간+장소 | 2,971 / 68 | 11,628 / 11,651 | 7,419 |
| Task 메모 | 2,723 / 40 | 3,129 / 3,139 | 3 |
| 합계 | 5,694 / 108 | 14,757 / 14,790 | 7,422 |

이는 이전 잘못된0-call 종료보다 비용이 들지만 요청 정보를 보존하는 기존 경로 복구다.
2표본의 p95나 일반 성능 향상을 주장하지 않는다. GPU/RAM 경합 방지를 위해 실행 중
편집·pytest·다른 모델 호출을 하지 않았다. 관측 시점의 GPU 메모리6,385MiB/8,188MiB,
온도50°C, 여유 RAM17.91GiB였다(peak 측정이 아님). 추가 서버/모델을 시작하지 않았다.

## 결속 및 범위 한계

- plan file hash `00fd6f33489da6d33660e204bfafcabf68c9b88780c09da41b372eb64e614fb4`.
- fixture hash `57710b95600b218dcd7f660a839709c3e7cb416051776aab946a6b6e2c3b6db1`.
- raw file hash `607b474471238c2fd77e7b30234a7fa3a3d9360925296c40845532ba313caf7a`.
- raw/plan: `evaluation/results/065-read-answer-handoff-t1/` (ignore 대상, 원격 비포함).
  raw FIRST, 실제 wire/Prompt/hash, consumer 결과와 실패 기록을 보존한다.
- 실행 전후 HEAD/source binding 일치, 입력3개 모두 불변. raw의 UNREVIEWED는 실행기가
  의미 PASS를 자동 만들지 않았다는 뜻이다. 위 표는 사전 기준에 따른 별도 의미 검수다.
- harness dry validation9 PASS/1.28초, 변경Python2파일 Ruff/Mypy PASS.
  malformed JSON/schema, timeout, prose repair 요청, seal drift, 재실행 금지를 확인했다.

전체 Main Graph/structured router repair/Canonical92/legacy smoke가 아니다. typed 입력은
합성 고정값이며 실제 RU가 이를 만들었다고 주장하지 않는다. compiled Planning fake2개의
이전 검증과 이번 모델 FIRST2개도 하나의 full Graph 모델 통과로 합산하지 않는다.
upstream Source/Output 판단, live Retrieval, Review·Approval 이후 성공은 여전히 별도다.
Provider READ/WRITE/SEND/승인0, Dataset/Gold/Prompt/제품 코드 추가 변경0.

## 판단 및 다음 선택

기존 formatter 수정의 owner-local handoff 확인은 **유효**하다. 이 결과만으로 Epic 완료나
전체 업무 성공을 선언하지 않는다. 새 Prompt 실험이나 동일 Trial 재실행은 하지 않는다.
다음은 기존 raw/코드에서 남은 의미 전달 결함을 재사용해 조사하고, 직접 근거가 있는
최초 손실 경계만 수정한다. 새로운 모델 호출은 수정 효과를 구별할 필요가 있을 때만
다시 사전 한정한다.
