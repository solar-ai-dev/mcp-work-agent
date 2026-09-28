# 064 v39 — 현재 Output baseline 대 format 생략 + fence admission

실행 HEAD `72dd131a`, 사전 기준 `064-output-fence-core5-criteria.md`.
Core009/019/023/025/059 × baseline/candidate 각1회, 실제 신규10calls/재사용응답0.
기존 Production의 실제 FIRST 입력만 재사용하고 양 arm을 현재Prompt1.1.1로 새로 실행했다.
과거Prompt1.1.0의 점수나 wire를 현재baseline으로 승계하지 않았다.

## 실제 의미 결과

| Case | 현재 schema baseline | format 생략 + fence candidate | 최초 차이 |
| --- | --- | --- | --- |
|009|PASS: 상황 조회에 빈 Output|PASS: 동일|없음. 과거1.1.0의 불필요 Task/Draft와 구분|
|019|PASS: Event CREATE + 안내 Draft CREATE|FAIL: Draft만 남고 요청한 Event 누락|LLM FIRST에서 이미 Event를 생략. parser/normalizer 손실 아님|
|023|PASS: 요청한 Event CREATE만|PASS: 동일|없음. 참고 메일을 Draft 변경으로 확장하지 않음|
|025|PASS: Event CREATE|PASS: 동일|기존 단일 Event control 유지|
|059|PASS: GMAIL_MESSAGE SEND|PASS: 동일|명시 SEND를 Draft로 축소하거나 추가하지 않음|

Output owner 의미는 **5 PASS / 0 PARTIAL / 0 FAIL → 4 PASS / 0 PARTIAL / 1 FAIL**.
불필요 WRITE는 양쪽0이나 명시된 결과 누락이 0→1이다. 현재 확정 Work binding은 양쪽
모두 work-1로 유지했지만, ID가 맞다는 이유로019의 업무 누락을 통과시키지 않았다.

019의 소요시간 부족은 원래 의도된 확인 조건이다. 관련 READ 후 구체적 확인을 허용하며
임의 시간을 발명하라는 Gold가 아니다. Output owner는 사용자가 요청한 Event와 Draft의
의도를 보존해야 하므로 Event 누락은 정보부족의 정상 처리로 재분류하지 않는다.
이 단계의 PASS가 정확한 Preview·승인·외부 생성까지 완료했다는 뜻은 아니다.

## 구조·최초 응답·판정 보존

baseline strict 구조 **5/5**, candidate strict 구조 **0/5**(모두 단일 코드펜스).
새 candidate의 좁은 fence admission 후 schema/owner 검증은 **5/5**다. 각 원 strict
INVALID_JSON과 raw는 불변으로 보존했다. codec은 wrapper만 제거했으며019의 누락을
보충하지 않았다. raw 의미 표시는 UNREVIEWED이고 이 문서가 별도 근거 기반 의미 판정이다.

입력/Prompt/본문schema/options는 pair별 동일하며 top-level format 유무만 다르다.
같은 원 입력을 현재Prompt로 실행한009/023/059에서 과거 불필요 Output은 관측되지 않았다.
이는 이미 반영된Prompt1.1.1 아래 새 owner 관측이며 이번 실험이 새 Prompt를 채택한 것은
아니다. 과거 trial을 삭제하거나 이번 점수로 교체하지 않았다.

Goal/prohibition에 이미 있던009의 근거 없는 SEND금지,019의 메일발송 완료표현,
025의 임의 title/description 제약,059의 확인 통지/확인 요청 혼동은 그대로 입력했다.
이번 Output 결과를 해당 upstream 의미가 모두 복구됐다는 증거로 사용하지 않는다.

## 비용·환경

모델 `qwen3.5:9b`, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
temperature0 / seed20260923 / ctx16384 / thinkfalse / timeout180초.
현재Dataset/fixture hash와 사례별 원 reference time/fault는 plan에 결속했다.

| 실제 측정 | schema baseline | format 생략 candidate |
| --- | ---: | ---: |
| 신규 calls |5|5|
| input / output tokens |13,163 / 138|13,163 / 251|
| reported latency 합계 |16,349ms|11,933ms|
| wall latency 합계 |16,467ms|12,029ms|
| usage누락 / repair / retry / timeout |0 / 0 / 0 / 0|0 / 0 / 0 / 0|

첫 baseline의 cold load가 있어 합계로 속도 개선을 주장하지 않는다. 모델1개 직렬,
실행 중 코드편집/pytest/mypy/다른모델0. 시작 RAM여유20.1GB/GPU유휴43°C,
종료 RAM여유17.7GB/VRAM6385MiB/48°C. Graph/외부업무 Provider READ·WRITE·SEND0.

## 결정과 다음 경계

**REJECT**: format 생략 + fence admission을 Product에 반영하지 않는다.
v38의3개 raw에서는 형식과 내용이 모두 맞았으나 이번 새로운 control에서 명확한 결과 누락이
생겼다. 작은 성공을 일반화하지 않고 같은 format 변형의 추가 모델 비교를 중단한다.
기존 constrained Product transport/parser를 유지한다. Prompt/State/Schema/activation 변경0.

다음은 모델 호출 없이 확인된 Planning의 route-local 입력과 global 예산예측 불일치를
수정한다. 그 뒤 RU 잔여 실패는 이미 실패한 방법을 반복하지 않도록 기존 raw/최초 경계에서
새 근거가 있는 축만 선택한다. Canonical92 또는 compiled workflow 성공률은 이번에
측정하지 않았고 이를 Output owner 점수와 합산하지 않는다.

## 근거

- `evaluation/results/064-output-fence-v39-core5-t1/raw.json` SHA256
  `5a72ec4342b9bc4f621eaf9515c609a06b64329885341c9492f19532e65ec27e`.
- `evaluation/results/064-output-fence-v39-core5-plan/preregistered-plan.json` 파일SHA256
  `36bada08cbbf81354af242217dc101497f6b7e9f422b33fa35f947decb57cb38`;
  object hash `68cc6e0a9c021b5f5bfb64fe8107102a21301e37705059744ec10289e8a7013a`.
- 상세 raw는 로컬ignore보존, 이 요약/기준/실행기/직접검사는 원격 버전관리한다.
