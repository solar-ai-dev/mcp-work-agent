# 066 v46 — 4B 고정 Source 진단: 의미0/3, REJECT

## 조건과 실제 결과

HEAD `9c381ef4`, 사전 기준 `066-source-fixed-model-v46-criteria.md`대로 신규3 FIRST를
직렬 실행했다. 기존 Source Product wire에서 model만 이미 설치된 qwen3.5:4b로 변경했다.
v45 catalog 제거, Prompt/Schema 변경, 학습, Product 모델 설정 변경은 없다.
9B baseline은 v42 default3개 재사용이며 현재 wire/Schema/validator 재구성 일치를 확인했다.
과거 SHA를 현재와 같다고 하지 않는다.

| Core | 9B baseline → 4B | 최초 Source FIRST 의미 차이 |
| --- | --- | --- |
| 009 | FAIL → FAIL | baseline의 Task 누락에 메일 근거까지 추가 소실. 모든 Source를 NOT_REQUIRED로 판단 |
| 049 | PARTIAL → FAIL | 필요한 메일·Task·Calendar를 전부 제외. 사용자가 새 객체 값을 일부 제시한 것이 기존 자료를 모두 확인하라는 요구를 없애지 않음 |
| 059 | PASS → FAIL | reply 대상 메일의 실제 identity/Thread/내용이 입력에 제공되지 않았는데 모든 Source 제외. '확인했다'는 작성 취지만으로 기존 메일 접근이 불필요해지지 않음 |

합계 **1 PASS / 1 PARTIAL / 1 FAIL → 0 / 0 / 3**. 기존 성공1건 회귀, 부분결과1건 악화,
기존 실패1건에서도 필요한 근거 추가 손실이다. 독립 검수도 같은 판정이다.
세 응답 모두 done=true/stop, Schema3/3 VALIDATED이고 raw와 validated의 의미는 같다.
구조 검증은 불필요 Source0을 올바른 업무 의미로 바꾸지 않는다. 의존성 누락을
validator가 채우거나 이전에 제거한 all-NOT_REQUIRED 의미 guard를 복구하지 않는다.

**REJECT: 이번 실패군의 해결책으로 4B를 채택하지 않는다.** 이 결과가9B의 모델 한계나
SFT 필요성의 증거라는 뜻도 아니다. 단발 Source-only 진단이지 전체4B 품질평가가 아니며
기존 지원 계약을 폐기하거나 사용자 설정을 바꾸지 않는다. 새 모델 반복/92 전수0.

## 비용·자원

| 구성 | 실제 calls | input / output tokens | reported LLM ms |
| --- | ---: | ---: | ---: |
| 9B 재사용 | 3 | 12,216 / 670 | 24,619 |
| 4B 신규 | 3 | 12,216 / 704 | 19,189 |

4B wall합19,264ms/load합3,666ms, usage 누락0. 완료된 출력 길이가 달라졌고 서로 다른
시점/모델/첫 load의 단발값이므로 속도 개선이나 parameter-count의 인과효과로 일반화하지 않는다.
새로 빠르게 생성한 답이 모두 의미 실패여서 품질 Gate를 넘지 못했다.

실행 직전 RAM여유19.66/31.71GiB, GPU0/8188MiB·45°C. 종료 직전 관측GPU4325MiB·0%·58°C,
결과 확인 시 RAM여유18.01GiB/GPU4325MiB·54°C. 순간 snapshot이며 peak 측정은 아니다.
generation 동시1, generation 중 편집/pytest0. 준비 direct/regression32 PASS, Ruff/mypy PASS.
모델 다운로드·학습·사용자process종료·서버재시작0.

## Runtime/근거 결속

- 4B `2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`,
  9B `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
  Ollama0.34.0, Q4_K_M/qwen35, temp0.05/seed20260923/ctx16384/think=false.
  show defaults 양쪽 presence1.5/temp1/top_k20/top_p0.95 동일. 4B actual response model3/3 일치.
- 4B 사전 무추론 렌더는 system/user/assistant 구분과 think=false 종료 구간을 확인했다.
  responseempty/donefalse/debug-only 관측이며 generation/semantic 결과로 세지 않았다.
- Dataset `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`,
  fixture `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
- plan object SHA256 `a7039751b9618981f5280456e4672fc355fd12ab22e3c4d90cdd050b4fc172fc`:
  `evaluation/results/066-source-fixed-model-v46-plan/preregistered-plan.json`.
- raw bytes SHA256 `5caada7871a88e0ddd8e5093c0f2c1cf846dac82bfa134e68b62719159161a2c`:
  `evaluation/results/066-source-fixed-model-v46-t1/raw.json`.
- render observation bytes SHA256 `4ee2004efaca46968dd97bb8475835e5fce6bc3d192acc7ee4475caf4c816b51`:
  `evaluation/results/066-source-fixed-model-v46-preflight/render-observation.json`.

원 raw의 UNREVIEWED는 그대로 두고 이 문서가 별도 의미 판정이다. Provider READ/WRITE,
승인, Graph/업무 실행0. 불필요 WRITE·다른 RU owner·Retrieval/Planning 이후는 미검증이며
Source 실패 개수와 합치지 않는다. Production9B 및 Prompt/State/승인 안전 계약 유지.

## 다음 선택 제약

9B Source v45와4B v46 모두 기각했으므로 둘을 결합하거나 새로운 문구를 더해 재시도하지
않는다. Goal projection 삭제/Source-Output fusion/금지 sparse/Runtime sampler/format 등
이미 실패한 축도 새 인과 근거 없이 반복하지 않는다. 가장 강한 구조 근거인 v4의 Output
재생성 제거는 보존하지만 기존 Goal completion/prohibition/status 회귀까지 해결됐다고
채택하지 않는다. 현재9B Output T3와 Source 잔여 실패는 아직 미해결이다.
