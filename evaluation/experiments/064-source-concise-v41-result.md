# 064 v41 — Source 설명 축소 FIRST 비교: REJECT

## 고정 조건과 범위

- 실행 HEAD: `a489e3c4e8b3f92799fe16b24b26e086fc195b44`. 기준/준비는 `064-source-concise-v41-criteria.md`, 준비 commit `9e0a68f3`이다.
- 현재 Product Source instruction을 축소한 evaluation-only 후보다. 원 입력, 기존 Source Schema/validator, assembler suffix, top-level format, sampling은 그대로다. Product Prompt/manifest/activation 변경 0.
- 005/009/017/049/059 순서로 각 1회, **신규 5회 + 원 FIRST 5회 재사용**. repair/retry/codec/Graph/업무 Provider 호출 0. 모델과 테스트를 겹치지 않았으며 파일 변경 없이 직렬 실행했다.
- qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, Ollama 0.34, temperature 0.05, seed 20260923, num_ctx 16384, think=false, timeout 180초. 미전송 sampling은 모델 기본값이며 0으로 간주하지 않는다.
- 원 baseline wire 5/5, 후보 wire 5/5를 실제 assembler/transport로 재구성해 hash 일치를 확인했다. baseline과 후보의 입력·Schema·format·options는 같다. 바뀐 것은 Source instruction prefix(-2,437자/호출)와 이를 식별하는 candidate version/hash뿐이다.
- 19개 코드/Prompt hash, Dataset/Fixture와 원 plan 3개의 hash 일치를 확인했다. 과거 baseline SHA를 현재 SHA에서 새로 실행한 결과처럼 합치지 않는다. 원 경로/row hash/실제 기준시각·fault는 plan에 남아 있다.

## 구조와 실제 의미

양쪽 모두 **5/5 strict VALIDATED**다. 후보 5개에서 JSON 원 출력과 validated output이 완전히 같았다. 아래 차이는 normalizer가 만든 것이 아니라 **Source FIRST 모델 출력에서 시작**했다.

| Case | 재사용 baseline | v41 후보와 최초 차이 |
| --- | --- | --- |
| CORE-005 | 선택 Task의 상태·기한을 포함하고 SINGULAR/work-1 보존. 필요정보에 전체 fact inventory를 복사한 과잉 명세는 관측으로 남김 | Resource/fact/Work는 같지만 **target_scope만 CRITERIA로 변경**. 선택한 특정 Task 하나라는 Source 범위 계약이 회귀. downstream이 실제 범위를 넓혔다고 주장하지는 않음 |
| CORE-009 | 메일 내용 경로는 있으나 명시 Task Source 누락 | Task/List를 추가했지만 필요정보를 모두 **ID/검색 키워드**로 작성. 메일 내용·작업 상태가 필요한 요청에서 기술 identity만 남음. Source category 복구를 업무 사실 복구 PASS로 세지 않음 |
| CORE-017 | Task/Event 사실 보존, 새 Draft를 기존 GMAIL_DRAFT Source로도 필수 지정하는 잔여 오류 | 불필요 Draft는 제거했으나 **Task까지 NOT_REQUIRED**, Event 필요정보도 start/end 등에서 event_identity 하나로 축소. 명시 Task 조회 의미가 사라지는 회귀 |
| CORE-049 | 메일/Task/Calendar 사실은 유지하지만 기존 Draft 등 과잉 필수 Source가 있음 | Draft와 함께 **명시 메일/Task를 모두 제거**. 남은 Event 필요정보도 사용자가 새로 만들라고 한 점검 일정 사양으로 바뀜. 새 Output 사양을 기존 조회 사실로 혼동 |
| CORE-059 | 답장할 Thread/메시지 이력의 Source를 보존 | Message 주제/본문 조회는 합리적인 대안. 그러나 **기존 Draft를 thread_id/message_id 제공자로 필수 추가**하는 Source owner 혼동이 새로 생김. 실제 SEND/recipient/최종 업무 결과는 미실행 |

다섯 후보의 `work_unit_ids=[work-1]`은 보존됐다. 이는 단일 Work binding 확인이며 다중 Work 안정성 근거가 아니다. parent나 보조 Source를 더 골랐다는 사실만으로 최종 업무 FAIL을 주지 않았고, 기존 자료 조회와 새 Output 생성의 의미를 구분했다.

