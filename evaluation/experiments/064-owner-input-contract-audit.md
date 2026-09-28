# 064 — Owner 입력 계약과 기존 재시도 이력 감사

## 범위와 결론

- 검토 기준 HEAD: `2e943ab9cafc94120d35a74985737c7e0e3b080a`.
- 기존 코드·실험 문서·로컬 raw를 읽어 대조했다. 이 감사의 신규 모델/Provider/테스트 실행은 0이다.
- 제품 코드·활성 Prompt·Schema·manifest 수정은 0이다. 아래 내용은 새 후보의 채택 결과가 아니다.
- **Source는 이미 생성 Goal 문자열 대신 사용자 원문을 받고 있다.** 이를 처음 도입하는 것처럼 반복하지 않는다.
- Output Prompt의 **금지 effect가 Schema에서 제외된다는 설명**은 현재 work-local validator 계약과 불일치한다. 설명 불일치는 확정이지만 실제 모델 오판의 인과 원인으로 확정하지 않는다.

## 1. 현재 Source 입력과 과거 raw

`src/google_work_agent/application/agents/request_understanding/identify_goal.py:345`의 Source 호출은
`project_extractive_source_goal`을 사용한다. 해당 helper
(`preserve_explicit_search_anchors.py:92`)는 다음과 같이 투영한다.

- `goal`은 현재 사용자 요청 원문으로 대체한다.
- `completion_conditions`는 빈 배열로 만든다.
- search terms/business concepts/person/sender/recipient/subject는 현재 원문에 결속되는 값만 남긴다.
- `additional_constraints`는 비운다. period/coverage/analysis 등 나머지 값 전체를 없애는 것은 아니다.
- 공통 `_prompt_input`은 별도로 `user_request`, `requested_work`의 WorkUnit/provenance,
  selected refs, reference time을 전달한다(`identify_goal.py:812`).

따라서 **생성 Goal 문자열은 없지만 모든 생성형 의미 입력이 제거됐다는 뜻은 아니다.**
남는 제약·analysis·Work 귀속이 Source 판단에 어떤 영향을 주는지는 각각 실제 입력으로 구분해야 한다.

기존 raw 재조회 결과:

| 기존 실행 | Source FIRST 관측 | 원문/Work 입력 확인 |
| --- | ---: | --- |
| 062 v4 Canonical92 | 90건 | 90/90에서 `goal_candidate.goal == user_request`, completion 빈 배열, requested_work 존재 |
| 062 v5 preflight | 5건 | 5/5에서 동일 조건 |

v4의 나머지 두 Case는 Source FIRST까지 도달한 결과가 아니다. 90건을 92건의 Source 의미 통과로 세지 않는다.
Work provenance가 입력에 있다는 사실도 업무 분해·귀속의 의미 정확도를 보증하지 않는다.

Raw 근거(ignored, 원격에는 이 요약만 보존):

- `evaluation/results/ru-goal-output-modality-v4-canonical92-trial1-20260924/raw.json`
  — `c5dac5ee0c1e6ebea6b4b71c7a3ca5a670d8004b40603e49f800708c5770ef5f`.
- `evaluation/results/ru-result-mode-first-v5-preflight-20260924/raw.json`
  — `0d2af439f5532c71dfb09b1229818932ec1db084a1196e859bbd4555b36fed28`.

## 2. 이미 시험한 입력/authority 축

