# 090 — 공통 문맥 제거는 성공 위치를 바꿀 뿐 개선이 아님

실행 SHA `43d65704`. 사전 고정 A6+B2 FIRST를 모두 실행했다. 실제 9B8회,
repair/retry0. 등록 router/compiled Graph/Provider 호출0인 **transport 원인분리**다.
088 역사6회(4 PASS/0 PARTIAL/2 FAIL)는 재사용했고 새 baseline 실행으로 세지 않는다.

| 변경 하나 | 상태·기한만 | 완료·메모 | 메모 재작성·원문 인용 금지 | 판단 |
| --- | --- | --- | --- | --- |
| 088 역사 공통 문맥 | FAIL2 | PASS2 | PASS2 | 기준4/0/2 |
| A 공통 문맥 문자열만 제거 | PASS2 | PASS2 | FAIL2 | 4/0/2, 회귀로 REJECT |
| B Prompt version metadata만 과거값 | FAIL2 | 미실행 | 미실행 | 0/0/2, 효과 없어 REJECT |

A의 조회 답은 정확히 미완료와2026-08-10만 전달한다. 그러나 메모를 체크리스트로
재작성하라는 요청에 title/status/due/notes 전부를 골라 메모 원문을 인용했다.
즉 하나의 과잉 선택을 고치는 대신 기존의 표현 조건 성공을 깨뜨렸다.
B는 계속 네 필드를 모두 골랐다. version 변경만으로 이번 관측 오류가 해결되지 않는다.
각 입력의 두 반복은 동일 결과이며, 동일seed 반복을 일반적인 안정성으로 해석하지 않는다.

FIRST field/mode 선택이 최초 divergence이고 renderer/normalizer가 필드를 추가하거나
금지를 삭제한 것은 아니다. 원문·Goal·outline과 요청 범위는 양쪽 입력에 존재한다.
공통 문맥이 결과에 영향을 준 것은 관측했지만, 그 내부 특정 문장을 확정 원인으로
지목하거나 더 작은 문구 patch 탐색을 반복하지 않는다. 084에도 입력 복사가 두 번
존재하므로 입력 중복이 새로운 원인이라는 설명도 사용하지 않는다.

## 다음 선택: 조회용 파생 alias만 분리

06의 Source `required_information`은 Connector가 확보할 사실·identity다.
05에서 같은 이름의 USER_REQUIREMENT는 검색 목적으로 소비한다.
`request_goal_candidate_schema.derive_source_information_constraints`는 이를 복제하고,
`planning/compose_answer.py`는 Source와 복사 constraint를 함께 전달한다.
답변 범위의 owner는 원문·approved outline이지 수집 목록 전체가 아니다.

이 중복이 확정 원인이라고 단정하지 않는다. 다음 평가 전용 입력 후보에서는
**기존 source_reads로 정확히 재구성되는 복사 constraint만 생략**하고 원래 Source,
원문·Goal·기타 조건·WorkUnit·Evidence는 보존한다. 자연어에서 정답 field를 추론하거나
title/notes를 Schema에서 금지하지 않는다. 이는 전체 constraint 삭제가 실패한077과 다르다.
별도 input contract로 선언하고 Product V3/State/Prompt는 변경하지 않는다.

## 비용·봉인·제한

- A6: input17,030/output1,010 tokens, reported45,189ms/wall45,422ms.
- B2: input8,236/output582 tokens, reported21,515ms/wall21,576ms.
- 전체8: input25,266/output1,592, reported66,704ms, usage 누락0.
  A 첫 호출에는 cold load6,224ms가 포함된다. 작은 표본의 지연을 우월성으로 해석하지 않는다.
- 전부 output schema와 draft 구조 VALID. 의미 결과는 위 표처럼 별도 수동 검수했다.
- model/digest/options는088과 동일. temperature/presence는 미전송(default), seed20260923,
  ctx16384, think=false. concurrency1. 결과·source·model 봉인 변경0.
- plan object SHA256 `2ef038cec5c50d81f0b4bb95760c40e8ca8f25c4282483d7758d5fa3754e356e`.
- raw `evaluation/results/090-answer-assembly-ablation-t1/raw.json`, SHA256
  `6985c0120125f94ff72a980b2fdf1281e99b24d58835dc461d0baff0b0a34a5e`.
- Provider READ/WRITE/SEND0, 승인0, rerun-to-pass0, Product/활성 Prompt/Dataset 변경0.
- Main089와 Canonical92는 실행하지 않았다. 이 결과를 전체 업무 성공률로 승계하지 않는다.
  원문/actual wire는 ignored local results에, 비민감 결론은 이 문서에 보존한다.
