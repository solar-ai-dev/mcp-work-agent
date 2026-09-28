# 065 — Request-only Review v3: REJECT

실행 HEAD `bb392968`. v2에서 Plan 오류가 정상 Intent 결함으로 전파된 반례에 따라,
Request 검토 입력에서 Plan/Evidence를 제외했다. v2 Request finding 하위 schema와 기존
receipt는 재사용했다. Product Prompt/Node/활성 계약/외부 Provider 변경0이다.

## 실제 결과

| 고유 입력 | v3 첫 출력 | Request 의미 판정 |
| --- | --- | --- |
| CORE-005 frozen 실제 Intent | 빈 request_intent_findings | **FAIL**. 상태·기한 조회 원문과 모순되는 TASK/UPDATE·GMAIL_MESSAGE/SEND Output을 놓침 |
| 합성 정상 Task CREATE | 빈 목록 | PASS. 잘못된 Plan 제목 control도 동일 wire alias이며 별도 trial/성공으로 세지 않음 |
| 합성 selected Task UPDATE | 빈 목록 | PASS. 이번에는 이미 결속된 selected identity를 없다고 하지 않음. 외부 target Evidence 충분성은 NOT_EVALUATED |

Request-only 비교 범위에서 Core1 FAIL + 합성2 PASS이다. 구조/closed-context3/3, transport
오류0이지만 실제 결함 recall0/1이므로 **REJECT**. v2의 오탐이 없어진 것만으로 개선 채택하지
않는다. v2는 모순을 인식했으나 틀린 필드도 지적한 PARTIAL이었고, v3는 모순 자체를 누락했다.
이는 한 번의 고정 진단이며 오류 빈도·모델의 일반적 한계·3회 반복 안정성을 뜻하지 않는다.

Plan 제목 오류와 Evidence 누락은 v3 입력·책임에서 제외됐으므로 v1/v2 전체 Review 점수와
직접 비교하지 않는다. 실제 Supervisor→RU 재판정·revision·Graph 복구 성공0회/미검증이다.
별도 Request owner를 제품에 추가하면 원칙적으로 LLM 호출+1이지만 이 비용을 정당화할
의미 이득이 확인되지 않았다. Product baseline을 유지하고 v3를 활성화하지 않는다.

## 비용과 자원

새 FIRST3, 입력5,320/출력105tokens, reported14,203ms/wall14,262ms. 첫 call load7,101ms.
모두 빈 관측이므로 짧아진 출력/지연을 품질 최적화로 해석하지 않는다. 정확히 같은 baseline
wire4개는 v1 raw에서 재사용했고 새 baseline generation0, repair/retry/rerun-to-pass0이다.

qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
Ollama0.34.0, seed20260923/ctx16384/thinkfalse, temperature 미전송(모델 기본1), timeout180.
GPU 관측6,385/8,188MiB·49°C, 여유 RAM17.80GiB. 모델 전 GPU0MiB·RAM19.70GiB.
연속 peak/thermal 안정성 검사가 아닌 snapshot이다. generation1개씩, 모델 중 편집/pytest0.

직접84 PASS/6.47초. 초기 테스트 fixture가 실제 Core와 달리 CREATE와 같아서 고유입력 수
검사1건이 실패했고, mock historical 입력만 구별되게 고쳤다. 실제 Case/원 raw는 변경0.
mypy의 package-base 설정 및 Mapping 타입 표시를 수정한 뒤 관련2파일 PASS, Ruff PASS.

## 재현 근거와 다음 선택

- raw: `evaluation/results/065-review-owner-v3-t1/raw.json`
- raw SHA256: `4ee58df383b53c507a882ca9c914a827a0ab39f484273a12365b53fddc64db31`
- plan object: `6056d5bb8f2275604f8d93612a1e67f558c481c5d525a6dc28a20a9ee2f2cc87`
- plan bytes: `2d3292b0c14751654585cc9c0a2728e05b1715419c1f1ca6098f007d2fd3badc`
- Dataset/fixture/model/runtime/Prompt/schema/wire/전체 Product source hash는 sealed plan에 결속.

세 Review 후보는 각각 typed owner 미전달(v1), 책임 오귀속(v2), 결함 누락(v3)이 남았다.
같은 role 문구를 추가하거나 반복 호출해 성공을 고르지 않는다. 분리 자체가 잘못됐다는
일반 결론도 내리지 않는다. 다음 모델 후보에는 새로운 입력/표현/책임 근거가 필요하다.
현재는 모델 호출을 확대하지 않고 revision/projection/consumer의 결정적 손실을 조사한다.

전체92/업무 성공률 갱신0, Holdout/Stress튜닝0, Live/승인/Provider WRITE/SEND0.
상세 raw는 기존 ignore 정책의 로컬 결과이고 이 비민감 결론은 버전관리로 공유한다.
