# 091 — 조회 alias 생략은 과잉 선택을 고치지 못함

실행 SHA `245265b7`, 신규 actual9B FIRST6 고정 완료. **REJECT / Product 미적용**.
088 역사동일6개의4 PASS/0 PARTIAL/2 FAIL에서 **2 PASS/2 PARTIAL/2 FAIL**로 회귀했다.

| 요청, 각2회 | 088 → 091 | 실제 답·이유 |
| --- | --- | --- |
| 선택 Task 상태·기한만 | FAIL → FAIL | FIRST가 title/status/due/notes 전부를 선택. 확정 사실은 정확해도 명시한 답변 범위를 위반했다. renderer 이전 오류이며088과 같은 답이다. |
| 완료 Task 상태·메모 | PASS → PASS | FACT renderer로 완료와 메모를 보존했다. 식별용 title은 이 요청에서 금지되지 않았으므로 감점하지 않았다. |
| 메모의 확인 항목을 짧은 체크리스트로, 원문 인용 금지 | PASS → PARTIAL | 계정 발급/장비 수령 두 내용과 원문 문장 인용 금지는 보존했다. 그러나 항목을 나눈 체크리스트 대신 한 문장으로 설명해 형식 요구가 남았다. |

PROSE/FACT mode를 정답으로 고정하지 않았다. 091의 재작성 PARTIAL은090의 원문 인용
위반 FAIL과 다르다. 양쪽 동일 요청·FIRST·materialized를 독립 검수한 결론도 일치한다.

## 실제 바뀐 것과 보존한 것

각 입력에서 Source로 정확히 재구성되는 constraint1개만 view에서 제외했다.
원래 Source, 원문/Goal/Work binding, 다른 constraints, snapshot/Evidence, outline,
공통 문맥·ROLE·PromptRef metadata·Schema/순서·sampling은 그대로다. 값을 지우는
일반 constraint 축소도, 원문에서 정답 field를 추론하는 처방도 아니다.
하지만 이 좁은 중복 제거만으로도 개선이 없으므로 **더 넓은 정보 삭제로 이어가지 않는다**.
중복이 유일 원인이라는 가설은 지지되지 않았다. Product V3/State/Prompt는 유지한다.

## 검증·비용

- exact alias/provenance/Work binding·원본 변조·두 wire 입력·재실행 차단 직접16 PASS.
  기존 연결/수리/답변 인접365 PASS. 중복 합산 없이 총381개의 관련 검사다.
- scoped Ruff PASS, mypy explicit-package-bases + follow-imports=silent 3파일 PASS.
  root의 첫 mypy 명령은 package-bases 미지정으로 중복 module name 오류였으며,
  명령 범위를 바로잡아 확인했다. 기존 full-import mypy 오류를 전체 PASS로 숨기지 않는다.
- 신규6 calls, input18,108/output906 tokens, reported41,952ms/wall42,123ms.
  첫 cold load5,990ms 포함. 역사6 calls18,524/946 tokens·43,226ms와 순수속도 비교하지 않는다.
- schema/draft 구조6/6 VALID, repair/retry0, 같은seed 반복은 입력별 같은 결과.
- qwen3.5:9b Q4_K_M/digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  Ollama0.34.0/ctx16384/think=false/seed20260923. temperature/presence미전송.
- 실행 중 GPU 관측6383MiB/66%/59°C, model concurrency1. 테스트/편집과 모델 생성 겹침0.
- Provider READ/WRITE/SEND0, Graph/registered router0, 승인0, rerun-to-pass0.
  단독 wire 진단이며 일반 confirmation-resume 입력과 Product 등록 경로의 호환은 미검증이다.

plan object SHA256 `ceba7ec84ebbefceaa9aeec66751e4b3101d0b1b85d4a3f7eead4f1281d16b61`.
raw `evaluation/results/091-answer-acquisition-alias-t1/raw.json`, SHA256
`36f46371db11c5701a240a7cab365ff0710cb1c2360bda159652813cc3f873f2`.
source/model/input 종료봉인 유지. 원 raw/Gold 변경0. Main089/Canonical92 미실행.

## 다음 선택

현재 답변 owner는temperature 미전송으로 모델기본1을 사용한다. 기존 낮은 Source
temperature와 Source/effect의 기각 기록은 답변 owner의 비교 결과가 아니다.
동일088 full wire에서 temperature만0으로 하는 신규 FIRST3 진단으로 넘어간다.
091 입력 축소를 중첩하지 않고, 개선이 없으면 sampler 수치 탐색으로 확대하지 않는다.
이는 Production 변경이나 Epic 완료가 아니다.
