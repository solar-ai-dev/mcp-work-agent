# 064 v38 — 기존 raw의 엄격 단일 fence admission 재검증

기준 HEAD `01da655c` + 평가 전용 runner patch. 새 모델/Graph/Provider 호출 **0**.
`064-output-fence-admission-criteria.md`의 계약대로 v36 omitted3개와 v37 JSON-mode3개를
각각 재검증했다. 원 raw와 기존 strict 판정은 변경하지 않았다.

| 원 응답군 | 원 strict 구조 | 새 admission 후 구조 | 별도 Output 의미 검수 |
| --- | --- | --- | --- |
| v36 format_omitted 3개 | 0/3 | 3/3 |005 빈 Output,017 Draft CREATE,049 세 CREATE/work-1 유지 → 3 PASS|
| v37 format_json control 3개 | 3/3 | 3/3, 변환 없음 |005 UPDATE+SEND 오류 유지 → 2 PASS / 1 FAIL|

omitted의 세 결과는 응답 전체가 단일 lowercase `json` 코드펜스여서 외곽 wrapper만
제거했다. 본문은 원 schema와 실제 owner validator가 검증했고 Resource/effect/Work 의미를
추가·삭제·보정하지 않았다. JSON-mode의 005 오답은 문법 codec으로 바뀌지 않았다.

이는 **기존 관측의 새 candidate 해석**이며 새 성공 Trial이나 Product 실행 성공이 아니다.
v36 원 strict INVALID_JSON 3개, v37 원 판정, 상세 응답 hash를 그대로 보존했다.
새 구조 수용으로 Source·Goal·시간 오판 또는 전체 업무가 해결됐다고 하지 않는다.

다음은 이미 고정한 별도 Core5의 현재Prompt paired 비교다
(`064-output-fence-core5-criteria.md`). 새 의미 규칙·Few-shot은 추가하지 않는다.
Production parser/transport/Prompt/State는 아직 변경하지 않았다. **평가 후보로만 유지**하며
추가 Core의 기존 성공·반례와 실제 compiled 연결 전에는 Product 채택 근거가 부족하다.

직접 장치 검사 **51 PASS / 4.19초**, Ruff 및 runner scoped mypy PASS.
plain/no-tag/prose/다중·중첩·잘린 fence, 복수 JSON 문서, schema·금지 위반과 원 결과
보존을 확인했다. 구현 중 발견한 CRLF delimiter 잔여문자 문제는 모델 실행 없이 수정했다.

근거:

- `evaluation/results/064-output-fence-v38-revalidation/fence-revalidation.json`
  SHA256 `be43a0d06763cc7cc064a1b2ed474c32023a8f081d2b3ba3ccdf29e7a64697db`.
- 원 raw hash는 v36/v37 결과 문서와 동일하다. 재검증 결과에는 각 원 행의 hash와 원
  strict validation, 신규 admission/validation을 분리했다. 원 JSON-mode가 재사용한
  constrained baseline은 다시 분모에 넣지 않았다.
- 신규 모델 calls/tokens/latency는0이다. 과거 생성비용을 신규 호출로 합산하지 않는다.
  상세 결과는 로컬ignore보존, 비민감 요약·실행기·직접검사는 버전관리한다.
