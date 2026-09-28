# 064 v37 — JSON 문법 제약만 남긴 Output 비교

실행 HEAD `057add8c4f181d89ea885068a6d77ac2cfa1878a`.
사전 기준 `064-output-json-mode-criteria.md`에 따라 v36 constrained 원 응답 3개를
재사용하고 `format:"json"` 후보만 Core005/017/049 각각 1회, **새 호출 3회** 실행했다.
기존 Prompt/input/schema/options/validator는 그대로이며 원문을 다시 생성하거나
repair하지 않았다. 평가 범위는 Output FIRST owner이며 전체 RU/업무 성공이 아니다.

## 결과와 최초 실패

| Case | 재사용 schema baseline | 새 JSON-mode | 판단 |
| --- | --- | --- | --- |
| CORE-005 | 조회에 TASK UPDATE + GMAIL SEND를 추가 | 동일한 두 불필요 WRITE | FAIL 유지: Output 최초 생성에서 요청에 없는 변경 선택 |
| CORE-017 | GMAIL_DRAFT CREATE / work-1 | 동일 | Output owner PASS, 기존 Source 오류는 별도 |
| CORE-049 | TASK / CALENDAR_EVENT / GMAIL_DRAFT CREATE / work-1 | 동일 | Output owner PASS, upstream 시간 오류는 별도 |

두 arm 모두 구조 검증 **3/3**, Output owner 의미 **2 PASS / 0 PARTIAL / 1 FAIL**이다.
원 raw는 `UNREVIEWED`로 보존하고 이 문서에서 별도 의미 판정했다. 새 응답은 JSON key
순서 차이가 있지만 Resource/effect/binding 결정은 같다. 기존 실패를 대체하지 않았다.

**REJECT: JSON mode를 Product에 반영하지 않는다.** 상세 schema의 enum만 없애면
005의 오류가 해결된다는 가설은 이 입력에서 지지되지 않았다. JSON 문법 제약 자체를
없앤 v36에서는 내용이 올바른 대신 코드펜스 때문에 strict parser가 거절했다.
이는 모든 모델 오류의 원인이 grammar라는 증거도, 무제약 출력을 바로 채택할 근거도 아니다.

## 비용·실행 조건

모델 `qwen3.5:9b`, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
temperature0 / seed20260923 / ctx16384 / thinkfalse / timeout180초.
Dataset/fixture/Case reference time은 사전 plan에 결속하고 변경하지 않았다.

| 측정 | 재사용 baseline 3개 | 신규 JSON-mode 3개 |
| --- | ---: | ---: |
| input / output tokens | 8,848 / 151 | 8,848 / 151 |
| reported latency 합계 | 14,898ms | 16,645ms |
| wall latency 합계 | 14,952ms | 16,700ms |
| usage 누락 / repair / retry / timeout | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |

cold load를 포함한 서로 다른 실행이므로 속도 차이를 일반화하지 않는다. 모델은 순차
1개만 실행하고 pytest/mypy와 겹치지 않았다. 종료 관측 VRAM6385MiB/58°C다.
Graph 재실행 0, 외부 업무 Provider READ/WRITE/SEND 0. 실제 신규 호출은 6회가 아닌 3회다.

## 다음 선택

v36의 내용을 의미 수정 없이 전달할 수 있는 **evaluation-only 단일 JSON 코드펜스
admission**을 먼저 기존 raw로 검증한다. 앞뒤 설명·여러 블록·불완전 JSON을 임의 추출하지
않고, 원 schema와 owner validator를 그대로 적용한다. 기존 INVALID_JSON 판정은 유지한다.
Product parser를 전역 완화하거나 005를 위한 Prompt/키워드 규칙을 추가하지 않는다.
이 작은 표현 경계가 닫히더라도 더 넓은 Core 성공/실패/반례 비교 전에는 채택하지 않는다.

## 원 근거

- `evaluation/results/064-output-json-v37-t1/raw.json` SHA256
  `2fa4d1c6ff77bdb16df7b4e80e72609df60a526de391eee86b885cb4be5a19ed`.
- `evaluation/results/064-output-json-v37-t1-plan/preregistered-plan.json` 파일 SHA256
  `b95454dddc775612b5f435fd21e418b64ce8d810771a21084ec6993bad767ad7`;
  plan object hash `6794d6ac96134d7a9435c3f9adea548bd7f8f8fe8f3079f82c61ee4a5f0b8a7b`.
- 재사용 원 baseline: `064-output-format-ablation-result.md`의 v36 원 raw 및 hash.
- 상세 결과는 로컬 `evaluation/results/` ignore 정책을 유지한다. 이 비민감 요약과 실행기는
  원격에서 검토 가능하다. Prompt/Schema/State/제품 실행 경로 변경은 이번 후보에서 0이다.
