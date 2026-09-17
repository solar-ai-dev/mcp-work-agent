# 035. Goal inspector의 세 판단을 한 호출의 분리된 출력 책임으로 비교

기준 SHA `e3e840c6`, clean tree. 031의 exact 이전값 결속과 032의
원문/외부 Evidence 입력 분리 모두 정상 또는 다른 허용 수정에서 회귀했다.
015/016에서 두 LLM 호출로 Goal과 Evidence를 분리한 방법도 명시적
사용자 수정·확인에서 실패했다. 같은 Prompt 설명이나 입력 field를 더하지
않는다. 이번 가설은 하나의 자유로운 findings 배열이 사용자 요구 불일치,
외부 근거 부족, 사용자 선택 필요를 혼합한다는 **출력 책임**이다.

개발 후보 B는 현 Goal 입력을 바꾸지 않는다. 한 번의 structured 출력에서
`request_alignment`, `external_evidence`, `user_choice`의 세 배열에
finding을 나눈다. 기존 finding DTO와 다섯 종류는 보존하며 각 배열에
허용되는 kind만 구조로 제한한다. 현재 결함만 출력하고 정상일 때 모두
빈 배열이다. 소비 경계에서 원래 findings 형태로 합치되 정답 disposition을
강제하거나 CONFIRMATION을 EVIDENCE_GAP으로 바꾸지 않는다. Prompt
source의 역할/검사 설명은 유지하고 출력 형식 부분만 후보 Schema에 맞춰
교체한다. Prompt+Schema는 의미를 함께 정의하는 불가분 변경이며 효과를
한 변수로 귀속시키지 않는다. 제품 manifest/계약은 이 비교에서 수정하지 않는다.

고정 입력: 031의 8개 + 028 저장된 날짜 오류와 참석자 금지(두 경우
기존 Goal 첫 출력은 정확한 ISSUE)를 합한 **10개**. A는 동일 input
fingerprint/model인 031/028 저장 원출력을 비교 기준으로 재사용한다.
B만 각 1회, qwen3.5:9b 동일 digest/temp0/seed1729, serial 최대
10 provider calls. input/Prompt/Schema fingerprint·원출력·flattened
finding·repair/timeout·token/latency 및 실패를 ignored 결과에 남긴다.
정상 023/028 0 유지, 날짜·금지 및 수정 불일치 ISSUE 유지,
수정 일치의 허위 ISSUE·CONFIRM 감소, 외부 메일 부족의 EVIDENCE_GAP
유지와 불필요 CREATE 확인 감소가 함께 필요하다. 한 번의 좋은 사례나
finding 개수 감소만으로 채택하지 않는다. 유력하면 별도 반복 및
compiled 순환·Live 예산을 정한다. Provider READ/WRITE·전체 92는 0.

개발 bundle의 output schema version을 2로 등록하려던 **모델 전 preflight**는
고정 slot version whitelist에 거절됐다(Provider dispatch 0). 026과
같은 개발 범위로 manifest의 현 slot identity/version은 유지하고 후보
schema만 `runtime.infer`에 명시적으로 전달한다. 제품 registry/계약은
수정하지 않으며 이 결과가 좋을 때만 Owner 계약 버전 변경을 별도 검토한다.

## 결과 — 기각

10/10 호출은 첫 structured 결과를 반환했고 후보의 세 배열은 **모두
빈 값**이었다. 정상 023/028 두 건만 올바른 무결함이다. 저장된 날짜·금지
위반의 ISSUE, Preview 수정 불일치 두 건의 ISSUE, 외부 메일 부족의
EVIDENCE_GAP까지 전부 놓쳤다. 수정 일치의 허위 finding도 사라졌지만
검사 책임 자체를 사실상 수행하지 않는 결과라 제품에 채택하지 않는다.
Schema validator 통과와 의미 성공은 여기서 명확히 다르다. 빈 결과를
억지로 거부하는 규칙이나 정답 finding을 강제하지 않는다.

B input/output 합 110,983/290 tokens, node 경과 합 57,111ms;
출력이 29 tokens로 일정한 것은 빠른 판단의 증거가 아니라 책임 축소
실패다. 동일 입력 A와 후보 Prompt/Schema가 다른 비교이며 비용 이득으로
주장하지 않는다. ignored 원출력·fingerprint는
`evaluation/results/review-goal-responsibility-20260917/node-comparison.json`.
Provider READ/WRITE 0, compiled/Live 0. 026의 RECHECK 상태·현재 finding
분리 성공을 초기 Goal의 세 분류로 단순 일반화할 수 없었다. 다음 선택은
입력 field·출력 array의 추가 반복이 아니라 Retrieval 충분성의 실제
거짓 양성, Review의 거대한 첫 호출 책임, 그리고 현 모델 판단 한계를
복수 실제 요청에서 분리 진단하는 것이다.
