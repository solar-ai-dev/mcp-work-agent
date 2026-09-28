# 083 — 답변 표현 선택 결과: 일반 적용 REJECT

## 범위와 결론

고정 입력에서 한 compose 호출이 `FACT_REFERENCES` 또는 `PROSE`를 선택하도록 한
비활성 후보를 검증했다. lookup 두 입력은 기존 081 성공을 유지했지만, 메모를 정리하고
원문 인용을 하지 말라는 합성 반례에서는 두 반복 모두 사실 참조를 선택해 금지를 위반했다.

- 후보: **4 PASS / 0 PARTIAL / 2 FAIL** — 세 입력의 각 2회이며, 독립 사례 6개가 아니다.
- 새 정리 baseline: **2 PASS / 0 PARTIAL / 0 FAIL** — 한 합성 입력의 2회다.
- 구조: 새 FIRST 8개 모두 기존 최종 답변 validator 통과. 구조 통과를 의미 성공으로
  승격하지 않았다.
- 판단: **일반 적용 REJECT**. 081의 두 lookup 한정 사실 참조 gate는 유지하지만,
  자동 eligibility나 일반 Task 답변 계약을 확보한 것으로 해석하지 않는다.
- Product source/활성 Prompt/State/Graph/Approval 변경 0, Provider/WRITE 실행 0.

## 봉인 및 실행

| 항목 | 값 |
|---|---|
| 실행 HEAD | `b3b2dbee0863eb173cf6cd2f56f8fcc2b34e8f4b` |
| 사전 기준 | `evaluation/experiments/083-answer-rendering-choice-criteria.md` |
| 로컬 원시 결과 | `evaluation/results/083-answer-rendering-choice-t1/raw.json` |
| raw SHA-256 | `57615df1c764ae283024213069e409bd6a117c2eae77ebcf728c0238589b26ac` |
| plan SHA-256 | `45d4d08990b82dab9edce1b9f17dfb462cc215c6c28a4ca5656f4e8140a63bea` |
| 모델 | `qwen3.5:9b` / Ollama `0.34.0` |
| 모델 digest | `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7` |
| 실제 wire | `seed=20260923`, `num_ctx=16384`, `think=false` |
| sampling | temperature/presence 미전송: 모델 설정 `1`/`1.5`; `top_k=20`, `top_p=0.95` |
| 실행 수 | 고정 8 FIRST, 동시성 1, repair/retry 0, 미실행 0 |
| 관측 범위 | Planning compose 고정 입력 진단; 실제 RU 생성·전체 Graph 실행 아님 |

모든 actual payload가 plan payload와 같았고, 입력·snapshot·runtime 결속은 실행 종료에도
유지됐다. 정리 baseline/candidate는 같은 입력·snapshot·options를 사용했다. 각 입력과
arm의 두 반복은 response content가 byte 단위로 같았다. 이는 이번 고정 seed/환경의
반복 관측이며 다른 요청이나 실행 조건에 대한 신뢰성 보장은 아니다.

081 결과는 lookup 역사 참조이며 이번에 새 baseline lookup을 실행한 것은 아니다.
상세 원시 결과는 기존 `evaluation/results/` 로컬 보존 정책을 따른다.

## 원문 → FIRST → 최종 답변 의미 검수

| 입력/arm | FIRST와 최종 결과 | 판정 |
|---|---|---|
| CORE005 lookup 후보 T1/T2 | `FACT_REFERENCES`, `status`/`due`만 선택. 실제 `needsAction`을 **미완료**, 날짜를 **2026-08-10**으로 전달했다. 제목·메모·시각을 추가하지 않고 새 Task 생성이나 실행 완료도 주장하지 않았다. | PASS ×2 |
| 합성 completed lookup 후보 T1/T2 | `FACT_REFERENCES`, `status`/`notes`만 선택. **완료**와 기존 메모의 원문 인용을 전달했다. 이 요청에는 원문 인용 금지가 없으며 날짜 등 없는 값은 추가하지 않았다. | PASS ×2 |
| 합성 정리 baseline T1/T2 | “선택한 작업 메모의 확인 항목은 입사자 계정 발급과 장비 수령입니다.” 두 확인 항목을 짧게 나열했고 원문 문장 전체를 인용하거나 수행 완료를 주장하지 않았다. | PASS ×2 |
| 합성 정리 후보 T1/T2 | `FACT_REFERENCES`로 `title`/`status`/`due`/`notes`를 모두 선택. 요청하지 않은 제목·상태·기한을 추가하고, 메모를 `메모(원문)` blockquote로 그대로 인용했다. | FAIL ×2 |

