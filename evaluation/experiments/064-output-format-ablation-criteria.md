# 064 — Output FIRST format-only owner 진단 사전 기준

## 범위와 가설

기존 v35 connected raw의 **같은 Output FIRST 입력**에서 Ollama top-level `format`
유무만 비교한다. constrained decoder가 원문의 READ와 요청 Output 선택에 영향을 주는지
보는 bounded 진단이며 Prompt 문구나 Product 책임을 수정하지 않는다.

- CORE-005 `production`, CORE-017/049 `work-span-codec-v35`의 원 Output FIRST 사용.
- 3 inputs × `schema_constrained` / `format_omitted` × 1 trial = **6 HTTP generation calls**.
- 순서는 Case별 005 baseline→candidate, 017 candidate→baseline, 049 baseline→candidate.
- 원 instruction/input/PromptRef/본문 schema/model digest/options/seed/think 모두 동일.
- 실제 Product assemble/transport가 재구성한 payload의 hash가 원 `wire_sha256`와
  동일해야 실행 가능하다. candidate는 top-level `format` 키 하나만 삭제한다.
- Graph/upstream 재실행, Provider 호출, repair/retry/semantic revision, 실패 Trial 교체 0.
- arm당 timeout 180초, 직렬 1개. 원 runtime repair budget은 입력 근거로 보존하지만
  이번 FIRST-only 실험은 이를 소비하지 않는다. 전체 workflow의 runtime 평가가 아니다.

Canonical15 §9.6 EVALUATION의 Output transport-envelope 비교 범위를 따른다.
Product Prompt/Schema/State/activation을 바꾸지 않는다.

## 결과 관측과 사전 의미 기준

raw는 항상 `semantic_verdict=UNREVIEWED`, 업무 성공 `NOT_EVALUATED`로 저장한다.
두 arm 모두 원 output schema와 실제 `validate_output_responsibility_candidate`를 적용한다.
invalid JSON, schema 오류, prohibition/closed binding 오류를 각각 보존하며 수정하지 않는다.
아래는 후속 사람 검수용 **현재 frozen owner 입력에서의 Output-only 기준**이지 새 Gold가 아니다.

| Canonical Case | Output owner가 보존할 의미 | 명확한 실패 |
| --- | --- | --- |
| CORE-005 | 선택 Task 상태·기한 조회. 외부 변경 요청 없음 → 빈 Output | UPDATE/SEND 등 요청하지 않은 WRITE 선택 |
| CORE-017 | 충돌 안내 Draft 준비 → GMAIL_DRAFT/CREATE를 현재 work-1에 결속 | Draft 누락, 즉시 SEND/Calendar 변경 등 불필요 WRITE |
| CORE-049 | Task·Event·Draft의 요청된 생성 결과를 각각 현재 work-1에 결속 | 필요한 생성 결과 누락, effect 변형, 요청하지 않은 WRITE |

세 Case에 PARTIAL로 완화할 추가 근거를 두지 않는다. count/Resource-effect 쌍만으로
전체 의미 PASS라 하지 않는다. 각 원문/확정 Work binding/금지와 해당 Output 결정이
일치하는지 확인하며, Approval 전 외부 생성이 완료됐다고 간주하지 않는다.
원 historical Output owner 판정은 005 FAIL / 017 PASS / 049 PASS다. 새 두 arm은 각각
고정 횟수의 별도 결과이며 과거 호출을 새 분모·점수로 승계하지 않는다.

017의 Source 오류, 049의 upstream 시간 오류는 이번 Output owner에 재귀속하지 않는다.
후속 Source/Route/Retrieval/Planning/Approval/Execution 성공은 이번 범위에서 미검증이다.

## 실행·보존

`scripts/evaluate_output_format_ablation.py`의 기본 명령은 read-only model catalog/show와
payload 재구성을 통해 preregistered plan만 생성한다. 실제 모델 생성은 `--execute-plan`과
출력된 plan object hash가 함께 있어야 가능하다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_output_format_ablation --result-dir evaluation/results/<new-format-plan>
.venv/Scripts/python.exe -m scripts.evaluate_output_format_ablation --result-dir evaluation/results/<new-format-run> --execute-plan evaluation/results/<new-format-plan>/preregistered-plan.json --expected-plan-sha256 <printed-object-hash>
```

plan은 current HEAD, 실행/validator/Prompt 관련 코드 hash, 원 calls/raw/plan hash,
실제 model digest/show metadata, dataset/fixture hash, Case reference time/fault binding,
원 입력과 payload를 결속한다. 실행 전 같은 조건인지 다시 확인한다.
결과는 `evaluation/results/`의 새 디렉터리에만 저장하고 plan별 영구 실행 claim으로
동일 plan을 재실행할 수 없게 한다. STARTED 및 반환/실패를 각 arm마다 저장한다.
Provider thinking 본문은 저장하지 않고 presence/문자 수만 남긴다.

구현 준비 중 신규 모델 실행 0. 실제 실행과 결과 검수는 고정 SHA/plan 승인 후 root 담당.

직접 장치 검증: `tests/evaluation/test_evaluate_output_format_ablation.py` **19 PASS**.
fake HTTP로 format-only 차이, 같은 schema/owner validator, invalid JSON/schema/prohibition,
timeout 보존·retry 0, 6회 직렬 실행·incremental 저장, 추가 Trial·중복 claim·기존 결과 덮어쓰기
거절을 확인했다. 실제 지정 raw 3개의 payload 재구성은 HTTP 없이 원 wire hash **3/3 동일**.
이는 모델 품질 판정이 아니다.
