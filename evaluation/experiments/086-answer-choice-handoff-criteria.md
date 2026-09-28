# 086 — 084 양식 선택의 실제 Planning·terminal handoff

## 동결 범위

084의 세 입력 × 두 FIRST, 총 여섯 응답을 그대로 재생한다. 신규 LLM/Provider/WRITE 0,
repair/retry 0이다. 원 raw SHA256은
`3ce662090733ad1d7c8811a566f8f4541514198463212b69615540beca6a8a1b`다.
wire byte 순서/객체 hash/input/출력 schema를 검증하며 이전 결과·점수를 변경하지 않는다.

082 `replay_case`/ObservedStore/compiled Planning/Answer artifact owner/terminal intent를
그대로 재사용한다. 평가 모듈이 참조하는 materializer 심볼만 scoped 주입하며 Product 함수와
082 원본을 수정하지 않는다. 084 sealed mode-first schema 검증 뒤 083 양식 materializer와
기존 Product compose validator를 통과한다. 자동 fallback이나 새 응답 생성은 없다.

CORE005는 082가 봉인한 067 pre-Planning checkpoint를 같은 read-only loader로 읽는다.
합성 completed/정리 입력은 historical Run이 아니라 synthetic ANSWER route fixture이다.
실제 outline→compose projection이 저장 입력과 전체 일치해야 하며 sections가 사용자 원문과
다르면 이를 덮어쓰지 않고 실패로 남긴다. 각 입력을 새 in-memory component Run으로 복사한다.

## provenance와 성공 조건

양식 두 종류 모두 현재 component Run/handle/version으로 resolve한 원 Task snapshot에 결속한다.
이번 고정 여섯 응답은 모두 해당 snapshot에서 생성되었으므로 PROSE도 snapshot 누락·다른 Run·
stale/hash mismatch라면 성공 처리하지 않는다. 이는 일반 PROSE의 새로운 snapshot 필수 정책이
아니라 저장된 응답의 replay provenance 검사이다. 승인 ref/enum/date/hash 검증은 기존 renderer와
Product 소비 경계를 유지한다. 다른 Resource 자료나 원문 분석의 일반화는 주장하지 않는다.

각 응답은 semantic adapter를 정확히 한 번 소비하고, Product final_result와 084의 validated
draft가 정확히 같아야 한다. Answer artifact identity는 새 component Run에 속해야 한다.
Terminal ANSWER_DRAFT 본문은 동일하며 terminal composer 호출은 0이어야 한다.
원 snapshot/요청/응답은 변경하지 않는다. 빈 refs 선택은 정상 미발견 답변으로 바꾸지 않는다.

component PASS는 답변 내용의 의미 PASS가 아니다. 의미는 항상 NOT_EVALUATED이며 084의
독립 의미 검수와 구분한다. 실제 Main/Supervisor merge/DB commit/UI delivery, 새로운 RU,
일반 ANSWER eligibility 및 Production 활성화는 검증하지 않는다.

새 전용 results 디렉터리에 시작 상태를 먼저 기록하고 각 replay의 성공·실패를 보존한다.
시작/끝 HEAD, 역사 raw/DB와 Product/helper/support hash 변화 시 전체 gate는 FAIL이다.

```text
python scripts/verify_answer_choice_handoff.py --result-dir evaluation/results/086-answer-choice-handoff-t1
python -m pytest tests/evaluation/test_answer_choice_handoff.py
```
