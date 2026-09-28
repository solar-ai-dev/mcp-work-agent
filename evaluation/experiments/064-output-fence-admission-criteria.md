# 064 — 단일 JSON fence admission의 비활성 재검증

## 범위와 계약

v36 format 생략 결과는 내용 관측과 별개로 strict JSON 통과 0/3이었다. v37 JSON mode는
strict 형식은 통과했지만 CORE-005의 불필요 UPDATE/SEND가 재발했다. 이번 후보는 새 모델
호출 없이 이미 있는 원 응답의 **transport admission**만 비교한다.

Canonical15 §9.6 EVALUATION에 한정한다. Product parser/Prompt/State는 변경하지 않는다.

- strict JSON 파싱에 실패했을 때만 평가 전용 fence admission을 시도한다.
- 응답 전체가 lowercase `json` 태그, LF 또는 CRLF 개행, 본문, 독립 닫는 fence로 이루어진
  단일 블록이어야 한다. 외곽의 ASCII 공백·탭·CR·LF만 허용한다.
- no-tag, 다른 tag, 설명문, 다중/중첩/잘린 fence는 거절한다. 내부 문자열의 triple backtick도
  이 좁은 후보에서는 거절한다. 임의 위치에서 JSON을 찾아 추출하지 않는다.
- 본문은 그대로 기존 `json.loads` → 원 output schema → actual Output owner validator에
  전달한다. 중복 JSON 문서·잘린 JSON·schema/금지 오류는 기존 검증으로 거절한다.
- raw 본문, 원 strict 실패와 새 admission/validation을 분리 저장한다. 의미 수정·repair·
  Markdown 제거 후 원 Trial의 PASS 재분류가 아니다.

## 근거와 분모

`064-output-format-v36-t1/raw.json`의 format_omitted 3건과
`064-output-json-v37-t1/raw.json`의 format_json 3건을 재검증한다. v37이 이미 재사용한
constrained 행은 다시 분모에 넣지 않는다. 신규 모델/Provider 호출은 0이며 재사용 관측만 6건이다.
각 raw/행/input/wire/schema/Product dependency hash와 기존 validation 일치를 확인한다.
원 파일을 수정하지 않고 별도 `fence-revalidation.json`에 결과를 기록한다.

새 admission 결과의 구조 수용은 업무 성공과 별개다. CORE-005 빈 Output, CORE-017
Draft CREATE, CORE-049 Task/Event/Draft CREATE라는 기존 Output-only 의미 기준을 유지한다.
raw 의미 판정은 `UNREVIEWED`이며 Root의 별도 검수 대상이다. Source/시간/전체 workflow
실패를 이 transport 비교로 해결했다고 주장하지 않는다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_output_format_ablation --result-dir evaluation/results/<new-offline-regrade> --regrade-fenced-raw evaluation/results/064-output-format-v36-t1/raw.json --regrade-fenced-raw evaluation/results/064-output-json-v37-t1/raw.json
```

이 모드는 model catalog/show/generation 및 Graph를 호출하지 않는다. 기존 model 실행
명령과 동시에 사용할 수 없고, 동일 출력 파일은 덮어쓰지 않는다. 후속 실제 모델 실험은
이번 후보 구현에 포함하지 않으며 root가 별도로 선택한다.

## 구현·직접 검증 결과

관련 단위 테스트 **51 PASS**, Ruff/mypy PASS. 첫 실행에서 CRLF 닫는 줄의 CR이 본문에
남는 후보 codec 오류 1건을 확인해 delimiter 처리만 수정한 뒤 재검증했다. Product 파일,
기존 strict parser/validator, Prompt 및 생성 runtime 변경은 0이다.

별도 모델0 재검증 보고서:
`evaluation/results/064-output-fence-v38-revalidation/fence-revalidation.json`
(SHA-256 `be43a0d06763cc7cc064a1b2ed474c32023a8f081d2b3ba3ccdf29e7a64697db`).

| 원 관측 | 원 strict 결과 | 새 admission 결과 | 내용 관측 |
| --- | --- | --- | --- |
| v36 format_omitted 3건 | INVALID_JSON 3 | 동일 본문의 schema/owner 수용 3 | 005 빈 Output, 017 Draft CREATE, 049 Task/Event/Draft CREATE |
| v37 format_json 3건 | VALIDATED 3 | strict 결과 그대로 3 | 005의 UPDATE/SEND도 그대로 남음; admission이 의미를 고치지 않음 |

v36 원 raw hash `c1f7c6e54c035dbb5baf556f310301599a78f93f5d756b8e320835cd8f646ef3`,
v37 원 raw hash `2fa4d1c6ff77bdb16df7b4e80e72609df60a526de391eee86b885cb4be5a19ed`는
전후 동일하다. 관측 6건은 재사용이며 신규 모델/Provider 호출 0이다. 원 v36의 strict
0/3 판정을 유지하고, 새 admission의 구조 수용을 전체 의미/업무 성공으로 승격하지 않았다.
