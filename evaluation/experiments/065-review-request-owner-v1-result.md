# 065 — 원문 기반 Review 재판정 후보 v1: REJECT

## 실행과 결론

Production 기준 `1c37ad3a`, 실행 코드 `7154f759`. 4개 frozen 입력에서 baseline/후보
각 FIRST1회, 총8회. repair/retry0, concurrency1, Provider0, Graph0, Approval0.
새 typed finding을 추가하고 원문·현재 Intent·Plan을 결속했으나, 실제 모순을 알아본 모델이
최초 잘못된 authority를 선택하지 못했다. **이 후보는 Production에 채택하지 않는다.**
기존 Route 진단 전달 및 Source owner 보존 수정은 유지한다.

| 입력 | baseline 첫 출력 | 후보 첫 출력 | 의미와 최초 실패 |
| --- | --- | --- | --- |
| CORE-005 실제 T2 Review input | ROUTE_ISSUE 1개 | ISSUE 3개 | 둘 다 조회 요청의 불필요 UPDATE/SEND를 인식. 그러나 잘못된 Output responsibility를 가진 Intent가 아니라 Tool Route/Planning을 수정 대상으로 선택. Request owner 전달 0/1→0/1 |
| 합성 정상 Task CREATE | findings=[] | findings=[] | 사용자 제공 제목의 정상 생성 제안 유지 |
| 같은 Intent, Plan 제목만 다름 | ISSUE | ISSUE | 제목 불일치를 Planning 문제로 구별; 불필요 RU 재판정 없음 |
| 합성 selected Task UPDATE, target snapshot 없음 | findings=[] | findings=[] | 실제 target 근거가 없는 기존 Resource 수정의 근거 부족을 지적하지 않음; 별도 안전 검증과 실제 Graph는 실행하지 않음 |

구조 검사는 양쪽 4/4 통과했지만 그것이 의미 성공이 아니다. 실제 Core는 양쪽 모두
모순 인식은 했고 **올바른 revision owner 전달은 실패**했다. 합성 control은 별도이며
Canonical 점수로 합치지 않는다. 전체 Canonical92 및 최종 업무 성공률은 이번에 측정하지 않았다.
독립 검수의 local 의미 판정은 양쪽 모두 Core1 PARTIAL, 합성2 PASS/1 FAIL이다.
합성 UPDATE의 근거는 현재 Review Prompt의 target Evidence 요구와 Canonical05 §Selected
resource의 최신 상세 GET 계약이다. selected ID가 존재해도 조회 근거를 대신하지 않으며,
반대로 생략된 모든 필드나 전체 raw snapshot을 요구하는 의미로 확대하지 않는다.

후보의 추가 설명은 기존 READ Evidence가 있는데도 "읽기 전에 UPDATE/SEND"라는 서술을
반복했다. 실행 전 Plan 검토를 실제 Provider 실행의 증거로 해석하지 않는다. finding 중복을
새로운 독립 결함 3건으로 세지 않는다. 자유 code/description에서 RU routing을 추론하는
후처리는 수행하지 않았다. 새 REQUEST_SEMANTICS_ISSUE, product ref projection 모두0이다.

## 비용·자원

실제 모델 `qwen3.5:9b`, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, Ollama0.34.0.
temperature 미전송(실제 모델 기본1), presence1.5, top_k20, top_p0.95,
seed20260923, num_ctx16384, think=false, timeout180초. 양쪽 동일 설정이다.

| 범위 | baseline calls / input·output tokens / reported ms | 후보 |
| --- | --- | --- |
| 실제 Core1 | 1 / 4,591·352 / 21,721 | 1 / 5,150·812 / 29,726 |
| 합성 control3 | 3 / 6,621·239 / 12,283 | 3 / 8,220·162 / 11,030 |
| 합계(업무점수 아님) | 4 / 11,212·591 / 34,004 | 4 / 13,370·974 / 40,756 |

총8회 모두 응답, timeout0, usage 누락0. wall 합계 baseline34,106ms/후보40,921ms.
첫 baseline에는 model load7,298ms가 포함된다. one-trial 고정 순서이며 latency의 인과적
향상·퇴보나 반복 안정성으로 일반화하지 않는다. GPU 관측 snapshot 최대6,385MiB/8,188MiB,
68°C, 여유 RAM 약19.8→17.43GiB. 연속 peak telemetry는 아니며 모델 중 테스트 병행0.

## 근거·다음 축

local raw는 `evaluation/results/065-review-owner-v1-t1/` 아래만 보존하며 Git ignore 유지.
원 raw를 재채점 값으로 덮지 않는다. 이 문서는 의미 검수 결과다.

- plan object SHA256: `7496c89aca88868e298733a7584c4eab67d38cb3b90959317f77774fc98c24b8`
- plan bytes: `75f54f73d54b2c8b33fd9a0f8f47664a2dc733c34045d5f50b9973b9c1e4c4dd`
- raw bytes: `22b7fbcb1257f3aede60f2f82d6c561e4c3d80c1e5fdc5fdc764ebab9ae113af`
- Dataset: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- fixture: `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`

실패군: `OWNER_MISATTRIBUTION`(모순 인식과 수정 authority 선택은 다름),
`TARGET_EVIDENCE_GAP_MISSED`. 같은 kind를 강조하는 Prompt suffix나 retry는 반복하지 않는다.
다음은 실제 item/Work binding의 revision 후 재사용 불변식을 먼저 조사한다. Review 후속
표현 실험은 명시적 관측 대상 artifact와 revision owner를 표현하는 방식에 새 근거가 있을
때만 별도 사전 고정한다. Production signal/status/checkpoint migration은 아직 미구현이다.

테스트113 PASS와 LLM8회는 서로 다른 근거이며 합산하지 않는다. Product Prompt/Schema/
Node/Edge/안전 경계 변경0, 모델 결과로 Canonical Gold 변경0. 상세 raw는 원격에 없으므로
독립 리뷰에 필요하면 위 hash-bound local artifact의 안전 projection을 전달해야 한다.
