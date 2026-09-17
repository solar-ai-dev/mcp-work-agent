# Development Datasets

이 영역은 RU와 Retrieval 품질 개발·튜닝용 Dataset을 보관한다.

- canonical active Dataset이나 promotion/release 평가 Dataset이 아니다.
- canonical default runner에 자동 등록하지 않는다.
- Gold를 모델 출력에 맞춰 수정하지 않는다.
- 각 version은 검수 후 freeze하고 baseline과 candidate 비교에 동일하게 사용한다.

## RU development evaluation

현재 Dataset인 `ru_quality_dev_v2.jsonl`은 canonical `grader_v8`과 분리된 개발 전용
`ru-quality-dev-grader-v2`를 사용한다. `ru_quality_dev_v1.jsonl`과 v1 manifest는 최초
freeze 상태를 보존하는 역사적 Artifact이며 수정하지 않는다.
Production Request Understanding subgraph까지만 실행하고 Retrieval, Connector, Planning,
Preview, WRITE는 호출하지 않는다.

```powershell
.venv-cpu\Scripts\python.exe scripts\evaluate_ru_quality_dev.py `
  --case-id RU-B-002 `
  --case-id RU-D-002
```

전체 24개 실행은 실수로 시작되지 않도록 명시적인 `--all`이 필요하다. 결과는 기본적으로
`evaluation/results/ru-quality-dev-<YYYYMMDD>/`에 JSON으로 저장되며 공식 baseline 또는
promotion evidence가 아니다. LangSmith API key는 process environment 또는 `.env.local`에서
읽고, trace는 `google-work-agent-development` project에 기록한다.
