# 078 — 단일 Resource 출력에서 native reasoning 호환성

실행 전 고정. Product 변경/Provider 실행 없이 076의 exact wire에서 `think=false`만
`true`로 변경한다. 077 constraints 제거, 역할 수정, Schema 완화, 새 예시는 섞지 않는다.

## 가설과 재시도 근거

v12/v13은 전체 Source Schema에서 final 없음/timeout이었다. 072는 짧은 입력·자유 출력에서
final3/3와 일부 의미 개선을 보였다. 076은 전체 catalog/원 입력을 보존하며 단일 Resource
Schema로 membership8/8을 얻었지만049는 새 작업의 정보를 기존 Source로 잘못 요구했다.
이번 다른 조건은 **단일 Resource의 작은 structured output**이다. 긴 입력 부담은 그대로다.
가설은 이 조건에서 native reasoning이 final을 완료하고 target 의미를 보존할 수 있는가이며,
reasoning 일반 효과·모델 한계·N-call Production 채택을 미리 결론내리지 않는다.

## 고정 범위·중단

076 raw hash `f59b013d514e5fd5ef805a8c5a086341db1442afff5eef1cef05bcc1fb7131d5`와
현재 재구성 wire/model/입력/Schema를 대조한다. 순서는049 TASK,005 TASK,017 GMAIL_DRAFT,
합성 Draft UPDATE GMAIL_DRAFT 각1회, 최대4calls/180초씩/concurrency1/retry0/repair0이다.

각 호출의 final done/model 확인 후 실제 strict Source admission을 적용한다. empty/invalid/
timeout/error이면 그 실패와 usage를 보존하고 나머지는 NOT_DISPATCHED로 끝낸다.
**구조 유효한 의미 실패는 중단 사유가 아니다.** 의미가 틀려도 고정 control을 계속한다.
hidden reasoning은 읽거나 저장하지 않으며 존재 여부 bool과 모델 usage만 기록한다.
생성 중 코드변경·pytest·동시추론0, 하드웨어 snapshot만 허용한다.

## 평가

076과 동일한 요청 의미로 판정하고 모양/count를 정답으로 강제하지 않는다.
049는 기존 Atlas 작업의 근거이지 아직 만들지 않은 Task의 현재 상태가 아니어야 하며,
특정 기존 Task identity가 없는 collection lookup을 SINGULAR로 축소하면 안 된다.
005는 선택 identity의 status/due,017은 기존 Draft 근거 불필요,합성 UPDATE는 현재
Draft body/recipient snapshot을 요구한다. 모델 오류를 validator가 교정하지 않는다.

부분 Resource 진단의 PASS/PARTIAL/FAIL 및 strict completion, 원 출력→검증값,
신규 calls/tokens/latency와 같은 subset의 frozen076 비용을 분리한다. 미실행은 실패4건이나
PASS로 환산하지 않는다. 전체 Source 조합/RU/Graph/Provider 업무 성공은 미검증이다.
N Resource 호출의 비용 확대와 반복성까지 닫히지 않으면 Product 채택하지 않는다.