| 실험 | 실제로 바꾼 경계 | 관측과 재시도 제한 |
| --- | --- | --- |
| 003 request-only | 기존 extractive Source Goal에서 파생 constraints까지 전부 빈 동일 구조로 제공. 원문/선택/시간/catalog/Prompt/Schema 유지 | Core6 유효 1/6→1/6. 011 과잉 감소와 014 유지가 있었지만 015 FreeBusy 누락, 024 Gmail·Task·FreeBusy 손실, 028 과잉 증가. REJECT. 단순 constraints 일괄 삭제를 개선책으로 재사용하지 않는다. |
| 062 v4 | Goal·result modality·Output 공동 authority, Source/prohibition 별도 유지. 당시 Work는 token-ref 후보 | 불필요 WRITE 감소 근거는 있지만 Source 누락은 남았다. Source 원문 투영을 새로 도입한 후보가 아니다. 역사적 전체 점수는 063의 재판정 제한과 함께 읽는다. |
| 062 v5 | Registry Output 후보를 숨긴 result-mode-first | Source-input 실험이 아니다. 009는 개선됐지만 012 Draft/059 SEND를 ANSWER_ONLY로 낮췄다. 5건 3 PASS/2 FAIL, REJECT. |
| 063 v7 | 원문→생성형 information need→Source ref 결속의 두 호출 | 023/027의 첫 need가 메일·Task 의미를 Calendar로 바꿨다. 049 복수 자료는 one-source-per-need와 충돌했다. 중간 재해석 추가를 그대로 반복하지 않는다. |
| 063 v8 | v4의 modality를 유지하며 Source/Output 역할을 공동 생성 | corrected Core9에서 v4 3/2/4, v8 3/1/5(PASS/PARTIAL/FAIL). 045 복구가 있었지만 023 Task 누락 회귀, 009 SEND/CREATE 오판이 남았다. REJECT. |
| 064 v15/v18 | 원문/Work에서 coarse Source family 선택 후 subtype 판단, 이어 실제 family를 positive typed handoff | v15 후단이 025/027/045/049의 필요한 family를 다시 제외했다. v18은 일부 family 보존을 강제했지만 025는 repair 후에도 결속 실패, 013의 잘못된 EMAIL/Draft를 고정했다. retention 자체를 의미 개선으로 세지 않는다. |
| 064 v20 | 기존 검증된 Output authority를 Source 입력에 read-only 전달 | 013 Task/Event 접근은 남았지만 잘못된 Draft Source도 남음. 023/025는 Google Source 9종, 049는 Source 모두 소실. baseline013 FIRST에도 Task/Event가 있었으므로 그 회복을 후보의 새 의미 이해로 계산하지 않는다. REJECT이며 실제 acquisition 영향은 별도 연결 검증 대상이다. |
| 064 v21 | 공동 Goal owner의 생성 schema에서 goal 제거, 반환 goal에는 원문 복사 | Source 실행은 없다. 009 SEND 회귀, 023 Task 완료 요구, 049 completion의 작업 완료 의미가 불명확하다. 025 title 강제/027 메일 발송시각 치환은 없어졌지만 Source 개선 증거는 아니다. REJECT. |
| 064 v22 | system에 동일 입력이 있음을 확인하고 wire prompt의 중복 input JSON만 제거 | fresh Source paired comparison에서 025 Mail/Task 소실, 027 근거 Source 손실 및 임의 09:00~10:00 생성. 비용은 줄었지만 의미 회귀로 REJECT. 원문 자체를 제거한 실험이 아니다. |

근거 문서:
`003-request-source-decision-input-projection.md`,
`062-request-understanding-semantic-authority.md`,
`063-source-demand-binding.md`, `063-semantic-review.json`,
`064-authority-order-and-binding.md`, `064-source-semantic-boundary-review.json`,
`064-goal-order-review.json`.

### Runtime 비교 제한

- 003은 당시 SHA `8055af4c`, seed1729의 Source owner 비교다. 현재 V3 Work/동일 Product Runtime의 paired 결과가 아니다.
- 062 v4는 SHA `7056682a`, seed20260923이다. 기본 temperature0 기록을 모든 owner의 실효값으로 읽지 않는다. Product router의 Goal0.1/Source0.05 override와 직접 v4 Goal0을 구분한다. 과거 raw에는 wire 관측이 없어 실측처럼 소급 확정하지 않는다.
- 063 v6/v7/v9 직접 Source는0, v10과 v15의 Product Source는0.05였다. v15→v18도0.05→0 차이가 있어 sampling까지 같은 단일변수 비교가 아니다.
- v20은 Product Source의 실효0.05를 재사용했다. v22는 같은 frozen input/schema/system/model/Source0.05/seed/timeout의 fresh 대조가 있다. 두 arm의 HEAD 차이는 confirmation 수정으로 frozen Source 호출 내용은 불변이었다. 동일 전체 Product SHA의 connected 평가라고 부르지 않는다.
- 현재 `production_goal_output_candidate.py`의 connected v4는 **현재 Product Work owner**를 그대로 사용한다. 옛 v4의 token-ref Work 변경은 포함하지 않으며 joint Goal temperature0 외 다른 owner sampler를 바꾸지 않는다. 옛 v4 전체 결과를 현재 연결 성공률로 승계하지 않는다.

## 3. Output Prompt와 work-local 금지 계약의 불일치

확정된 불일치:

