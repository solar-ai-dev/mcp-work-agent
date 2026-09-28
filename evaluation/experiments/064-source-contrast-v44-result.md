# 064 v44 — 대조 예시는 일부 범위를 고쳤지만 메일 근거를 누락: REJECT

## 실행과 단일 변수

SHA `bc1a619e8efb8b72643a6a0fb53218e70c34bcb0`. 사전 기준은
`064-source-contrast-v44-criteria.md`. 기존 Product Source one-call의 role·입력·Goal·선택
identity·Work·Schema·format·sampling을 유지하고 일반 입력→출력 예시 3개만 추가했다.
새 Draft / 기존 Draft 편집 / 여러 Task·Event를 근거로 새 Draft 준비의 대조이며,
현재 Core 원문/Fixture/Gold는 예시에 넣지 않았다. v43 분리나 v42 penalty는 적용하지 않았다.

Core005/009/017/049/059 후보 각1회, 별도 합성 Draft UPDATE/CREATE 후보 각1회:
**새7 calls / baseline7 재사용 / rerun·repair·codec0**. Core baseline은 v42 실제 default5,
합성 baseline은 v43 실제 baseline2. 재사용 시 원 row/파일/wire와 현재 Product assembler,
schema/owner validation·Dataset·Fixture·runtime을 대조했다.

qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
Ollama0.34.0, temp0.05/seed20260923/ctx16384/think=false/기본presence1.5/180초.
실행은 2026-09-28 13:04:35~13:05:47 UTC에 한 번 순차 수행했다.

## 의미 결과 — 원문·필수 사실 기준

7개 모두 strict 구조 검증을 통과했고 raw JSON과 validated output이 같았다.
따라서 아래 최초 차이는 validator/조립이 만든 값이 아니라 **Source FIRST 생성**이다.
독립 wire/input/dual-schema/options 재구성7/7, 원 baseline 승계7/7, 코드·Prompt 의존
hash32/32도 일치했다. 실제 role+예시 hash와 후보 PromptRef 결속도 확인했다.

| Case | baseline → 후보 | 실제 결과와 최초 차이 |
| --- | --- | --- |
| CORE-005 | PASS → PASS | 선택 Task의 상태·기한 및 SINGULAR 유지. title/notes 추가를 개수만으로 오답 처리하지 않음 |
| CORE-009 | FAIL → FAIL | baseline은 메일만 골라 Task를 잃었는데, 후보는 Task만 골라 **메일 내용을 잃음**. 필수 Source 누락 대상만 바뀜 |
| CORE-017 | PARTIAL → PASS | 불필요한 기존 Draft 조회를 제거하고 Task 목록·Event의 필요 사실 및 **CRITERIA**를 보존. 입력에 없는 검토회의 시각을 만들어내지는 않음 |
| CORE-049 | PARTIAL → FAIL | 메일 Source를 모두 누락하고 **새 Task 제목/기한·새 Event의 계획 시각을 조회할 기존 사실로 요구**. Draft 과선정 제거만으로 성공이라 할 수 없음 |
| CORE-059 | PASS → FAIL | 실제 Canonical reply SEND에 필요한 **기존 메일 Source가 전부 NOT_REQUIRED**. 과거 Quartz UPDATE로 채점하지 않음 |

Core Source-only **2 PASS / 2 PARTIAL / 1 FAIL → 2 PASS / 0 PARTIAL / 3 FAIL**.
017 개선과 동시에 기존 성공059 회귀, 049 악화. 독립 재검수도 같은 판정이다.
Source 종류/Tool 개수·정확 문장 대신 필요한 사실·역할·scope·Work 보존으로 판단했다.

별도 합성 Source-only **1 PASS / 0 PARTIAL / 1 FAIL → 2 PASS / 0 PARTIAL / 0 FAIL**:
UPDATE는 현재 선택 Draft의 본문·보존값을 요구해 유지, CREATE는 모든 값이 제공되고
다른 자료 조회를 제외한 요청에서 기존 Draft를 요구하지 않게 개선됐다. 이 control은
실제 upstream/Provider를 실행하지 않은 hand-authored owner 입력이며 Core/92 분모에 합치지 않는다.

## 판단과 다음 책임 경계

