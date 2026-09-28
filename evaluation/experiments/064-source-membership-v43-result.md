# 064 v43 — membership 고정만으로 세부 의미는 보존되지 않음: REJECT

## 고정 구조·실행

실행 SHA `29bfa570ab54ebdab733310a88f78e653ecdf377`. 사전 기준과 합성 입력은
`064-source-membership-v43-criteria.md`, `064-source-membership-v43-controls.json`이다.
첫 호출은 모든 개별 Resource의 필요/불필요만 명시하고, 둘째 호출은 선택을 변경하지 않고
그 Resource의 필요 사실·대상 범위·Work binding만 작성했다. 기존 Product decision으로
투영해 기존 owner validator를 적용했다. 새 need 문자열/family 재판정은 없다.

Core005/009/017/049/059는 v42의 실제 default baseline 5개를 재사용하고 같은 입력으로
후보를 각 1회 실행했다. 별도의 합성 기존 Draft UPDATE/값이 제공된 Draft CREATE는
baseline/후보를 각 1회 실행했다. 신규 **15 calls / 사전 최대16**, 기존 baseline5 재사용.
CREATE 후보가 명시적으로 Source 0을 선택해 둘째 호출을 생략했다. 실패 대체·추가 재실행0.

qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
Ollama0.34.0/llama-server b10760, temp0.05/seed20260923/ctx16384/think=false/180초.
presence override는 없고 실제 backend15개 sampling 기록에서도 기본1.5를 확인했다.
v42에서 기각한 penalty=0이나 v41 지시 축소 후보를 채택해 얹은 실험이 아니다.

## 구조 결과와 최초 의미 차이

신규 **15/15 strict VALIDATED**, 최종 Source 후보 **Core5/5 + 합성2/2 구조 통과**다.
payload/input/dual-schema/wire hash 15/15, 실제 membership→details 부모 결속6/6,
baseline 원 row/검증값5/5, 코드·Prompt·계약 hash26/26을 독립 재구성해 확인했다.
구조 검증·전달 성공을 의미 성공으로 바꾸지 않았다. raw는 UNREVIEWED / NOT_EVALUATED다.

| Case | baseline → 후보 | 실제로 달라진 의미와 최초 경계 |
| --- | --- | --- |
| CORE-005 | PASS → PASS | 선택 Task의 상태·기한 및 SINGULAR 유지. title/notes 등 과넓은 fact 명세는 관측으로 남기되 개수만으로 실패 처리하지 않음 |
| CORE-009 | FAIL → PASS | **membership에서 TASK 누락 회복**, details도 메일 내용·Task 메모/기한/상태를 보존. Thread/Message 병행과 TaskList 보조 경로 자체를 감점하지 않음 |
| CORE-017 | PARTIAL → FAIL | membership은 잘못된 기존 Draft Source를 제거하고 Task/Event를 유지. **details에서 TASK를 SINGULAR로 축소**하고 현재 작업 목록을 ‘현재 진행 중인 작업’으로 작성. 상태 filter가 실제 적용됐다는 주장은 하지 않음 |
| CORE-049 | PARTIAL → FAIL | membership의 기존 Draft 혼동이 남음. **details에서 새 Task 제목·마감일, 새 Event의 계획 시각, 새 Draft를 조회할 기존 대상의 사실로 요구**하고 전체 Source를 SINGULAR로 좁힘 |
| CORE-059 | PASS → PASS | 실제 현재 Canonical의 reply SEND에 필요한 메일 내용/이력 보존. 과거 Quartz Draft UPDATE Smoke로 채점하지 않음 |

Core Source-only: **2 PASS / 2 PARTIAL / 1 FAIL → 3 PASS / 0 PARTIAL / 2 FAIL**.
기존 PASS2개는 유지했고 009는 개선됐지만, 기존 PARTIAL2개의 필수 의미가 더 훼손됐다.
PASS 수 증가만으로 채택하지 않는다. 모든 Work binding은 work-1이라 다중 Work 안정성
증거도 아니다. Source 종류 개수나 가능한 parent/대안 경로를 업무 정답으로 고정하지 않았다.

| 별도 합성 control | baseline → 후보 | 의미 |
| --- | --- | --- |
| 기존 Draft UPDATE | PASS → PASS | 양쪽 모두 현재 Draft의 본문·수신자 등 보존값 조회 필요, SINGULAR와 선택 Work 유지 |
| 값이 제공된 새 Draft CREATE | FAIL → PASS | baseline은 외부 자료를 조회하지 말라는 입력에도 기존 Draft를 필수로 요구. 후보는 Source 전부 NOT_REQUIRED, details 호출0 |

합성 Source-only **1 PASS / 0 PARTIAL / 1 FAIL → 2 PASS / 0 PARTIAL / 0 FAIL**.
이 합성 입력은 원문을 그대로 Goal로 두고 빈 조건/단일 Work를 만든 owner component control이다.
실제 upstream·Provider fixture·92개 Case 결과라고 하지 않고 Core 분모에 합치지 않는다.
Source0은 정책·승인 검사 생략이나 실제 CREATE 성공을 뜻하지 않는다.

## 해석과 판단

