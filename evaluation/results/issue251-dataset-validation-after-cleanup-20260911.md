# 의미 강제 제거 후 데이터셋 제한 검증

- 고정 실행 커밋: `62fde3661489b9120f49876e9fd0f7f1cdbeaae6`
- Prompt: `request_understanding.identify_goal` 1.0.53, `retrieval.plan_query` 1.0.24
- 조건: 9B temperature 0.2, 4B temperature 0.7, seed 1729
- 실제 production compiled Graph와 현재 허용된 Connector를 사용했으며, 외부 WRITE와 실행 승인은 수행하지 않았다.

| 사례·모델 | 실행 커밋 | 최초 실패/도달 노드 | 실제 답변·Preview 요지와 판정 | Run/Trace |
| --- | --- | --- | --- | --- |
| Nimbus · qwen3.5:9b | `62fde366` | `execute_read`에서 Gmail SEARCH 3회가 모두 0개를 반환했고, `select_evidence`의 Evidence 0개 뒤 `assess_sufficiency`가 PARTIAL로 종료 | “Nimbus 조건으로 확인했지만 근거가 충분하지 않다.” 실제 READ에는 진입했으나 9월 14일 정정 날짜를 답하지 못해 **실패**. LLM 4회, Connector READ 3회, source page 3회, detail 0회, WRITE 0. | Run `fc1d04cc-4b3a-489e-8145-e3a17724a400` · [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a08dbf-edfe-7e62-a792-374ff8429a55/run/01a08dbf-edfe-7e62-a792-374ff8429a55) |
| Nimbus · qwen3.5:4b | `62fde366` | 세 번째 `execute_read`의 Gmail projection이 `EMAIL retrieval requires a translatable constraint`로 실패해 `RECOVERY_REQUIRED(CONTRACT_VIOLATION)` | 앞선 Gmail READ 2회 뒤 Query가 실행 가능한 제약을 잃었고 사용자 답변 없이 복구 대기로 전환되어 **실패**. LLM 4회, Connector READ 2회, source page 2회, detail 0회, WRITE 0. | Run `89df535e-d6b3-4712-99ec-11a38f1f91d2` · [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a08dc6-30f3-7d73-9d78-16e0224af2a2/run/01a08dc6-30f3-7d73-9d78-16e0224af2a2) |
| Maple · qwen3.5:9b | `62fde366` | `execute_read`/detail 조회와 Evidence 3개를 거쳐 `compose_answer`·`finalize` 도달 | 9월 8일 오전 후보가 장소 문제로 취소됐고 다른 날짜는 아직 정해지지 않았다고 정확히 설명해 **성공**. 제품 표시는 전체 범위 미확인에 따른 PARTIAL. LLM 13회, Connector 5회(페이지 2·detail 3), WRITE 0. | Run `b04f20bb-daa8-4dff-9bfd-16c011e5e143` · [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a08dc8-4779-7f60-9098-e42037fd0272/run/01a08dc8-4779-7f60-9098-e42037fd0272) |
| Maple · qwen3.5:4b | `62fde366` | 반복 Retrieval 뒤 `plan_query`가 `RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID`로 차단되어 `BLOCKED` | Gmail Connector 8회(페이지 7·detail 1)와 LLM 16회를 사용했지만 최종 날짜 판단에 도달하지 못하고 내부 검증 실패 안내만 게시해 **실패**. Evidence 영속 0개, WRITE 0. | Run `0e5f3f49-2708-40c4-b902-0426d648efec` · [Trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a08dcb-2563-70d0-b859-410fc76b1925/run/01a08dcb-2563-70d0-b859-410fc76b1925) |
