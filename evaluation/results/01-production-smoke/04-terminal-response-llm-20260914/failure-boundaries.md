# 실패 경계

## 신규 terminal-response 경계

### TR-03 — 필수 수신/열람 한계 누락

- 입력: SEND Action `VERIFIED`, 수신자/제목 검증값, “수신자의 실제 수신 또는 열람 여부는 확인하지 않았다”는 typed limitation
- 실제 LLM 출력: 발송 완료만 설명하고 limitation을 2/2 Trial에서 누락
- 최초 divergence: Output Schema 통과 뒤 자유문 `answer`에서 필수 limitation이 사라짐
- 영향: SEND Provider effect 자체의 상태는 바뀌지 않았지만 사용자에게 검증 범위를 과도하게 보이게 함
- 수정 owner: `ComposeTerminalResponseHandler`의 사용자 문장 최종 projection
- 수정: LLM 및 fallback 결과 모두에서 입력 `limitations`의 누락 문장을 결정적으로 보존. 2,400자 상한을 넘으면 안전한 output 오류로 처리
- 검증: LLM 경로와 fallback 경로의 단위 회귀 PASS
- 남음: no-rerun-to-pass 원칙에 따라 최종 SHA 실제 Provider Trial은 재실행하지 않음

### TR-06 — 불필요한 일반 재시도 권고

- 실제 결과 설명은 일정 성공, Task 거절, Draft dependency block을 정확히 구분함
- 두 Trial 모두 “추가 정보를 제공하거나 조건이 충족되면 다시 시도”라는 입력에 없는 일반 조언을 덧붙임
- 업무 사실 왜곡·추가 실행 약속은 아니므로 의미 PASS, 표현 WARN으로 기록
- 이 경고를 없애기 위한 keyword validator나 추가 LLM review는 도입하지 않음

## 최종 6개 Smoke의 기존 upstream 실패

### 대상 없는 Calendar confirmation resume

- Run: `c87dd90c-4dde-49ce-a517-3d73bfa12695`
- 상태: `COMPLETED/SUCCESS`
- 확인된 근거: `2026-08-18 10:00~11:00 Asia/Seoul`
- 사용자 문장: 종료를 `오후 11시`로 표현
- 최초 관측 divergence: Planning ANSWER 자연어의 시간 표현
- 신규 terminal-response 경계 도달: 아니오 (`ANSWER_ONLY`)
- 판정: semantic FAIL. 이번 범위에서 Planning/Request Understanding을 수정하지 않음

### Quartz Draft

- Run: `c7da41b4-e41e-430e-8519-5bc9e37f6ec4`
- 상태: `BLOCKED/BLOCKED`
- reason code: `REQUEST_STATUS_PROVENANCE_MISMATCH`
- 최초 관측 실패: Request Understanding의 status provenance 검증
- Action/Approval/Attempt: 0/0/0
- 신규 terminal-response 경계 도달: 아니오
- 판정: 기존 upstream FAIL. terminal response 구현으로 숨기거나 완화하지 않음

## 안전 경계 확인

- LLM은 Action/Attempt/Verification의 durable projection만 소비한다.
- 계획 인자, 사용자 요청, confirmation label은 실제 실행값으로 승격하지 않는다.
- UNKNOWN_RESULT, 미검증 EXECUTED, 미해결 MISMATCH, FAILED 결정 대기를 terminal 성공으로 바꾸지 않는다.
- 최종 6 Smoke의 Approval과 Execution Attempt는 DB 직접 조회 기준 모두 0이다.
- 실제 Provider WRITE/SEND는 수행하지 않았다.