**REJECT / Product 유지.** 필요 Resource를 고정해 전달하는 연결은 통과했지만 Source 선택
오류가 모두 해결되지 않았고, 세부 사실/범위 단계에서 새 의미 손실이 생겼다. Core 호출을
5→10으로 늘린 비용에 비해 수평 품질 이득이 충분하지 않다. 뒤 단계에서 오류를 코드로
고치거나 틀린 첫 membership을 정답으로 교체하지 않는다.

017의 원 입력에는 Goal의 `coverage_requirement=NOT_COLLECTION`이 있고 049에는 신규
Output의 제목/수신자/시간이 Goal의 검색·시간 조건으로 들어 있다. 두 arm의 입력은 같으므로
후보의 회귀는 확인되지만 **responsibility 분리 자체가 유일한 원인이라고 확정하지 않는다**.
Goal의 최종 collection 여부는 특정 Source의 대상 범위와 같은 개념이 아니다. 새 Output의
계획값도 기존 Source의 조건이라는 의미는 아니다. 원문에는 그 역할 차이가 남아 있다.

이후 기존 기록을 확인하니 003에서 **Source의 Goal constraints만 비우는 동조건 비교**가
이미 Core011/014/015/021/024/028에서 실행됐고 당시 의미1/6→1/6, 필수 Source 손실과
과선정 증가로 기각됐다. 해당 구현은 `evaluate_request_source_decision_node.py`의
request-only 경로다. 당시 조건과 현재 V3가 같다는 주장은 하지 않지만 Goal 제거를 전혀
새 원인축으로 포장해 즉시 재실행하지 않는다. 필요하다는 증거 없이 새 shared artifact/ID/
State를 추가하거나 details Prompt에 Case 규칙을 붙이지 않는다. 다음은 현재 표현으로
올바른 의미를 전달할 수 없는 코드 결함인지, 표현은 가능하지만 첫 생성이 틀린 것인지
실제 consumer까지 확인하고 이미 실패한 접근과 구별되는 최소 방법을 선택한다.

## 비용·자원·미검증

| 구분 | calls | 입력/출력 tokens | 보고 latency / wall / load 합계 |
| --- | ---: | ---: | ---: |
| Core baseline 재사용 | 5 | 20,442 / 1,119 | 51,211 / 51,404 / 6,424ms |
| Core 후보 신규 | 10 | 28,157 / 2,280 | 98,269 / 98,683 / 5,774ms |
| 합성 baseline 신규 | 2 | 7,677 / 328 | 15,774 / 15,858 / 17ms |
| 합성 후보 신규 | 3 | 7,027 / 258 | 13,159 / 13,278 / 8ms |

신규 총15회, 입력42,861/출력2,866 token, 보고127,202ms/wall127,819ms. usage 누락0.
Core 후보의 membership5회는29,108ms, details5회는69,161ms. 첫 load5,711ms이며
재사용 baseline은 동시 paired 지연 비교가 아니다. 호출 증가와 실제 관측값은 보고하되
일반 지연 비율/p95/반복 안정성은 주장하지 않는다.

모델 동시성1, 실행 중 테스트/파일 변경0. 시작 RAM 여유19.90/31.71GiB,
VRAM0/8,188MiB·47°C. 중간 관측 VRAM6,385MiB·63%·71°C, 종료 RAM 여유15.38GiB,
VRAM6,385MiB·0%·53°C. snapshot이며 전체 peak나 다른 프로그램의 자원 변동 원인을
단정하지 않는다. 다른 사용자 프로그램을 종료하거나 서버를 재가동하지 않았다.

직접/인접 도구 회귀145 PASS, Ruff/mypy PASS는 실행 전 구조 준비 증거다. 제품 코드/
활성 Prompt/State/Node/승인·권한·실행 계약 변경0. 후보 role Prompt와 local Schema만 변경.
Graph/실제 업무 Provider/WRITE/SEND0, rerun-to-pass0, Holdout/Stress 튜닝0, 전체92 실행0.
실제 upstream RU→Tool Route와 Retrieval/Planning 이후, 다중 Work·confirmation/revision은
이번 결과로 검증하지 않았다. 전체 LangGraph 안정화 완료나 최종 업무 성공률이 아니다.

## 재현

- raw: `evaluation/results/064-source-membership-v43-t1/raw.json`, SHA256 `b5a6419ec305e213d01d377b6b91eb04310752af923a380de3037fdb442897ac`.
- plan: `evaluation/results/064-source-membership-v43-plan/preregistered-plan.json`, object SHA256 `374ede8500ed219ba82f2e4fd3762fcd532044ffa85c46c89921cb78250b90d7`, bytes SHA256 `6b5c8860e03ca4c9e4a5e19509a7dd20f629501cdef4a24348ad0f12283695ae`.
- Dataset SHA256 `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`, Fixture SHA256 `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
- 원 baseline은 v42 raw SHA `f5b40bd0d4e36e0f7d9138d00d9d0bdd45cbebc5cd954a110ced1d3a50c6ee52`의 실제 default 5개다. 신규/재사용을 원 row hash와 함께 구분한다.
- 상세 raw는 로컬 ignore 영역에 보존하며 추적된 이 문서는 원격 검토용 비민감 근거다.
