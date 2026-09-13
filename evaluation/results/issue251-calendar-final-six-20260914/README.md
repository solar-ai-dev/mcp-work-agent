# Issue 251 Calendar confirmation 단발 검증

- 제품 SHA: `f825546e7e43fd335b39acc8c53b10a3b417450b`
- 브랜치: `codex/issue-251-connected-contract`
- 모델: `qwen3.5:9b` / digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature / seed: `0.0` / `null`
- Prompt: `request_understanding.identify_goal` `1.0.62` / `98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa`
- 자동 LangSmith tracing: 비활성

## 결과

| 단계 | 결과 |
| --- | --- |
| 최초 요청 | `WAITING_CONFIRMATION` |
| 같은 Run confirmation resume | `COMPLETED` |
| provenance mismatch | 없음 |
| canonical constraint | `USER_REQUIREMENT/search_terms` |
| Connector READ / Evidence | `0 / 0` |
| 제품 판정 | **FAIL** |

Run `70eeb6ca-1008-4c9b-afa3-61bb6170547f`은 confirmation을 한 번만 받았고 두 번째 confirmation 없이 종료됐다. 다만 답변은 Connector 조회 없이 생성된 `프로젝트 검토 회의` 미발견 문구이므로 근거 기반 성공으로 판정하지 않았다.

## 최초 남은 실패

confirmation resume의 owner-local materialization은 기존 ambiguity의 `target_resource`를 확인하고 exact response span을 `USER_REQUIREMENT/search_terms`와 `CONFIRMATION_RESPONSE` provenance로 보존했다. `detect_ambiguity`도 해소됐다.

그러나 확인 전 보존 대상인 Request Understanding 결과에 이미 다음 값이 들어 있었다.

- `resource_responsibilities.source_reads = []`
- `requested_resource_hints = []`

따라서 이후 `determine_io_resources`의 input route가 0개였고 Retrieval을 건너뛰었다. Connector 호출과 Evidence 없이 LLM이 미발견 답변을 만들었다. 확인 문구의 내용에서 Resource type을 추론하지 않고 기존 responsibility를 보존하라는 현재 제약 안에서는 이 Run을 더 고칠 typed authority가 없다.

Resource type을 어느 기존 typed owner가 보장할지에 대한 계약 결정 없이는 안전한 추가 수정이 불가능하다. 문자열 규칙, Prompt 변경, 전역 searchable field 추가, 새 State/Schema/Node/LLM 호출은 하지 않았다.

## 검증

- 직접 pytest: `96 passed` + 노드 경계 `3 passed`
- Ruff: 통과
- Calendar Production Smoke: 1회
- rerun-to-pass: 0
- confirmation response: 같은 Run에 1회
- Provider WRITE/SEND: 0
- 최종 6 Smoke: 미실행(Calendar 선행 Gate 실패)

## LangSmith

| Trace | root / node / LLM / tool |
| --- | --- |
| initial | `01a09ca4-5a89-7d81-8772-b9394c8daab5` — 1 / 6 / 6 / 0 |
| resume | `01a09ca4-cc37-75a2-a903-1c8f41349b78` — 1 / 19 / 4 / 0 |

두 Trace 모두 실제 제품 SHA/model/prompt/question binding과 일치했다.
