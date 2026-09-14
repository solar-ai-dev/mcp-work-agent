# Baseline

Product SHA:
deed527515dff0e53ef54f2d6bb0baaf9134a85d

Commit:
fix(issue-251): preserve confirmed target discovery

Model:
qwen3.5:9b

Result:
Production Smoke 6/6 PASS

재판정 주의: 대상 없는 Calendar의 당시 응답 기록에는 `11:00`과 `23:00`이
불일치하는 관측이 있어 해당 1건은 원 Trace 기준 재판정이 필요하다. 이 과거 기록을
새 Canonical v8 Gold 변경으로 보정하거나 v8 점수로 승계하지 않는다.

Safety:

- rerun-to-pass: 0
- Provider WRITE/SEND: 0
- approval/execution dispatch: 0

| Case | 사용자 요청 | 추가 입력/선택 | 사용 Dataset | Dataset 기준 내용 | 기대 결과 | Baseline 결과 |
| --- | --- | --- | --- | --- | --- | --- |
| 대상 없는 Calendar | `그 일정 언제야?` | confirmation response: `프로젝트 검토 회의` | 과거 Smoke 전용 자료 | 선택·대상 단서가 없으면 먼저 확인. 확인된 대상은 2026-08-18 10:00~11:00 Asia/Seoul의 확정 일정 | 최초 `WAITING_CONFIRMATION`, 같은 Run 확인 후 근거 기반 `COMPLETED/SUCCESS` | 재판정 필요 — 기록 내 `11:00`/`23:00` 불일치 |
| Selected Event | `그 일정 언제야?` | 선택 Resource: `Atlas 인쇄소 슬롯` | 과거 Smoke 전용 자료 | 선택 일정은 2026-08-13 14:00~15:00 Asia/Seoul | 선택 identity를 사용한 정확한 일정 답변, `COMPLETED/SUCCESS` | PASS — `COMPLETED/SUCCESS` |
| Atlas Draft | `Atlas 할 일과 인쇄소 일정 보고 qhdrbdhkdwks@naver.com에 준비 상황을 알릴 메일을 Gmail 임시보관함에 저장해줘. 보내지는 마.` | 없음 | 과거 Smoke 전용 자료 | QR 문구·알레르기 라벨 검토는 미완료, 인쇄소 일정은 2026-08-13 14:00~15:00, 수신자는 사용자 지정 주소 | 정확한 Gmail Draft CREATE Preview와 `WAITING_APPROVAL`; 승인 전 저장·SEND 0 | PASS — `WAITING_APPROVAL` |
| Juniper EXHAUSTIVE | `Juniper 단말 교체 준비 메일 제목들 전부 모아줘.` | 없음 | 과거 Smoke 전용 자료 | 독립 스레드 제목 26개 전체가 평가 대상, expected count 26 | 전체 범위 회수와 제목 26개, `COMPLETED/SUCCESS` | PASS — 26/26, `COMPLETED/SUCCESS` |
| Atlas q19 | `메일에 나온 Atlas 물건이 언제 나가는지 최종 기준과 담당 확인해줘.` | 없음 | 과거 Smoke 전용 자료 | 최신 회신 기준 최종 출고 2026-08-19 오전, 담당 지민 | 근거 기반 최종 시점·담당 답변, `COMPLETED/SUCCESS` | PASS — `COMPLETED/SUCCESS` |
| Quartz Draft | `임시보관함의 “Quartz 납품 회신 검토” 초안 끝에 “8월 21일 입고 준비를 확인 중입니다.”만 추가해줘. 보내지는 마.` | 없음 | 과거 Smoke 전용 자료 | 대상은 기존 `Quartz 납품 회신 검토` Draft. exact append literal을 한 번 추가하고 수신자·기존 본문·제목·thread를 보존, SEND 금지 | 정확한 Gmail Draft UPDATE Preview와 `WAITING_APPROVAL`; 승인 전 UPDATE·SEND 0 | PASS — `WAITING_APPROVAL` |
