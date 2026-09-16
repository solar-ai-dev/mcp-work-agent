# 030. RECHECK 출력 정합성 — 계약 경계

기준 SHA `4e66353c77e89b3167ec1d7c2cc5d765037192a1`, clean tree.
직전 제품 변경 `d59b69d1`의 `issue_assessments`는 상태를 검증했지만
`UNRESOLVED`/`UNCERTAIN` + `findings=[]`를 그대로 집계해 PASS가 될 수 있었다.
이는 원출력의 명백한 모순이며 자연어 이유에서 결함을 추론할 근거는 아니다.

사전 범위: 모델/Provider 호출 0. 동일 v2 RECHECK 출력에 대해 두 열린 상태와
빈 finding을 실패로, 관계 없는 RECHECK(`issue_assessments=[]`), 해결된 이전
issue + 새로운 finding, 다중 이전 issue와 하나의 현재 finding을 정상으로
검증한다. 출력 Schema에서 모순을 `$.findings` 오류로 반환해 기존 1회
bounded schema repair에 맡기고, Application 소비 경계에서도 같은 모순을
거절한다. 자동 finding 복사·상태→disposition 변환은 하지 않는다.

실행: 변경 전 단위 테스트 2건이 예상대로 실패(기존 Schema의 오류 목록 `[]`).
변경 후 69개 직접 영향 unit/architecture 테스트 PASS, `ruff`/diff check는
커밋 전 확인했다. 후속 compiled Review 직접 테스트에서 열린 assessment
두 유형 모두 aggregate/PASS 이전에 ValueError로 중단하는 것과,
Confirmation/no-transition·dimension-only·다중 Action 입력에서 새
finding을 정상 보존하는 것을 확인했다. 실제 모델이 모순을 얼마나 내는지, repair 비용·Live 성공률은
이 계약 테스트로 증명하지 않는다. Prompt source/input manifest는 바꾸지
않았고 기존 출력 v2의 유효 결과 집합만 좁혔다. Canonical 06/08에 같은
불변식을 기재했다.

잔여 Preview 수정·외부 근거 부족 분류는 별도 비교에서 원인과 효과를
확인하기 전 제품에 추가하지 않는다. 전체 92, 실제 Provider WRITE 0.