합성 정리 요청은 “선택한 작업 메모에서 확인할 항목을 짧은 체크리스트로 정리해줘.
원문 문장은 그대로 인용하지 마.”였다. baseline의 문장은 bullet/checkbox가 아니지만
확인할 두 항목과 인용 금지를 보존한다. 사전 기준은 특정 정리 형식이나 표현 하나를
강제하지 않으므로 이 시각적 형식 차이만으로 PARTIAL을 부과하지 않았다.

반례 후보 실패는 `FACT_REFERENCES`라는 mode 이름 자체 때문이 아니다. 실제 renderer가
내놓은 원문 인용이 명시적 금지를 위반하고, 필요한 정리를 원문·metadata 전달로 대체했기
때문이다. title/status/due/notes는 모두 snapshot에 존재하므로 **새 사실 창작**과는 다르다.
필수 확인 항목도 인용문 안에는 있지만, 존재한다는 사실만으로 표현 조건을 만족하지 않는다.

## 최초 실패 경계와 불변식

최초 divergence는 **LLM FIRST의 표현 mode/field 선택**이다. 두 반례 FIRST는 처음부터
네 필드를 선택했다. renderer는 그 선택을 그대로 materialize했고, 8개 모두
`draft == validation.normalized`였다. validator/normalizer가 사실을 바꾸거나 잘못된
분기를 만들어낸 관측은 없다.

- 현재 요청·선택 identity·Work provenance·Evidence·exact snapshot은 입력에 있었다.
- lookup에서 값 재생성 오류는 생기지 않았다. 상태 의미는 기존 renderer가 소유했다.
- 실패한 정리 응답을 PROSE로 다시 호출하거나 필드 제거로 보정하지 않았다.
- 구조 검증 결과는 모두 VALID여도 raw의 의미 판정은 자동 PASS가 아니라 미검수 상태로
  보존했으며, 위 표가 별도 사후 의미 검수다.
- 승인·Action·실제 WRITE 완료 권한은 새로 만들지 않았다.

## 호출·토큰·지연

| 입력/arm | 새 호출 | 입력 토큰 | 출력 토큰 | reported latency 합계(ms) |
|---|---:|---:|---:|---:|
| CORE005 lookup 후보 | 2 | 7,726 | 302 | 20,104 |
| completed lookup 후보 | 2 | 3,020 | 106 | 4,874 |
| 정리 baseline | 2 | 8,232 | 200 | 9,379 |
| 정리 후보 | 2 | 6,212 | 592 | 21,597 |
| **새 실행 합계** | **8** | **25,190** | **1,200** | **55,954** |

후보 6회 합계는 입력 16,958 / 출력 1,000 / 46,575ms다. 정리 후보는 baseline보다
입력 토큰은 적었지만, 불필요한 네 필드 참조를 출력해 출력 토큰·관측 지연이 증가했다.
미보고 usage는 0이다. 첫 CORE005 후보에는 모델 load 7,638ms가 포함됐고 반복에는
prompt cache 차이도 있으므로 전체 지연을 081 또는 역사 prose와 동일 조건의 인과 비교로
표현하지 않는다.

## 미검증 범위와 다음 선택

일반 Task eligibility, 더 복잡한 요약·분석, multi-Resource, partial/failure 안내,
confirmation, 실제 upstream RU→Retrieval→Planning, Canonical 92 전체와 Live Provider는
이번 모델 진단에서 검증하지 않았다. 기존 좁은 renderer gate나 082의 연결 검사는 이
미검증 범위를 대신하지 않는다.

다음 084에서는 새 conditional union의 `mode`-first property 순서만 제한적으로 검토한다.
현재 FIRST가 `items`를 먼저 생성하고 `mode`를 뒤에 생성한 관측을 바탕으로 하지만,
이 순서가 실패 원인이라는 인과는 아직 확인되지 않았다. 064 v11에 출력 순서 축의
선행 시도가 있었으므로 완전히 새로운 일반 해법으로 소개하지 않는다. 유효 출력 언어와
원문·snapshot·runtime을 유지하는 좁은 비교이며, 효과·채택 가능성은 **미확정**이다.
083 실패를 규칙·few-shot·후처리로 숨기거나 Production에 활성화하지 않는다.
