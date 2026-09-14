# 03. 동시성과 자원

## Local API J=2

| Config | Episode | Job | Backend p95 (ms) | Goodput (page/s) | CPU (ms/page) | Probe p95 (ms) | Probe timeout |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S3 baseline | 50 | 100 | 9,612.38 | 0.224 | 551.72 | 20.83 | 0 |
| **B20/W1** | **50** | **100** | **2,791.13** | **0.836** | **148.44** | **30.08** | **0** |

## Production Node process 관측

| Config | CPU 평균 (ms) | RSS p50 (MiB) | RSS p95 (MiB) | RSS max (MiB) | Thread p50 | Thread p95 | Thread max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S3 baseline | 3,873.44 | 222.55 | 230.72 | 234.04 | 29 | 31 | 31 |
| B20/W1 | 1,549.06 | 222.53 | 231.74 | 489.29 | 26 | 28 | 152 |

| 관측 | 해석 |
| --- | --- |
| B20/W1 100개 중 99개 | Thread p95 28 이하, RSS p95 231.74MiB |
| B20/W1 1개 표본 | trial별 runtime teardown이 겹쳐 process 10개, thread 152, RSS 489.29MiB의 일시 이상치 발생 |
| 별도 persistent Local API J=2 | 반복 후 settled resource 안정성 확인 |
| context switch | Windows bundled runtime에서 per-process 누적 counter를 제공하지 않아 미측정 |
