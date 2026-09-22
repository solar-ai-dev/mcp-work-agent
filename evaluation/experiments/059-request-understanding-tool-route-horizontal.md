# 059 — Request Understanding → Tool Route 수평 진단

Issue: #289 후속 진단

## 결론

현재 Production HEAD의 compiled Request Understanding과 Tool Route를 Canonical Core
10건에서 각각 1회 연결 실행했다. 구조적으로는 10/10이 Tool Route까지 도달했지만,
Canonical 업무 의미 기준은 `PASS 1 / PARTIAL 1 / FAIL 8`이었다.

최초 주된 divergence는 Tool 선택이 아니라 Request Understanding의
`identify_output_responsibilities`다. 단순 READ에 WRITE를 추가하고, UPDATE를 CREATE로
바꾸거나, 명시하지 않은 다른 Output을 추가한 결과가 schema-valid candidate로 통과했다.
Tool Route는 이 잘못된 `RequestIntentV3`를 다시 해석하지 않고 Registry route로 정확히
투영했다. 이는 현재 ownership 계약에 맞으므로 downstream 보정 대상이 아니다.

## 고정 조건

- Product SHA: `6455e82327d5e47c4f9154ba98e591327d70ddbc`
- Dataset SHA-256: `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Fixture SHA-256: `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`
- Prompt manifest SHA-256: `29161dcc93325b50655571c91b7e7cebc0eac07214f4617216ba541009ed2ea9`
- Model: `qwen3.5:9b`, digest
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature `0.0`, seed `20260923`, Case당 1회, rerun-to-pass `0`
- 범위: compiled RU → compiled Tool Route만 실행
- Provider READ/WRITE/SEND: `0/0/0`

## Case 결과

| Case | 판정 | 최초 의미 차이 | Tool Route 결과 |
| --- | --- | --- | --- |
| CORE-001 | PASS | 없음 | selected Gmail Thread READ, Output 없음 |
| CORE-005 | FAIL | 금지·Output 판단 | Task 상태 READ 요청에 Task UPDATE와 Gmail SEND 추가 |
| CORE-009 | FAIL | Output 판단 | 메일+Task 현황 ANSWER 요청에 Gmail SEND와 Task CREATE 추가 |
| CORE-012 | FAIL | Output 판단 | Draft CREATE에 금지된 SEND를 추가 |
| CORE-019 | FAIL | ambiguity 판단 | 소요시간 미확정인데 Confirmation 없이 Event+Draft Route 생성 |
| CORE-035 | FAIL | Output 판단 | Task CREATE 요청에 Calendar Event CREATE 추가 |
| CORE-037 | FAIL | Output 판단 | Task UPDATE를 Draft CREATE+Task CREATE+Event CREATE로 변경 |
| CORE-049 | FAIL | requested work/source 판단 | 세 Output은 유지했으나 WorkUnit 하나로 합치고 Gmail·Task·Calendar source responsibility를 누락 |
| CORE-056 | PARTIAL | prohibition 판단 | Gmail READ/Output 없음은 맞지만 `실행은 하지 마` prohibition이 빈 값으로 소실 |
| CORE-059 | FAIL | Output 판단 | Gmail SEND에 요청하지 않은 Draft CREATE 추가 |

Tool Route에서는 모든 생성 Route가 Registry에 결속됐고 `route_id`와 `work_unit_ids`는
소실되지 않았다. 따라서 최종 Route가 잘못된 Case의 first divergence는 upstream RU다.
이번 표의 PASS/PARTIAL/FAIL은 업무 의미 판정이며 runner의 `ROUTE_READY`는 단지 graph가
Route artifact를 만들었다는 구조적 상태다.

## 호출·지연

- 전체 LLM 호출: `71`
- input/output tokens: `175,452 / 6,690`
- 모델 보고 latency 합: `347,866 ms`
- wall latency 합: `358,788 ms`
- Tool 선택 LLM 호출: `0`

이번 10건에서 Registry 후보가 여러 개인 Output capability는 생성되지 않아 #289의
ambiguous Tool 선택 fan-out은 이 수평 실행에서 재측정되지 않았다. 동일 capability
N-route 1회 선택, 단일 후보 0회, 서로 다른 capability 독립 선택은 #289의 직접
unit/component gate에서 별도로 검증됐다.

## 다음 판단

Tool Route나 Planning에서 보정하지 않는다. 먼저 RU의 Output responsibility raw candidate와
final validated decision을 비교해 `goal_candidate`의 오염인지, Output owner 자체의 과잉
선택인지 구분한다. CORE-019는 ambiguity owner, CORE-049는 requested-work/source owner의
별도 first divergence로 유지한다. 이 진단만으로 Prompt·Schema 수정은 채택하지 않는다.