**REJECT / Product 유지.** 예시와 가까운 Task/Event 및 Draft 경계는 개선됐지만 새로운
요청의 메일 Source를 잃었다. 단일 호출·계약 유지의 장점도 회귀를 상쇄하지 못한다.
메일 예시를 더 붙여 점수를 올리는 식의 연속 Prompt patch는 하지 않는다.

별도 코드 검토에서 `validate_source_dependency_semantics()`가 Source0/Output0 상태를
Goal의 `search_terms/business_concepts`가 있다는 이유만으로 거절하는 공통 경계를 발견했다.
이 슬롯은 외부 사실이 필요하다는 typed 증명과 동일하지 않으므로, 제공된 메모만 찾아
정리하는 정당한 no-READ 결정을 거절할 가능성이 있다. 그러나 현재 v44는 해당 caller를
실행하지 않았으며 이 경계가 이번 Source 실패의 원인이라는 주장은 하지 않는다.
단순 guard 제거는 실제 외부 Source 누락도 놓칠 수 있다. 다음은 추가 모델 호출 전에
실제 caller의 제공자료 반례/정상 외부조회/실제 Source 누락을 component로 대조한다.
검증기 완화나 Product 수정으로 즉시 채택하지 않는다.

## 비용·자원·검증 범위

| 집합/arm | calls | 입력/출력 tokens | reported latency 합계 |
| --- | ---: | ---: | ---: |
| Core baseline 재사용 | 5 | 20,442 / 1,119 | 51,211ms |
| Core 후보 신규 | 5 | 25,407 / 950 | 54,518ms |
| 합성 baseline 재사용 | 2 | 7,677 / 328 | 15,774ms |
| 합성 후보 신규 | 2 | 9,663 / 300 | 16,181ms |

신규 총7회, 입력35,070/출력1,250 tokens, reported70,699ms/wall71,060ms/load6,732ms,
usage 누락0. 예시로 입력이 늘었으며 재사용 baseline은 동시 paired 비교가 아니므로
지연 비율을 일반 성능 개선/악화의 인과 수치로 주장하지 않는다. 1회 결과는 반복 안정성이 아니다.

단일 모델만 사용하고 모델 실행 중 테스트/편집0. 시작 RAM 여유19.91/31.71GiB,
GPU0/8,188MiB·49°C; 중간6,383MiB·64%·72°C; 종료 RAM 여유17.43GiB,
GPU6,385MiB·0%·56°C. snapshot이지 peak나 호스트 전체 사용 원인 분석이 아니다.
다른 사용자 프로그램 종료·Frontend/Backend 재시작0.

실행 전 직접·기존 도구 회귀 **175 PASS/35.28초**, Ruff check/format·mypy PASS.
이 테스트는 구조/기록/재실행 차단 근거이며 모델 의미 PASS로 승계하지 않는다.
Product/활성 Prompt/Schema/State/Node/승인·권한·실행 계약 변경0.
Graph/Provider/WRITE/SEND0. Holdout/Stress tuning·전체92 실행0.
불필요 WRITE 의미는 Output owner를 실행하지 않아 평가하지 않았고 실제 WRITE는0이다.
다중 Work·실제 upstream RU→Route·Retrieval/Planning 이후 업무 성공은 미검증이다.

## 재현

- raw `evaluation/results/064-source-contrast-v44-t1/raw.json`: SHA256 `de719b1b3b5b66b8f2b399f30ac3451bdd8e1db963ce9bfaded6e2d4f0ad6aa5`.
- plan `evaluation/results/064-source-contrast-v44-plan/preregistered-plan.json`: object SHA256 `dbae46e3a42326e004b8e2e394bd88a612104169458124bc2c925e94a138bf8a`, bytes SHA256 `5f3ca45c45679517a14bc8ee9e21a8255a7abe7ba7208bd9eba0c7d4e5d28cf5`.
- Dataset SHA256 `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`; Fixture SHA256 `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
- Core 원 raw SHA256 `f5b40bd0d4e36e0f7d9138d00d9d0bdd45cbebc5cd954a110ced1d3a50c6ee52`, 합성 원 raw SHA256 `b5a6419ec305e213d01d377b6b91eb04310752af923a380de3037fdb442897ac`.
- 상세 raw는 로컬 ignore 영역, 본 문서는 원격 검토용 비민감 요약이다. raw의 semantic_verdict는 UNREVIEWED로 보존하고 위 수동 재검수를 별도로 기록했다.
