# 065 — 관측 대상별 한-call Review v2: REJECT

실행 `966acc54`, Product의 별도 Work freshness 수정 `ff0591f5`. v1 baseline4 FIRST는
wire·model·Dataset·fixture 일치 검증 후 재사용했고, v2 후보4 FIRST만 새로 실행했다.
repair/retry0, 단일모델, 외부 Provider/승인/Graph0. 원 실패 Trial을 대체하지 않는다.

## 실제 출력과 판단

| 입력 | baseline/v1 | v2 | 결론 |
| --- | --- | --- | --- |
| CORE-005 실제 Review 입력 | 조회에 불필요 UPDATE/SEND 인식, RU owner 전달0 | Request 관측2개: outputs 경로는 타당하나 completion_conditions의 '조회된 정보만 반환'도 SEND 위험으로 잘못 지적. outputs 설명도 Plan 행위를 근거로 서술 | 구조적 RU projection2 생성은 확인했지만 올바른 field/관측만 전달하는 경계는 미달. PARTIAL |
| 합성 정상 CREATE | 정상, finding0 | 양 section 빈 배열 | 유지 PASS |
| Plan 제목만 잘못됨 | 정상 Intent 보존, Planning ISSUE | Planning ISSUE와 함께 정상 Intent goal/constraints에도 Request 관측 생성 | 기존 성공 회귀. 불필요 RU 재판정, FAIL |
| selected UPDATE, target 조회 근거 없음 | 양쪽 빈 findings, 근거 부족 누락 | EVIDENCE_GAP은 생성했지만 이미 있는 selected ID를 없다고 판단하고 Request 관측·ID/제목 요구 | 근거 부족 인식만으로 성공 아님. 선택 identity와 owner 귀속 왜곡, FAIL |

baseline/v1은 Core1 PARTIAL+합성2 PASS/1 FAIL, v2는 Core1 PARTIAL+합성1 PASS/2 FAIL.
이는 작은 owner 진단이며 Canonical 전체 또는 업무 성공률로 합치지 않는다.
wire/closed-context는4/4이나 **Plan 오류가 Request owner 쪽으로 전파된 회귀 때문에 REJECT**.
생성한 projection4개를 네 번의 정상 복구로 세지 않는다. 실제 Supervisor/RU revision은0.

## 비용·자원·근거

동일 qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
Ollama0.34.0, temperature 미전송(기본1)/presence1.5/seed20260923/ctx16384/thinkfalse/timeout180.
새4call input12,414/output911tokens, reported44,036ms/wall44,187ms, usage 누락0·timeout0.
첫 call load6,238ms. v1 baseline4는11,212/591tokens·34,004ms, v1 후보4는13,370/974·40,756ms.
동시 paired latency나 반복 안정성으로 주장하지 않는다.

GPU 관측6,383MiB/8,188MiB·69°C, 완료 후 여유 RAM17.48GiB. 연속peak가 아닌 snapshot이다.
모델 중 테스트·편집 병행0. 사전 직접33 PASS. Product Prompt/활성 계약 변경0.

- raw: `evaluation/results/065-review-owner-v2-t1/raw.json`
- raw hash: `61ddff5af159ce6d35e8fb4afac446f4cd6c11f8680bccd64c14ebfe0dabd7fb`
- plan object: `a83daff2463ce3b4005b72aa972f39a8f301e65757c5cedab45f7b3d70adf087`
- plan bytes: `c2fb0af7dcc23c9db9fa14487b30ad1a931a8606c00d989e93b3b10d79434e0f`

확인한 failure family: `PLANNING_ERROR_MISATTRIBUTED_TO_INTENT`, `VALID_FIELD_FALSE_POSITIVE`,
`SELECTED_IDENTITY_DROPPED`. Schema가 두 목록을 만들 수 있어도 각각의 책임을 지켰다는
뜻은 아니다. 자연어 설명을 코드로 재분류하거나 옳아 보이는 관측만 골라 남기지 않는다.
한-call 분할만으로 해결됐다고 결론내리지 않는다. 다음 grounded 축은 Request 검토 입력에서
Plan을 제외해 비교 기준 자체를 분리하는 최소 진단이다. 실제 채택 시 별도 호출/owner가
필요할 수 있으므로 호출·지연 증가 및 Production migration 검증을 피할 수 없다.
