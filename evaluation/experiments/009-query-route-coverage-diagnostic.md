# 009. Query 첫 추론의 Route 포함 여부 진단

기준 SHA `0622d8e1`, corpus `canonical92-v8-5a49aa00-ecf32ffc82`.
기존 Node evaluator의 `SEMANTIC_VALID`는 validator를 통과한 Query라는 뜻에
가깝고, required business source가 누락됐는지 별도 표시하지 않았다.
현재 연결의 015는 Task가 frozen Route에 있음에도 조회되지 않았고,
021/028은 정책 pre-read 누락이 결정적 합성으로 회복됐다. 저장 input과
현재 producer input은 서로 다른 모집단이므로 혼합하지 않는다.

제품 코드를 바꾸지 않고 저장 Node 입력 `014/015/021/028/036/058`만
직렬 replay한다. 첫 **성공적으로 반환된 structured inference**의 Route ID를
frozen Route에만 결합해 resource type을 기록한다. Schema repair 이전의 raw
provider output은 볼 수 없으므로 이를 `first provider dispatch`와 동일시하지
않는다. `POLICY_*` 기존 두 pre-read, access-only dependency, 나머지
required business Route를 구분하되 business 누락을 자동 오답으로 확정하지
않는다. 그 판단은 원 요청·upstream 선택·실제 Evidence와 비교한다.

이 단계의 결과는 Node 출력 분포와 평가기 과대계수 여부 진단이다.
Connector·WRITE·Work Analysis는 실행하지 않는다. 결과를 보고 같은
Route 결함이 넓게 나타나는지 판단한 뒤 Query 출력 책임 분해 또는 앞단
Source 판정으로 조사 범위를 정한다. 단일 문구별 강제 규칙은 추가하지 않는다.

## 저장 Node 입력 6건 결과

동일 9B 모델·temperature 0·seed 1729로 한 프로세스에서 직렬 실행했다.
원래 evaluator 집계는 `SEMANTIC_VALID` 4/6, 실패 2/6이었다. 새 Route
관측에서는 그 4건 중 021 첫 추론에 `CALENDAR_EVENT`, 028 첫 추론에
`CALENDAR` 정책 Route가 빠졌다. 최종 Query에만 007의 결정적 정책 합성이
포함했다. 따라서 **첫 추론의 정책 포함까지 요구하면 2/6**이고,
021/028은 `POLICY_COMPOSITION_RECOVERED`로 따로 세야 한다. 이 판정은
저장 Route의 정책 계약에 한정되며 business 의미 전체의 성공률이 아니다.

014는 Task·Calendar 필수 business Route를 첫 추론에 포함했다. 저장 015는
Task가 frozen Route에 아예 없어 Query의 Task 누락으로 분류할 수 없다.
반면 007의 **현재 RU/Route** 연결 015에는 Task가 있고 Query가 이를
시도하지 않았다. 이는 upstream 입력의 변화와 Node 판단을 분리해야 한다는
대조 결과다. 036은 schema repair가 실패 범위 밖을 바꿔 첫 structured
inference가 없었고(2 dispatch), 058은 FREEBUSY temporal range가 빠져
semantic revision 뒤에도 실패했다(2 dispatch). 두 경우를 정책 Route
누락과 합치지 않는다.

이 6건의 Provider dispatch는 8회, 반환된 inference의 input/output token은
50,302/4,311, Provider latency 합계는 139.1초였다. Connector 0회,
WRITE 0회다. 원시 Trial은
`evaluation/results/query-route-coverage-core6-20260916/result.json`에 남긴다.
이번 Trial 후 evaluator가 모델 첫 추론의 정책 누락과 결정적 보충을 별도
classification/outcome으로 세도록 고쳤다. 이는 기존 저장 결과를 몰래
재작성한 것이 아니다. raw 4/6과 근거 기반 재판정 2/6을 함께 보존하며,
정책 포함 외의 business semantic-valid 판정은 아직 미완료다.
