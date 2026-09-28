# 079 — final 응답 복구와 의미 안정화는 다름

**REJECT / Product 미반영.** 078에서 빈 final을 만든 think=true wire의 top-level format만
생략했다. 고정4건 중3건 실행, 세 번째 strict admission 실패로 마지막1건은 미실행이다.
최종응답은3/3 도착했지만 **계약+의미 통과는1 PASS /0 PARTIAL /2 FAIL**이다.

| 부분 Source 판단 | 076 같은3건 →079 | 최초 실패와 실제 결과 |
| --- | --- | --- |
| 049 TASK | FAIL→FAIL | CRITERIA 및 '기존' 표현은 복구했지만 필요한 제목·기한을 '기존 인계 작업'에 귀속했다. 원문은 기존 Atlas 작업들을 보고 **새** 인쇄소 인계 작업을 만들라는 요청이다. |
| 005 TASK | PASS→PASS | 선택 TASK의 SINGULAR/work-1과 due/completion_status 유지. 불필요 title/notes는 제거. |
| 017 GMAIL_DRAFT | PASS→FAIL(structure) | SOURCE_NOT_REQUIRED는 맞았지만 required_information=[],target_scope,work_unit_ids를 추가해 oneOf/추가필드 금지 위반. |
| 합성 Draft UPDATE | 비교 제외 | 사전 중단 조건에 따른 NOT_DISPATCHED, 실패나PASS로 세지 않음. |

049 fixture의 기존 자료는 QR 문구 확정·알레르기 라벨 검토 Task이고 인계 Task는 초기
부재다. Source의 자연어 required_information에서 새 결과와 기존 근거의 대상이 다시
섞인 것이므로 단순 문구 차이로 PASS 처리하지 않는다. 다만 Query/Provider까지 실행하지
않았으므로 실제 조회 누락을 관측한 것처럼 보고하지 않는다.

FIRST 원출력과 검증값은 유효한2건 모두 동일하다. 017은 HTTP 오류가 아니라 final
도착 후 계약 거절이며 원문·usage를 남겼다. 해당 필드를 삭제해 PASS로 만드는 보정0.
membership 문장만 보면3/3이지만 **strict구조3/3→2/3, 구조+의미2/3→1/3**으로 회귀했다.

## 같은 분모의 비용

| 비교 | calls | input/output tokens | reported latency | wall latency |
| --- | ---: | ---: | ---: | ---: |
| 076 frozen 같은3개 | 3 | 11,260/157 | 12,808ms | 12,858ms |
| 079 신규 | 3 | 11,254/8,763 | 289,578ms | 289,703ms |

지연합은 약22.61배다. 단발 비동시 비교이며 일반 성능 배율로 보장하지 않는다.
output은 숨겨진 추론 포함 provider 생성량이고 최종JSON 길이가 아니다. load합은25ms와
21ms, usage누락0. raw의4개 historical reference 집계에는 미실행UPDATE가 있으므로
동일분모비교에 그대로 사용하지 않았다. 078의1회실패도 별도로 보존했다.

## 조건·판단

- SHA `ab8ed19162e8c072b89a1d8fb13651e6ddfabaac`, plan전후binding같음.
- qwen3.5:9b/Q4_K_M,digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  Ollama0.34.0/temp0.05/seed20260923/ctx16384/think=true/stream=false/format미전송.
- runtime 외 역할·본문Schema·원문·Goal조건·catalog·Work·focus 동일.
  실제 wire에format을 재삽입하지 않고 검증용 임시 사본만 분리했다.
- 직접harness118PASS,scopedRuff/mypyPASS. Canonical92평가/전체pytest0.
- concurrency1,생성중편집/pytest0,관측GPU6,383MiB/최대관측72°C.
  종료6,385MiB/0%/49°C. retry/repair/rerun-to-pass/Provider/Approval/WRITE0.

이번조건에서는 format생략 후 final을 받았으므로 '긴 입력에서는 reasoning이 무조건
불가능하다'고 말하지 않는다. 그러나 decoder/parser중 정확한 내부 원인까지 확정하지
않았고, 의미 회귀·Schema실패·지연비용 때문에 Product설정을 변경하지 않는다.
전체Source/RU→ToolRoute/Graph/업무성공·반복안정성·학습효과는 미검증이다.

공식 [structured outputs](https://docs.ollama.com/capabilities/structured-outputs)와
[thinking](https://docs.ollama.com/capabilities/thinking)은 format 및 분리된 final의 계약
참고자료이며, 위 결론은 타버전issue가 아닌 이번 고정wire 실제관측에 근거한다.

## 재현

- plan `evaluation/results/079-source-focal-reasoning-format-plan/preregistered-plan.json`,
  objecthash `230337e2eb446b347014bfda1a944460646d72e87807c6600a753fa75466c4e3`.
- raw `evaluation/results/079-source-focal-reasoning-format-t1/raw.json`, byteshash
  `6dacf447eaf6269c4c0d583b56785f75dfb841b0d45c176976f4835b9ab8dc65`.
- Dataset/Fixture/current-source/Prompt/Schema/model/각Case시각은plan결속.
  상세raw는로컬ignore영역, 이문서는원격리뷰용비민감요약이다.
