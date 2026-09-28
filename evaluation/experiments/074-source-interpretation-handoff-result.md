# 074 — 자연어 해석 추가만으로 typed Source는 안정되지 않음

**REJECT / Production 미반영.** 같은 Source-only3건에서 historical
**1 PASS / 2 PARTIAL / 0 FAIL → 2 PASS / 0 PARTIAL / 1 FAIL**이다.
017은 개선됐지만049의 필수 근거가 모두 사라졌다. PASS 수 증가로 채택하지 않는다.
전체 RU/Tool Route/Canonical92/최종 업무 성공률과 합산하지 않는다.

## 실제 입력 → FIRST → validator → merge

| Core | baseline → 074 | 실제 의미와 최초 차이 |
| --- | --- | --- |
| 017 | PARTIAL → PASS | 현재 TASK와8/12Event의 정보·CRITERIA·Work binding 유지. 새 Draft를 기존 GMAIL_DRAFT Source로도 요구하던 오인은 제거. TaskList/Calendar parent 조회 가능성만으로 실패 처리하지 않음 |
| 049 | PARTIAL → FAIL | 원문과072 해석에 기존 Mail/Task/Calendar가 명시됐지만 **Source FIRST가10개 모두 NOT_REQUIRED**. 필수 근거가 전부 누락됨 |
| 005 | PASS → PASS | 선택한 동일 Task의 상태·기한, SINGULAR/work-1 유지. Source가 CREATE를 추가하거나 상태 filter로 바꾸지 않음 |

세건 모두 strict Schema/Source owner **VALIDATED**. raw JSON과 검증값이 같고
REQUIRED의 정보·scope·Work projection이 실제 merge에서도 그대로다.049의 최초 손실은
Source 첫 생성이며 validator/merge의 결정적 손실이 아니다. Work는 모두work-1이므로
다중Work 안정성을 증명하지 않는다. Output은 빈 값인 Source-only merge 검사였다.

072의017 자연어에 남았던 '진행 중' 표현은 현재 Source에서 INCOMPLETE 필터나
Task8/12 한정으로 변하지 않았다. 그 자연어 PARTIAL을 Source 점수에 자동 승계하지
않는다. 반대로 Source 성공이 후속 Query의 범위나 전체 답변 성공을 보증하지 않는다.
Source 필드 inventory 과복사와 container title/metadata는 관측으로 남기며 실제
Provider 과조회 횟수라고 주장하지 않는다. 독립 검수도 위 Source-only 판정과 일치했다.

## 고정 조건과 비용

- 실행 SHA `003fd8980f3d61ad853d707b369a3778216dac80`; 사전074 criteria.
- 역사 Source SHA `e9a09524f398b6e6f34b841fbdb239ed930fc32f`,072해석 SHA
  `b116c94b2d2f5016a411a8a52cc4333d89a29cde`. 서로 같은 제품SHA라고 하지 않는다.
  Source 실제 wire/Prompt/Schema/Registry/검증값을 현재 코드로 재구성해 동일성을 확인했고
  073 등 intervening 코드차이는 plan의 historical_file_differences에 결속했다.
- 원문·선택·시각·Goal·Work·catalog 보존.072 실제 final만 비권위 optional 입력으로 추가.
  숨겨진 추론·Gold·사람의 수정은 전달하지 않았다. 별도 evaluation PromptRef/hash 사용.
- qwen3.5:9b Q4_K_M digest
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, Ollama0.34.0.
  Source think=false,temp0.05,seed20260923,ctx16384,presence미전송/default1.5.
- 신규 FIRST3, 각1회, concurrent1, retry/repair/rerun0.3/3완료, 시작·종료 binding동일.

| 범위 | calls | input/output tokens | reported latency |
| --- | ---: | ---: | ---: |
| 역사 Source3 재사용 | 3 | 12,730 / 794 | 37,946ms |
| 신규 Source3 | 3 | 14,190 / 564 | 35,354ms |
| 072 해석3 비용(재사용) | 3 | 579 / 5,354 | 177,319ms |
| 해석+Source 비용 합계 | 6 | 14,769 / 5,918 | 212,673ms |

해석을 replay했다고 생성비용을 제외하지 않았다. 마지막 행은 별도 시점의 관측 합계이지
새 same-Run connected 실행 latency가 아니다. 전체 비용은 baseline보다 약5.60배이고
단발/cache/cold-load 차이가 있어 일반 성능비율로 확장하지 않는다. 신규wall35,438ms,
load7,357ms,usage누락0. 해석 output usage는 숨겨진 추론을 포함한 모델 보고량이다.

시작 여유RAM19.56GiB,GPU0/8188MiB·42°C; 중간6383MiB·67%·58°C,
종료6385MiB·0%·50°C(snapshot). 모델 중 편집/테스트/다른 생성0.
직접/recorder44 tests PASS, scoped Ruff/mypy PASS. 전체pytest미실행.

## 판단과 다음 축

올바른 자유 해석을 덧붙이는 것만으로 현재 Source의 재판단이 안정되지 않았다.
추가 설명/예제/요약을 더 누적하거나049를 성공할 때까지 반복하지 않는다.
현재 계약은049의 올바른 답을 표현할 수 있고 검증·전달도 그대로 보존한다. 그러므로
validator를 완화하거나 Source0을 deterministic하게 정답으로 교체하지 않는다.
생성 부담과 개별 필요성 판단을 분리할 가치가 있는지 기존 membership/family 결과와
대조하고, 새로운 비교 축이 있는 경우에만 작은 반례 포함 진단을 진행한다.
LoRA나9B의 한계로 확정할 근거도 아직 아니다.

Product source/활성 Prompt/State/Node 변경0, Provider READ/WRITE/SEND0,
승인0, Graph0, Holdout/Stress 튜닝0, 신규92실행0. 앞선073 Task scope 수정은 유지한다.
전체 LangGraph 안정화는 미완료이며 Query/Retrieval/Planning 연결과 반복 안정성은
이 실험으로 검증하지 않았다.

## 원 근거

- plan `evaluation/results/074-source-interpretation-handoff-plan/preregistered-plan.json`,
  object hash `4293b7bcfd2f58f45a354d2a5db631f79f1a0956452b2fbcd06d014465505b16`.
- raw `evaluation/results/074-source-interpretation-handoff-t1/raw.json`, bytes hash
  `94c3fadd968a8dd152ac0d9e605af1b8ccd47f44cab62365d39679b322ee61d7`.
- `source-admission.json`에 원 raw hash, strict validated 값, source-only merge와 비용.
- Dataset `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`;
  Fixture `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
- 상세 raw는 ignore된 로컬 결과이며 이 문서만 원격 검토용 비민감 요약이다.
