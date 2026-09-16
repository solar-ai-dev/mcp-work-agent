# 026. RECHECK 해결 판정과 새 finding 분리 후보

기준 `53842ae6`, 입력은 025의 전후 제안 관계 후보와 동일하다.
025는 미수정 날짜를 검출했지만 수정 후에도 새 확인·근거 부족을
만들었다. 이번 가설은 데이터 추가가 아니라 단일 `findings` 배열에
“과거 문제의 해결 상태”와 “현재 새 결함”을 함께 맡긴 출력 책임이다.

개발 후보는 이전 issue마다 index와 `RESOLVED`/`UNRESOLVED`/
`UNCERTAIN` 상태 및 짧은 현재 근거를 별도로 출력하고, 현재 제안에
실재하는 결함만 기존 형식의 `findings`에 쓴다. 이전 finding은
사용자 요구가 아니며, `RESOLVED` 자체를 PASS로 강제하지 않는다.
수정 전후 relation은 025와 동일하게 route가 단일 매칭일 때만 준다.
Prompt source/output schema를 dev copy에서 함께 바꾸는 불가분 후보:
기존 출력에 상태 필드만 더하면 무엇을 의미하는지 모델이 알 수 없기
때문이다. 실제 제품 계약은 채택 판정 후에만 수정한다.

사전 비교는 025의 수정 날짜·수정 금지·미수정 날짜·미수정 금지 4개,
후보 각 1회 최대 4 LLM 호출이다. 025 A/B 결과는 같은 모델·저장
입력의 참고 기준으로 보존하고, 새 후보의 input/output schema·Prompt
hash가 다르므로 순수 입력 변수 효과라고 부르지 않는다. temp0,
seed1729, 동일 digest, Provider I/O 0. 두 수정안은 prior issue를
해결로 인정하면서 허위 새 finding이 없어야 하고, 두 미수정안은
실제 위반을 놓치거나 단순 확인 질문으로 돌리면 실패다. 모든 Trial을
보존하고 실패를 대체하지 않는다. 단발 성공만으로 제품 채택하지 않고
기존 compiled 수정 순환과 정상/Preview/근거 부족 반례를 거쳐야 한다.

결과와 채택 판단은 Trial 후 기록한다.

4회 모두 first structured inference/schema 완료, repair/timeout 0.
수정 날짜/금지에서는 과거 issue 3개씩 RESOLVED, 새 finding 0.
미수정 날짜/금지에서는 과거 issue 3개씩 UNRESOLVED, 실제 위반
ISSUE 1개씩. 이전 025와 달리 무관한 확인·실행 결과 요구가 사라졌다.
이 결과는 유력하지만, 025의 changed_arguments가 JSON path 삭제를
`null` 값과 구별하지 않은 결함이 있다. 참석자 삭제를 모델이
“null로 변경”이라 설명했다. Canonical은 absent와 null을 구별하므로
이 Projection을 그대로 제품에 채택하지 않는다. 027에서 존재 여부를
명시한 동일 후보를 비교한 뒤 compiled 순환으로 넘어간다. 첫 loader
시도는 개발 contract의 고정 output version 제한으로 모델 dispatch 전
실패했고, 결과 Trial에는 포함하지 않았다. 후보 호출은 별도 supplied
output schema로만 평가해 제품 manifest/contract를 바꾸지 않았다.
ignored 결과는 `evaluation/results/review-resolution-output-20260917/`.
