# 067 — UUID/시각 교차: Goal 목적 유지, constraint 오염 지속

실행 HEAD `b9bd1871`, plan object SHA256
`6c8c19eabf44f814bfdf476b785787c4643a940043099905110b5359ca115d45`.
사전 고정한 교차 FIRST 두 개만 실행했다. 과거 대각 두 결과는 재사용했고
repair/retry/새 Graph/Provider 실행0이다. 종료 후 plan 재구성도 동일했다.

| UUID / 시각 | 최초 Goal 출력의 관측 | 이후 조립 |
| --- | --- | --- |
| 이전 / 이전 — 재사용 | due에 조회 지시문, description에 내부 필드 문자열 조각 | 그대로 DATE/RESOURCE constraint로 전달 |
| 현재 / 현재 — 재사용 | 조회 대상을 title/description 값으로 추가 | 그대로 RESOURCE constraint로 전달 |
| 이전 / 현재 — 신규 | additional은 비었지만 금지문·선택 표현·요청문이 search_terms에 포함 | 그대로 검색어 constraint로 전달 |
| 현재 / 이전 — 신규 | additional은 비었지만 금지문·상태·알려달라는 지시가 search_terms에 포함 | 그대로 검색어 constraint로 전달 |

조회 목적 자체는4/4 보존했다. 그러나 구조 VALID4/4는 전체 Goal 의미 PASS가 아니다.
슬롯 오염은 FIRST부터 있고 deterministic normalizer가 새로 만든 의미가 아니다.
additional만 비었다고 개선으로 세지 않는다. UUID-only/clock-only 변화의 안정화 효능이나
alias 채택 근거는 얻지 못했다. 원문·Provider target·WorkUnit·Prompt·Schema·sampling은 유지했다.
독립 검수도 동일 결론이며, 한 셀1회의 역사/신규 혼합으로 통계적 인과를 확정하지 않는다.

- 신규2회: input6,916/output496 tokens, reported27,951ms, usage 누락0.
- 재사용2회: input6,916/output438 tokens, reported20,126ms. 신규 비용에 합산하지 않는다.
- 두 신규 응답 모두 done=true/stop. Source/Output 및 downstream 업무 성공은 새로 평가하지 않았다.
- 직접·인접 runner 테스트134 PASS, Ruff/mypy PASS. 첫 mypy 경로 해석 오류는
  `--explicit-package-bases`로 재검사했으며 Product 설정을 바꾸지 않았다.
- raw `evaluation/results/067-goal-input-variance-t1/raw.json`, SHA256
  `70edad5a3a3119934f9016ba310a8c6feec4e9e8ca3645306c50ab5d6c0f39c2`.

판단: 이 진단을 이유로 Product input을 바꾸지 않는다. RU 일반 문구 변형을 계속 쌓지 않고,
별도로 반복 관측된 compose의 Provider completion enum 과잉해석을 기존 authority 기반으로
좁게 검증한다. 이는 RU 해결 선언이 아니며 금지/Source/Output 잔여 실패는 그대로 남는다.
