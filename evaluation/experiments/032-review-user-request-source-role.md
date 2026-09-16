# 032. Review Goal에서 사용자 원문과 외부 Evidence의 역할 분리

기준 SHA `0407b006`, clean tree. 031의 이전값 provenance 검증 + 옛
constraint 비활성화도 수정 일치/불일치와 근거 부족을 동시에 안정화하지
못했다. Goal inspector는 현재 `USER_MESSAGE`를 외부 Resource와 같은
`evidence[]`에 넣는다. 원문을 숨기는 대신 사용자 요청의 출처·권위를
명시적으로 분리하면 현재 수정과 외부 근거 부족의 혼동이 줄어드는지 본다.

사전 고정 입력은 031의 8개(정상 023/028, 저장 023 제목 수정,
합성 028 제목·설명 수정 일치, 023 제목·028 설명 불일치, 메일 근거 부족
합성)이고 모델/qwen3.5:9b digest, temp0/seed1729, Goal Prompt source와
output schema는 같다. A는 031의 **동일 입력** 결과 8개를 보존해
재사용한다. B는 원래 `USER_MESSAGE` Evidence 객체를 `evidence[]`에서
빼고 동일한 원문/ID를 `original_user_request`의 별도 typed input으로
이동한다. 다른 Resource Evidence, Intent, Work Analysis, Plan,
modifications는 바꾸지 않는다. 유일한 USER_MESSAGE와 current Run의
message_id가 비어 있거나 복수라면 B를 적용하지 않는다. 제품 적용 시에는
WorkflowStartRequest의 current Run message_id까지 검증한다. 개발 input contract에
optional root를 선언한 dev manifest를 사용하고 정답은 넣지 않는다.

최대 B 8회, 실제 Provider READ/WRITE 0, 전체 92 0. A와 B는 실행
시간이 다르므로 속도 우위를 단발로 주장하지 않는다. 입력 fingerprint,
원 structured output, Schema/repair 결과, 토큰·지연, 실패를 별도 ignored
결과에 모두 남긴다. 판정: 정상 허위 finding 증가 없음, 두 수정 일치의
허위 title/description 판단 감소, 불일치 ISSUE 유지, 메일 부족에서
EVIDENCE_GAP은 지키고 “생성할까요” 불필요 CONFIRM은 감소. 한 축만
좋아져도 전체 채택으로 포장하지 않는다. 유력하면 직렬 반복과 compiled
경로를 별도 예산으로 확인하고 그때 제품 입력·Prompt/Canonical을 갱신한다.

## 결과 — 제품 미채택

B 8/8 structured output 반환. 저장된 동일 A 입력(031)과 비교해 023 제목
수정 허위 ISSUE는 3→2, 합성 028 제목 수정은 1→1로 남았다. 028 설명
수정은 기존 잘못된 CONFIRMATION이 사라졌으나 ISSUE 두 건이 남았고,
두 불일치 입력에는 실제 위반 ISSUE와 추가된 과잉 ISSUE/EVIDENCE_GAP이
섞였다. 정상 028은 0→0이었지만 **정상 023은 0→ISSUE+EVIDENCE_GAP**으로
회귀했다. 메일 부족은 EVIDENCE_GAP을 유지하면서 불필요 생성 재확인
CONFIRMATION도 그대로이고 gap 한 건이 더 생겼다. 의미 개선으로 채택할
수 없다. 원문을 외부 Evidence에서 별도 객체로 옮긴 것만으로 Goal의
권위·충분성 분류가 해결되지 않는다.

B input/output 합계 84,818/4,148 tokens, node 경과 합 122,962ms.
A의 84,738/2,691 tokens, 77,384ms는 이전 시간대의 저장 Trial이므로
지연 우위 주장이 아니다. 원 structured output과 모든 fingerprint는
`evaluation/results/review-user-source-role-20260917/node-comparison.json`
(ignored)에 보존했다. 수정 실패가 동일 방법에서 반복되었으므로 같은
Projection/Prompt 정보 추가를 반복하지 않고 책임·상위 조회 경계를
우선 재검토한다. 실제 Provider 연결/compiled 순환/92는 이 후보에서 0.
