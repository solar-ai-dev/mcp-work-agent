# 084 — conditional output의 discriminator 생성 순서만 비교

083의 직접 조회4회는 맞았으나 정리·인용 금지 반례2회는 원문 인용으로 실패했다.
정리 baseline2회는 두 사실과 금지를 보존해 의미 PASS다. 출력은 후보6/6에서
`items → mode`였다. FIRST의 방식·항목 선택 오류이며 validator 변형은 아니다.

## 단일 가설·기존 이력

확정 값을 전달하는 FACT_REFERENCES와 내용을 구성하는 PROSE의 선택 시점이
branch payload 뒤에 놓였다. 같은 schema의 각 branch `properties`에서 `mode`만
먼저 오도록 옮긴다. JSON Schema의 허용값·의미는 바꾸지 않는다. `required`는 이미
mode-first이며 그대로다. oneOf branch 순서(FACT 먼저), Prompt/SYSTEM 문자열,
본문 안의 정렬된 schema, input/snapshot, sampling/options는 모두083 그대로 유지한다.

생성 순서 자체는 미실험 방법이 아니다. 064 v11은 RU authority order를 시험했고
개선과 회귀가 섞였다. 이번은 다른 owner의 conditional union에서6/6 payload-first가
관측된 새 근거에 따른 제한 재시험이다. grammar가 실패의 원인이라고 사전 확정하지 않는다.

공식 Ollama v0.34.0의 [LLAMA_CPP_VERSION](https://github.com/ollama/ollama/blob/v0.34.0/LLAMA_CPP_VERSION)은
b10760이다. [generate/completion 경로](https://github.com/ollama/ollama/blob/v0.34.0/llm/llama_server.go#L1478)는
`JsonSchema json.RawMessage`로 format을 그대로 전달하고, 해당
[converter](https://github.com/ggml-org/llama.cpp/blob/b10760/common/json-schema-to-grammar.cpp#L948)는
properties 순서로 required 속성을 수집해 grammar에 연결한다. `required` 배열 순서와는
다르다. 로컬 llama-server --version의 `0f3a71be1`은 공식 b10760 commit prefix와
일치한다. 로드된 DLL까지 포함한 재현 빌드 동일성은 검증하지 않았다. map 변환을 거치는
chat 경로나 다른 backend까지 이 결론을 확대하지 않는다.

## 고정 예산·판정

- 083과 같은 실제 CORE005 lookup / synthetic completed / synthetic reformulation.
- 각 FIRST2회, 순서 lookup1/completed1/reformulation1/lookup2/completed2/reformulation2.
- 신규6회, repair/retry0, concurrency1, timeout180초. 실패도 모두 보존한다.
- 기존083의 후보6회와 실제 정리 baseline2회를 재사용하며 새 baseline 호출은 없다.
- 9B/Ollama/digest/seed/ctx/think/미전송 temperature·presence까지083 실제 wire와 동일.
- 최종 의미 기준도083 그대로: 올바른 prose lookup도 PASS, refs mode 자체를 금지하지
  않지만 실제 원문 인용으로 정리·금지를 잃으면 FAIL. 특정 bullet/checkbox 모양은 강제하지 않는다.
- payload schema가 재배열됐더라도 실제 출력이 mode-first가 아니면 그 사실을 기록한다.
  구조 통과를 의미 성공으로 해석하지 않는다. 자동 fallback이나 누락 값 보충은 없다.
- 정리 반례 해결과 기존 조회4개 보존이 함께 필요하다. 실패 시 이 순서 변경은 기각하며
  같은 문구 강화 대신 의미 선택·참조 전달의 책임 구조를 다시 판단한다.

## 봉인·범위

기존 object_hash/dict equality는 object property 순서를 보지 않는다. 그래서 실제
Product transport와 동일한 `json.dumps(payload).encode('utf-8')`의 SHA256과 branch별
property 순서를 별도로 봉인한다. loaded plan은 실행 전후 재계산하고 실제 response의
dispatch payload hash도 기록한다. plan 저장은 기존 order-preserving write_json을 사용한다.

Product source/활성 Prompt/Schema/State/Node/Approval 변경0. 외부 Provider/WRITE0.
고정 compose 입력의 진단이며 실제 새 RU, 전체 Workflow, Canonical92 성과가 아니다.
상세 raw는 evaluation/results/084-*에 보존한다.
