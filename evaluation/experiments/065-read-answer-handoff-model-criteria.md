# 065 — 수정된 READ 답변 handoff의 bounded 실제 모델 확인

## 가설과 범위

기준 Product `690a80b3`: Task/Calendar formatter가 지원하지 않는 필요정보를 생략하지 않고
기존 `planning.compose_answer`로 넘긴다. 이 전달이 닫힌 뒤, 실제 모델이 주어진 자료에서
요청한 메모·장소를 답할 수 있는지만 확인한다. 새 Prompt/Schema/State 후보 비교가 아니다.

현재 Core RU/Source 오류를 정답 입력으로 교체해 전체 성공으로 세지 않는다. 아래는
고정된 합성 typed Planning input의 owner-local 진단이며, Canonical92/legacy smoke 점수와
분리한다. 앞서 수행한 실제 compiled Planning의 fake handoff 테스트와 실제 모델 FIRST
검증도 구분한다. 이 실행은 application outline/compose와 기존 Prompt assembly/transport를
연결하지만 실제 Main Graph·structured router repair·Live Provider는 실행하지 않는다.

## 고정 집합과 예산

| 합성 진단 | 확인할 의미 | 예상 dispatch |
| --- | --- | --- |
| Calendar schedule control | 선택한 단일 Event의 2026-08-18 10:00~11:00 Asia/Seoul. 정상 snapshot으로 기존 구간 답변 유지 | 0 |
| Calendar time + location | 위 일정 시각과 실제 location=한빛회의실 보존. 없는 저장/수정 사실을 주장하지 않음 | compose FIRST 1 |
| Task notes | 선택한 단일 Task의 notes에 있는 장비 수령 항목 확인 내용을 답함. 제목·상태만으로 대체하지 않음 | compose FIRST 1 |

각각1회, 총 모델 generation 최대2회, 순차 실행, repair/retry0, rerun-to-pass0.
하나의 호출이 timeout/invalid이면 그대로 실패 Trial로 보존하며 성공 Trial로 교체하지 않는다.
모델 judge0. 요청한 사실을 의미상 정확히 전달하면 표현 차이는 허용한다. 일부 누락은
PARTIAL, 엉뚱한 사실/요청 누락/계약 실패는 FAIL. 구조 PASS만으로 의미 PASS라 하지 않는다.
Task/Calendar는 실제 계정이나 Canonical 자료가 아닌 기존 테스트의 명시적 합성 Fixture다.

## 실행 결속

- 실행 전 plan을 생성하고 HEAD·관련 소스/Prompt·fixture·모델 digest와 plan hash를 고정.
- qwen3.5:9b, 실제 Ollama catalog/show/version 기록. Product의 `/api/generate`,
  Structured Output, think=false, num_ctx=16384 사용.
- temperature는 Product Planning과 같이 미지정(None), seed=20260923. 미지정을0으로
  보고하지 않으며 show의 모델 기본값을 함께 기록한다. Timeout은 기존 bounded180초.
- raw FIRST, schema validation, compose consumer 결과, input/output tokens,
  reported/wall/load latency, 실제 wire 입력/hash를 분리 보존.
- 실행 중 코드 편집·다른 모델 호출·pytest 병렬 실행 금지. 결과는
  `evaluation/results/065-read-answer-handoff-t1/`에 보존하고 이전 결과를 덮지 않는다.
- 외부 Provider READ/WRITE/SEND/승인0. 로컬 계정 설정·서버 재시작·Dataset 변경0.

## 판정 후

실패하면 최초 입력/모델 FIRST/consumer 변환을 비교하며, 자동 재호출하거나 사례 규칙을
추가하지 않는다. 모델이 자료를 놓친 경우와 코드가 출력에서 지운 경우를 구분한다.
두 FIRST가 성공해도 upstream 의미 품질·반복 안정성·전체 업무 성공·Release ready를
주장하지 않는다. 호출 증가의 실측 비용도 함께 기록한다.