- `src/google_work_agent/application/prompt_runtime/sources/request_understanding.identify_output_responsibilities.md:9`는
  `FORBIDDEN` effect가 Schema 선택지에서도 제외된다고 설명한다.
- 실제 `identify_output_responsibilities.py:191`은 `build_output_responsibility_output_schema`에
  `prohibited_effects`를 전달하지 않는다. Schema는 Registry의 Resource/effect capability를 닫는다.
- 같은 파일 `:199/:249`의 validation은 각 Output `work_unit_ids`에 적용되는 금지와 비교하고,
  위반 시 `REQUEST_PROHIBITED_OUTPUT_EFFECT_SELECTED`로 기존 bounded revision 경계에 돌려보낸다.
- `50ff0879`에서 전역 금지 평탄화를 제거하고 work-local validation으로 교정했지만 위 설명은 남았다.
- 기존 `tests/unit/application/agents/request_understanding/test_identify_effect_prohibitions.py:202`는
  work1 CREATE 금지와 work2 CREATE 허용을 구분하는 반례다. 이 감사에서는 테스트를 새로 실행하지 않았다.
- Canonical06의 item-owned `work_unit_ids`와 atomic semantic ownership은 유지해야 한다.

이는 **설명/실제 계약의 미정합**이다. 이를 이유로 모든 업무에서 금지 effect를 enum에서 전역 제거하면
다른 Work의 합법적인 요청까지 차단하는 회귀다. 현재 validator가 금지를 없애거나 무시하는 결함이라는 뜻도 아니다.
잘못된 `NOT_FORBIDDEN` 생성은 앞 금지 owner의 의미 실패이며, 이 문장 하나가 그 원인이라고 단정하지 않는다.

별도 미확정 표현:

- 같은 Prompt의 “같은 후보를 중복하지 않는다”는 exact duplicate 금지로 읽으면 현재 validator와 맞는다.
- 이를 같은 Resource/effect의 모든 복수 결과 금지로 읽으면 바로 앞 `:7`의 독립 결과 유지와 충돌한다.
- 현재 근거만으로 어느 해석이 실제 모델 실패를 유발했는지 확정하지 않는다. 별도 확정 결함이나 실패 건수로 합산하지 않는다.

## 4. 다음 선택의 제약

1. Source에 원문/Work span이 없다는 가정으로 “Goal 원문화”를 반복하지 않는다. 남아 있는 typed 입력과 실제 실패 FIRST를 먼저 대조한다.
2. constraints 일괄 삭제, 생성형 needs 추가, Source/Output 전면 fusion, 중복 envelope 제거를 재시도하려면 기존 실패와 달라진 계약·입력 또는 새 근거가 필요하다.
3. v20의 부분 Source 회복과 과잉 선택은 실제 Query/READ/Evidence 소비 결과 없이 업무 PASS/FAIL로 확정하지 않는다. schema repair의 손실을 Source FIRST의 의미 실패와 구분한다.
4. Output 설명을 정합화한다면 기존 work-local 금지와 Registry capability 책임을 정확히 기술하는 범위다. 새 금지 규칙/예시나 전역 Schema 강제를 추가하지 않는다. 활성 Prompt/manifest/hash 변경은 별도 결정·검증으로 수행한다.
5. owner-only, RU→ToolRoute, 실제 MainGraph 업무 결과를 분리한다. 이번 감사만으로 신규 후보를 채택하거나 과거 실패 Trial을 대체하지 않는다.

## 감사 이후 확정 설명 정합화

Core8 continuation이 종료된 뒤 Output Prompt의 잘못된 Schema-exclusion 한 문장을 기존
work-local prohibition과 Registry Schema의 책임 설명으로 교체했다. Output slot만
1.1.0→1.1.1, source hash는 `1ab2409d3e762d7077b9fdf170bbc786330c1f12ee4eaf6ef90ea0460b28a7f5`다.
규칙·예시·semantic validator·출력 Schema·전역 effect filter는 추가하지 않았다.
DRAFT와 모든 미검증 activation flag를 유지하므로 production signed release 승격이 아니다.
이 수정은 설명/실제 계약 정합화이며 005/009 등의 LLM 오판이 해결됐다는 주장이 아니다.
기존 Core8 결과와 hash는 수정 전 조건으로 보존하고 새 모델 성공률을 소급 부여하지 않는다.
기존 work1 금지/work2 허용 반례 및 registry/hash/release gate 검사 **34 PASS**, Ruff PASS.
새 모델·Provider 호출은 0이다.
