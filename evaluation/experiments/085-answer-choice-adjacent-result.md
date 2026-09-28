# 085 — 인접 답변 회귀: Task 메모 유지, Calendar 시각 변형

## 결론

고정된 두 synthetic Planning 입력 × FIRST 2회에서 **2 PASS / 0 PARTIAL / 2 FAIL**이다.
Task 메모는 두 번 모두 정확했지만, Calendar는 실제 오전 10–11시를 오후 10–11시로
바꿨다. 구조 VALID 4/4를 의미 성공으로 승격하지 않는다.

**catalog가 없는 Resource까지 choice ROLE/schema를 적용하는 현재 범위는 REJECT**한다.
084의 좁은 Task lookup·정리 결과를 폐기하지는 않지만, 그 성공을 Calendar나 일반 답변
전체의 성공으로 승계할 수 없다. Product는 활성화하지 않았다.

## 봉인·실행 조건

| 항목 | 값 |
|---|---|
| 실행 HEAD | `948904ea7c2527fcba8a5f5e205724a8c30aebbd` |
| 사전 기준 | [085 인접 control 기준](085-answer-choice-adjacent-criteria.md) |
| 로컬 raw | `evaluation/results/085-answer-choice-adjacent-t1/raw.json` |
| raw SHA-256 | `9c4bcb8049adbf684fd4ae94cfffbd1723505c2ec87ac6edd4e0bae851e6e337` |
| plan SHA-256 | `e7d7f737d023ce5c8073f9410bed75a40b6eb94b2aea30cb8d83c31cf79869c2` |
| 역사 입력·baseline | `065-read-answer-handoff-t1`, synthetic typed Planning fixture |
| 모델 | `qwen3.5:9b`, Ollama `0.34.0` |
| 모델 digest | `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7` |
| 실제 wire | `seed=20260923`, `num_ctx=16384`, `think=false` |
| sampling | temperature/presence 미전송: 모델 설정 `1`/`1.5`; `top_k=20`, `top_p=0.95` |
| 새 실행 | 4 FIRST, 동시성 1, repair/retry 0, 미실행 0 |

065 원 FIRST의 projection과 실제 HTTP serialization을 재구성하여 동일성을 확인한 뒤
역사 baseline을 재사용했다. 이번 actual payload/transport byte hash가 봉인된 case와
일치했고 종료 시 `binding_unchanged=true`였다. 두 입력 각각의 반복 response는 byte 단위로
같았다. 고정 seed의 두 반복이지 독립 업무 네 개나 넓은 안정성 증명은 아니다.

## 원문·근거·실제 FIRST 검수

| 입력 | 기존 근거 | 085 FIRST와 최종 답변 | 판정 |
|---|---|---|---|
| Task 메모 T1/T2 | 선택 Task 제목 `장비 수령 확인`, 메모 `장비 수령 항목을 확인할 것.`. status/due는 없다. | PROSE로 같은 제목과 메모를 전달했다. 없는 상태·기한을 추가하거나 작업을 완료했다고 주장하지 않았다. | PASS ×2 |
| Calendar 시간·장소 T1/T2 | `설계 검토`, `2026-08-18T10:00:00+09:00`–`11:00:00+09:00`, `Asia/Seoul`, `한빛회의실` | PROSE FIRST에서 **“오후 10시부터 오후 11시까지”**라고 생성했다. 장소·제목·시간대는 보존했지만 시작·종료 시각을 12시간 이동했다. | FAIL ×2 |

Task 메모는 FACT_REFERENCES가 아니라 PROSE를 선택했어도 요청 의미를 충족하므로 PASS다.
메모 조회가 반드시 refs여야 한다는 Gold를 추가하지 않았다. 선택 Task 제목은 문맥으로
표시됐으며 요청하지 않은 status/due를 발명한 것과 구분한다.