독립 검수를 포함한 **Source owner 범위** 판정은 baseline **2 PASS / 2 PARTIAL / 1 FAIL** → 후보 **0 PASS / 2 PARTIAL / 3 FAIL**다. Case별로 005 PASS→FAIL, 009 FAIL→PARTIAL, 017/049 PARTIAL→FAIL, 059 PASS→PARTIAL이다. 005 baseline의 fact 과선정은 별도 관측이고, 009 후보는 조회 category는 복구했으나 필요한 업무 fact가 불명확해 PARTIAL이다. 이 표본의 기존 PASS 2건 모두 완전 PASS를 유지하지 못했다. 이 점수를 전체 RU 또는 최종 업무 성공률로 사용하지 않는다.

이 결과로 의미 개선을 채택할 수 없다. 특히 005의 범위, 017/049의 명시 Source 보존이라는 기존 성과가 회귀했다. 009의 Source 이름 복구와 017/049의 불필요 Draft 제거는 관측되지만 필요한 사실·자료 손실을 상쇄하지 않는다. 기존 raw의 UNREVIEWED 및 business_success=NOT_EVALUATED 표시는 덮어쓰지 않았다.

## 호출·토큰·지연 및 자원

| 구분 | calls | 입력 token | 출력 token | 보고 latency 합계 | wall 합계 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 재사용 baseline | 5 | 20,442 | 1,119 | 50,595ms | 50,718ms |
| 신규 v41 | 5 | 16,332 | 1,010 | 51,351ms | 51,577ms |

입력은 4,110, 출력은 109 token 감소했다. 신규 첫 호출의 model load는 7,437ms(5개 합계 7,460ms)다. 재사용 baseline은 동시 paired 성능 측정이 아니므로 +756ms를 순수 Prompt 영향이나 속도 개선/저하로 단정하지 않는다. 1회 비교를 반복 안정성으로 표현하지 않는다.

자원 snapshot: 시작 RAM 여유 19.99GiB/31.71GiB, GPU 0/8,188MiB·42°C. 실행 중 관측 GPU 6,385MiB·68%·72°C. 종료 RAM 여유 17.41GiB, GPU 6,385MiB·0%·50°C. 순간 관측이며 전체 peak 측정은 아니다. 신규 모델 generation 동시성은 1이다.

## 판단과 다음 축

**REJECT / Production 유지.** instruction 부담을 줄이는 것만으로 Source 의미가 안정되지 않았다. 길이가 실패 원인이라는 가설은 입증되지 않았고, 더 짧은 문구/사례별 규칙을 추가해 같은 축을 반복하지 않는다.

남은 최초 경계는 Source 의미 생성이다. 원문이 실제 입력에 있었고 동일 입력·Schema에서 다른 Source 판단이 생성됐다. 이것만으로 9B 모델 한계나 특정 다른 구조의 성공을 결론내리지 않는다. 다음은 실제 runtime의 미전송 decoding 설정이 어떤 값으로 소비되는지 기존 코드/원 기록을 확인한다. 이미 통제한 실험이면 재실행하지 않고, 새 축도 실제 구현이 그 옵션을 소비함이 확인된 경우에만 작은 고정 비교를 고려한다.

Source-only 결과이며 RU→Tool Route/연결 성공/최종 업무/Canonical92 점수가 아니다. no-source·다중 Work·UPDATE/DELETE·confirmation/revision과 Retrieval→Planning 이후는 미검증이다. Provider WRITE/SEND 0.

## 재현 근거

- raw: `evaluation/results/064-source-concise-v41-t1/raw.json`, SHA256 `91772da9aea4514cc12e4c6bb0195389e4ab414a9252549871feb8b3f0b042b7`.
- plan: `evaluation/results/064-source-concise-v41-plan/preregistered-plan.json`, bytes SHA256 `8465dda2f1a97f89884590c1371c6a4a4b02d6f7f3a662859841220beb4e08c3`, object SHA256 `27ececffef23a670e018bf133fbb3c08133357b742876af1aed5cb082509f9a4`.
- 후보 instruction SHA256 `b073911a62c101e66c4812a9216df3cfd30ebe0cdeef8de17fa54d2c36237b5b`.
- Dataset SHA256 `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`, Fixture SHA256 `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
- 상세 raw는 기존 ignore 정책에 따라 로컬 보존한다. 이 문서는 원격 검토용 비민감 결론이며 원 source 본문·비밀키를 포함하지 않는다.
