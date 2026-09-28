# 064 — Output FIRST `format="json"` 후속 진단 사전 기준

## 기존 관측과 새 비교 축

v36 (`9813416e`, `evaluation/results/064-output-format-v36-t1/raw.json`)의
`format_omitted`는 세 Case 모두 Markdown fence가 포함된 JSON을 반환했다.
기존 strict JSON 검증의 구조 통과 **0/3** 판정을 유지한다. fence 내부의 내용이 업무 의미와
맞았다는 관측은 제품이 수용 가능한 구조화 출력이라는 판정과 다르다. 원 raw·분모·판정을
고치거나 fenced JSON을 추출해서 성공으로 바꾸지 않는다.

후속은 동일 원 Output FIRST wire를 대상으로 **full schema constrained decoding 대
JSON mode**를 비교하는 독립적인 representation 조건이다. Prompt/Input/본문의 output
schema/옵션을 그대로 두고 top-level `format` 값만 JSON Schema object에서 `"json"`으로
바꾼다. 규칙·예시·Prompt 재작성·repair 추가 실험이 아니다.

## 고정 계획

- 원 입력: v35 connected CORE-005 production, CORE-017/049 codec의 Output FIRST.
- v36의 `schema_constrained` **3개 기존 결과를 재사용**하고 `format_json`만 **3회 신규 호출**.
- 비교 관측은 3쌍이지만 새 6회 실행으로 집계하지 않는다. 신규 순서는 005→017→049.
- v36 raw의 exact path/hash와 baseline 3행 hash, original wire/input/model/runtime/schema,
  Product validator/dependency hash가 일치해야 재사용한다. runner HEAD/code hash는 새 비교
  모드 때문에 다르며 이를 source HEAD와 분리한다. Product/actual wire는 동일하다.
- model digest·instruction·input·PromptRef·본문 schema·seed·think·temperature·num_ctx
  모두 기존 wire와 동일. actual Product transport payload hash가 원본과 일치해야 진행.
- arm당 HTTP 1회, timeout 180초, 직렬 1개. retry/repair/semantic revision/Provider/Graph 0.
- 새 plan에 `candidate_mode="json"`, 선택 arm·순서·후보 wire hash·HEAD/code/raw/model/
  dataset/fixture/reference-time binding을 저장한다. 모드가 다르면 동일 plan으로 실행 불가.
- 기존 기본값 `omitted`, 해당 mode의 payload 및 strict validator 동작은 유지한다.

실행 전 자원 예산을 6 신규 호출에서 **3 신규 호출 + 3 baseline 재사용**으로 고정했다.
constrained baseline을 불필요하게 세 번째 반복하지 않는다. 성공할 때까지 같은 Trial을
반복하는 것이 아니며, v36 원 결과와 새 후보 결과의 기원/호출수/usage를 분리한다.
새 Trial의 실패도 그대로 보존하고 과거 결과를 신규 호출 성적으로 승계하지 않는다.

## 동일한 검수 기준

양 arm 모두 **동일한 원 JSON Schema와 actual Output owner validator**를 적용한다.
Markdown fence·설명문은 제거하지 않으며 invalid JSON/schema를 수정하지 않는다.
raw는 `UNREVIEWED`로 남기고 다음 owner-scoped 의미를 별도 검수한다.

| Case | 기대 업무 의미 | 명확한 실패 |
| --- | --- | --- |
| CORE-005 | 선택 Task 상태/기한 조회 → 빈 Output | 불필요 UPDATE/SEND 등 외부 변경 |
| CORE-017 | Draft 준비 → 현재 work-1의 GMAIL_DRAFT/CREATE | Draft 누락·effect 변경·불필요 WRITE |
| CORE-049 | 요청한 Task/Event/Draft 생성 결과 각각 현재 work-1에 귀속 | 필수 결과 누락·effect 변경·불필요 WRITE |

count/pair만으로 전체 업무 PASS라 하지 않는다. 이번 입력에서 PARTIAL로 완화할 근거는
추가하지 않는다. Source/시간 upstream 오판 및 Retrieval/Planning 이후의 업무 성공을
Output owner 점수로 재귀속하지 않는다. Approval/외부 실행은 미검증이며 실행하지 않는다.

## 명령

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_output_format_ablation --candidate-mode json --result-dir evaluation/results/<new-json-plan>
.venv/Scripts/python.exe -m scripts.evaluate_output_format_ablation --candidate-mode json --result-dir evaluation/results/<new-json-run> --execute-plan evaluation/results/<new-json-plan>/preregistered-plan.json --expected-plan-sha256 <printed-object-hash>
```

기본 명령은 모델 catalog/show 읽기와 plan 생성만 수행한다. 실제 generation은 root가
현재 코드/계획을 고정한 뒤 명시적 execute 명령으로 수행한다. 구현 단계 모델 실행 0.

장치 검증: 기존 omitted 동작과 JSON 모드/reuse 경계를 포함한 직접 테스트 **30 PASS**,
Ruff/mypy PASS. 실제 v36 raw를 사용한 HTTP 없는 dry plan에서도 신규 3 / 재사용 3,
original wire hash 3/3 일치, JSON mode의 format 값만 변경됨을 확인했다.
원 v36 raw SHA-256은 `c1f7c6e54c035dbb5baf556f310301599a78f93f5d756b8e320835cd8f646ef3`로
검증 전후 동일했고, omitted 세 행은 모두 `INVALID_JSON`을 유지했다.
이 dry 검증은 기존 model metadata를 사용했으며 실제 catalog 확인·모델 generation은 0이다.
정식 CLI plan은 live catalog/show metadata를 다시 읽어 동일 digest/parameters를 확인한다.
