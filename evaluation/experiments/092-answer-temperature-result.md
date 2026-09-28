# 092 — 낮은 온도는 과잉 선택을 줄였지만 형식 성공을 회귀시킴

실행 SHA `0949eeae`. 실제 FIRST3(입력별1회), **2 PASS/1 PARTIAL/0 FAIL**.
088의 같은 T1 세 역사 결과는2 PASS/0 PARTIAL/1 FAIL이다. 분모·기존 실패를 바꾸거나
새 paired baseline 실행으로 표시하지 않는다. **공통 sampler 변경은 REJECT**, 관측한
lookup 개선은 보존하지만 후보 Product 채택 근거로 쓰지 않는다.

| 입력 | 역사088 → 092 | 실제 결과 |
| --- | --- | --- |
| Task 상태·기한만 | FAIL → PASS | FIRST가 status/due만 선택, 미완료와2026-08-10만 전달. title/notes를 추가하지 않았다. |
| 완료 Task 상태·메모 | PASS → PASS | title/status/notes 선택, 완료 사실과 요청한 메모를 정확히 표현. |
| 메모 체크리스트·원문 인용 금지 | PASS → PARTIAL | 두 확인 의미와 인용 금지는 보존하지만 항목별 체크리스트 대신 한 문장 설명. PROSE mode 자체가 감점 이유는 아니다. |

092는091의 alias 제거를 사용하지 않는다. 원문/Source/Goal/constraints와 공통 문맥,
PromptRef·ROLE·Schema의 값/순서·model/seed/presence 모두088 그대로이고,
`options.temperature=0.0`만 명시했다. 답변 owner의 기존 미전송 기본1과 비교다.
Source0.05나 과거 Source/effect sampling 실험을 답변 owner의 점수로 승계하지 않는다.
기존 성공이 PARTIAL로 바뀌었으므로 수치를 더 탐색하거나 presence까지 섞지 않는다.

## 근거와 제한

- actual3 calls, input9,262/output295 tokens, reported16,091ms/wall16,156ms, 누락0.
  역사3 calls9,262/473 tokens·27,638ms는 동시 paired latency가 아니다.
- 모델9B/digest/Ollama0.34.0/ctx16384/think=false/seed20260923은088과 동일,
  presence 미전송(default1.5). 단발3개이며 반복 안정성이나 일반화는 미검증이다.
- schema와 draft 구조3/3 VALID, retry/repair0, source/model/ordered wire 종료봉인 유지.
- 직접 fake11 PASS, Ruff/mypy scope2파일 PASS. 기존 회귀381과 별도 검사다.
- plan object SHA256 `aec89a46d92c5b278cc250a255e4401f2e1461cb2b1c68a16c00e48192fd8b21`.
- raw `evaluation/results/092-answer-temperature-t1/raw.json`, SHA256
  `53bdfb2b1f559b87ee183a331ba6d84b65cdaafaa28669625c23d50c1350902f`.
- Provider READ/WRITE/SEND0, Graph/registered router0, Product/활성Prompt변경0.
  Main089/Canonical92 미실행. 이 진단을 업무 성공률이나 release 검증으로 승계하지 않는다.

## 다음 작업

같은 Task 세 입력의 문구·sampling 조합 탐색을 멈추고, 독립 코드 검토에서 확인된
**WorkUnit별 Task field 요구를 전역 union하는 결정적 consumer 손실**을 직접 재현한다.
단일 업무와 동등 필드 업무는 유지하고, 이질적 범위는 기존 작성 owner에 typed binding을
그대로 전달하는 최소 수정으로 진행한다. 이 별도 코드 결함이088 모델 오류의 원인이라는
주장은 하지 않는다.