Calendar에는 Task fact catalog가 없어 schema가 PROSE 한 분기만 허용했다. 따라서 PROSE
선택 자체는 의미 판단 성공이 아니다. 날짜도 최종 문장에서는 생략됐지만, FAIL의 명확한
근거는 원문 Evidence에 있는 오전 시간을 오후로 바꾼 것이다. 새 일정 생성·저장·실행
완료를 주장한 오류는 관측하지 않았다.

065 역사 baseline은 각 입력 1회이며 둘 다 의미 PASS였다. Calendar는 **2026년 8월 18일
오전 10시–11시, 한빛회의실**을 답했고 Task 메모도 그대로 전달했다. 이 두 역사 호출을
신규 네 호출의 반복 수나 성공 분모에 합산하지 않는다.

## 최초 divergence와 원인 해석 범위

Calendar의 잘못된 오후 표현은 최초 LLM response에 이미 존재했다. materializer는 PROSE의
mode만 제거했고 4/4에서 `draft == validation.normalized`였다. 시각 변형이 renderer나
normalizer에서 발생한 것은 아니다. 틀린 시간을 후처리로 오전으로 고치거나 재호출하지 않았다.

확인된 회귀는 **Task catalog가 없는 지원 범위에도 새 choice 역할·출력 계약을 적용한
조건에서 발생한 FIRST 시각 재서술 오류**다. 065 대비 ROLE와 mode schema가 함께 다르므로
이 한 비교만으로 Prompt 문구, schema, property 순서 중 하나를 단독 원인으로 확정할 수
없다. 모든 Resource에 mode-first가 나쁘다거나 모델이 시간을 이해할 수 없다는 결론도 아니다.

## 비용

| 구간 | 새 호출 | 입력 토큰 | 출력 토큰 | reported latency 합(ms) |
|---|---:|---:|---:|---:|
| Task 메모 후보 | 2 | 2,894 | 108 | 11,887 |
| Calendar 후보 | 2 | 3,082 | 206 | 7,817 |
| **085 합계** | **4** | **5,976** | **314** | **19,704** |
| 065 역사 baseline(별도) | 0; 과거 2회 | 5,694 | 108 | 14,757 |

usage 누락은 0이다. 첫 Task 호출 load 7,254ms와 반복 prompt cache 차이가 있으므로
역사 baseline과 지연 합계를 직접적인 제품 성능 개선·악화율로 단정하지 않는다.

## 086 연결 gate와 다음 선택

[086 Planning·terminal handoff 기준](086-answer-choice-handoff-criteria.md)의 별도 replay는
**084의 저장된 여섯 응답**을 사용해 component PASS 6개를 확인했다. 신규 모델·Provider는
0이고 의미 판정은 `NOT_EVALUATED`다. 이는 085의 Calendar 오답을 검증하거나 고친 결과가
아니며, 085 의미 점수에 합산하지 않는다.

086 raw는 `evaluation/results/086-answer-choice-handoff-t1/raw.json`, SHA-256은
`43a5cd05b072fb447826a926c22b1aaf6b7aaa91789ecd049cbaf9f366d8ffac`다.
실제 Main/Supervisor·DB commit·UI 전달이나 새로운 RU/Provider 실행 성공을 뜻하지 않는다.

후속 087은 **검증된 Task fact catalog가 없으면 후보 역할·mode schema를 적용하지 않고
원 Product wire를 dispatch 전에 그대로 반환하는 capability 경계**를 검토한다. 이는
자연어 키워드나 required_information allowlist로 답변 의미를 분류하는 정책이 아니며,
실패를 보고 새 Prompt 규칙이나 사후 semantic fallback을 추가하는 것도 아니다.
효과는 아직 미확정이며 별도 고정 실행으로 검증해야 한다. 085의 두 실패는 원래대로 보존한다.

Product source/활성 Prompt/Registry/State/Approval 변경 0, Provider READ/WRITE/SEND 0.
새 upstream, Canonical 92, 실제 사용자 업무·출시 품질은 미검증이다. 상세 raw는 기존
`evaluation/results/` 로컬 보존 정책을 따른다.
