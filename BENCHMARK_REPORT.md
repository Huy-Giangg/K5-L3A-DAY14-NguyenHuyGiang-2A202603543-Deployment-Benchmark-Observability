# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Nguyễn Huy Giang
**Ngày chạy:** 2026-11-26
**Môi trường:** Microsoft Windows 11 Home Single Language, AMD Ryzen 7 7435HS, 15.8 GB RAM, Python 3.11.6, Docker Desktop

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency bình thường của agent v2 (retrieval ~20 ms + LLM ~120–180 ms) khoảng 190–240 ms; ngưỡng 500 ms cho phép dao động khi tải tăng nhưng vẫn đảm bảo trải nghiệm real-time (trên Prometheus alert đặt ngưỡng lỏng hơn là > 1 s trong `2m` để tránh alert fatigue). |
| Error rate `/ask` | < 2.0 % | `MOCK_ERROR_RATE` mặc định là 1% (`0.01`); error budget 2% cho phép lỗi upstream ngẫu nhiên nhỏ, đồng thời bắt kịp thời khi lỗi vượt mức bình thường (Prometheus alert đặt > 5% trong `1m`). |
| Accuracy trên golden dataset | ≥ 80 % | Đảm bảo chất lượng trả lời trước khi merge/deploy (sau khi bổ sung knowledge base nâng quality gate lên `100%` với `0` regression). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Nguồn dữ liệu: [load_v2_c1.json](reports/load_v2_c1.json), [load_v2_c10.json](reports/load_v2_c10.json), [load_v2_c50.json](reports/load_v2_c50.json), [load_v2_c100.json](reports/load_v2_c100.json) (`--requests 300`).

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.85 | 198.6 | 236.4 | 1710.4 | 1.00% | PASS |
| 10 | 35.45 | 194.7 | 366.1 | 1728.9 | 1.33% | PASS |
| 50 | 106.89 | 199.4 | 309.8 | 1721.7 | 1.67% | PASS |
| 100 | 41.75 | 835.8 | 5167.1 | 5299.6 | 1.67% | FAIL |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Không. Từ `concurrency = 1` đến `50`, RPS tăng gần tuyến tính (`3.85 → 35.45 → 106.89 req/s`) nhờ `asyncio.sleep` trong mock LLM không block event loop nên 1 process FastAPI/uvicorn xử lý được nhiều request I/O song song. Tuy nhiên đến `concurrency = 100`, RPS tụt mạnh xuống `41.75 req/s`, `p50` tăng lên `835.8 ms`, `p95` vọt lên `5167.1 ms` (vi phạm SLO 500 ms) và xuất hiện `1` lỗi `conn_error:ReadError` (`{'200': 295, '503': 4, 'conn_error:ReadError': 1}`). Nguyên nhân là 1 process uvicorn đơn lẻ trên Windows bị bão hoà socket listen backlog và event loop khi nhận 100 kết nối đồng thời, làm request phải xếp hàng chờ xử lý.

### 2.2 Tail latency

Nguồn dữ liệu (`--requests 300 --concurrency 20`): [load_v2_slow_0.json](reports/load_v2_slow_0.json), [load_v2_slow_0.03.json](reports/load_v2_slow_0.03.json), [load_v2_slow_0.1.json](reports/load_v2_slow_0.1.json).

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 191.7 | 226.9 | 244.2 |
| 0.03 (mặc định) | 251.4 | 239.2 | 1711.4 |
| 0.1 | 289.1 | 1676.7 | 1711.8 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

**p99** (và tiếp theo là **p95** khi tỉ lệ chậm vượt 5%) nhạy nhất với request chậm, trong khi **average** thay đổi rất ít. Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03`, `avg` chỉ tăng nhẹ `59.7 ms` (`191.7 → 251.4 ms`) và `p95` giữ ở `239.2 ms`, nhưng `p99` nhảy vọt hơn 7 lần lên `1711.4 ms`. Khi tăng lên `0.1` (10% request chậm > 5%), cả `p95` cũng vọt lên `1676.7 ms` (FAIL SLO `500 ms`) trong khi `avg` mới là `289.1 ms`. Nếu đặt SLO theo `average`, nhóm 3–10% người dùng phải chờ gần 2 giây sẽ bị che giấu hoàn toàn bởi 90–97% request nhanh.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Nguồn dữ liệu: [eval_v1.json](reports/eval_v1.json), [eval_v2.json](reports/eval_v2.json), [eval_v2_fixed.json](reports/eval_v2_fixed.json).

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.3 | 108.8 | 113.7 |
| Tổng cost (USD) | $0.000406 | $0.000757 | $0.000790 |
| Cost / câu đúng (USD) | $0.00040635 | $0.00003607 | $0.00003436 |
| Quality gate | FAIL | PASS | PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry với từ khoá `["jwt"]` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` và `production/utils/mock_llm.py` giải thích JWT có chữ ký số, chứa thông tin user và thời điểm hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry với từ khoá `["hpa", "kubernetes", "autoscal"]` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` và `production/utils/mock_llm.py` giải thích Kubernetes HPA scale pod theo CPU, memory hoặc custom metrics. |

Kết quả chạy lại với `--min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json`: **23/23 (100.0%)**, `0` câu bị regression, `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS` (exit code `0`).

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

Agent v2 thêm bước retrieval (RAG) nên prompt dài hơn (~`113.7` tokens/câu so với `57.3` tokens/câu của v1, gấp ~2 lần), tổng chi phí cho 23 câu tăng từ `$0.000406` lên `$0.000790`, và latency `p95` tăng thêm ~`42–46 ms` (`188.3 ms` ở v1 → `234.4 ms` ở v2 và `230.2 ms` ở v2 fixed). Đổi lại, độ chính xác nhảy từ `4.3%` lên `100.0%`, kéo **cost / câu đúng** giảm **~11.8 lần** (từ `$0.00040635` xuống `$0.00003436`). Vì vậy đánh đổi này rất đáng giá cho production.

**Quality gate trong CI (Exercise 7.3):**

Script `eval/run_eval.py` trả về **exit code `0`** khi đạt `--min-accuracy` và có `0` regression so với `--baseline`, và trả **exit code `1`** nếu không đạt. Khi thử chạy `python eval/run_eval.py --url http://127.0.0.1:8001 --baseline reports/eval_v2.json` (so v1 với baseline v2), script báo `Quality gate ... ❌ FAIL` (`20` câu bị regression) và trả **exit code `1`**, giúp CI chặn merge PR tự động:

```yaml
# .github/workflows/eval.yml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Run agent + eval quality gate
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
          python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2.json
```

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**: [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Trả lời Exercise 7.4 (quan sát stack với 2 instance agent, 30 users Locust):**

1. **p95 và avg:** Khi chạy tải 30 users, Prometheus ghi nhận `avg = 233.4 ms` (`0.2334 s`) và `p95 = 293.5 ms` (`0.2935 s`, trên ảnh Grafana là `297.23 ms`, `Traffic = 10.6 req/s`, `Error rate = 0.00%`, `Saturation = 4`, `Instances up = 2`). Khoảng cách giữa `avg` và `p95`/`p99` (đường `p99` trên biểu đồ lên tới ~`1.7 s` do 3% request chậm) cho thấy latency không phân phối chuẩn mà có đuôi dài (tail latency).
2. **Panel "Requests/s theo instance":** Có chia đều. Giá trị đo từ Prometheus là `172.21.0.5:8000 = 9.29 req/s` và `172.21.0.9:8000 = 9.22 req/s` (~50/50) nhờ cơ chế round-robin của Nginx.
3. **Vì sao input tokens/s lớn hơn output tokens/s:** Đo được `input = 1428.5 tokens/s` so với `output = 747.8 tokens/s` (~1.9×). Vì agent v2 ghép thêm `SYSTEM_PROMPT` + tài liệu retrieve được từ `KNOWLEDGE_BASE` + câu hỏi người dùng vào input prompt, làm input dài hơn câu trả lời output.
4. **`curl -i http://localhost:8080/metrics`:** Trả về **`HTTP/1.1 404 Not Found`** từ Nginx (`nginx/1.28.3`), vì [nginx.conf](06-lab-complete/benchmark-observability/production/nginx/nginx.conf) chặn `location = /metrics { return 404; }`. `/metrics` chỉ phục vụ Prometheus scrape nội bộ trong Docker network `obs_net`, tránh lộ thông tin hệ thống, route, lưu lượng ra internet.

### 4.2 Thí nghiệm "phá hệ thống"

Unit test alert rules (`docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml`): **`SUCCESS`**.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`severity: critical`) | `88.7 s` (`for: 1m`) | **Error rate** (đỏ > 5%), **Requests/s theo status code** (503 tăng), **LLM calls theo kết quả** (`error` tăng) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`severity: warning`) | `147.8 s` (`for: 2m`) | **Latency p95** (đỏ > 1s), **Latency /ask — p50 / p95 / p99** (đường `p95` vọt lên ~1.7s) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`severity: warning`) | `145.7 s` (`for: 2m`) | **Cost burn rate (USD/giờ)** (vượt ngưỡng $2/giờ, đạt ~$17.11/giờ), **LLM latency p95 theo model**, **LLM cost (1h)** |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`severity: critical`) | `42.5 s` (`for: 30s`) | **Instances up** (giảm từ 2 xuống 1), **Requests/s theo instance** (instance bị pause tụt về 0) |
| E | `AGENT_VERSION=v1` | Không có alert mới nào firing | Không firing (chỉ theo dõi 75s) | **Retrieval hit ratio (agent v2)** (mất dữ liệu mới), **Tokens/s** (giảm ~50%: input `698.4/s`, output `380.1/s`), bảng **Phiên bản đang chạy** (`version="v1"`) |

*(Trong ảnh [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png), cả 2 alert **`LLMCostBurnRateHigh`** và **`AgentInstanceDown`** đang đồng thời ở trạng thái **`FIRING (1)`**.)*

**Phân tích bổ sung Thí nghiệm D (`docker pause` vs `docker stop` và lỗi 504):**
- Dùng `docker pause` thay vì `docker stop` vì khi stop container sẽ biến mất khỏi Docker DNS (`dns_sd_configs`), Prometheus coi như target không còn tồn tại chứ không đánh `up == 0`; khi pause container vẫn còn trong DNS nhưng không phản hồi `/metrics` nên `up{job="agent"} == 0` kích hoạt `AgentInstanceDown`.
- Lỗi `504 Gateway Timeout` ở Nginx (khi proxy chờ quá `proxy_read_timeout 10s` trên container bị treo/pause) không xuất hiện trên panel Error rate của agent vì request chưa bao giờ được agent xử lý xong để ghi counter `http_requests_total`; production cần thu thập thêm metric/log ở tầng Load Balancer (Nginx) và synthetic health check từ ngoài vào.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Alert hạ tầng (error rate, p95, instance up, cost) đều theo dõi sức khoẻ hệ thống chứ không biết câu trả lời có đúng hay không — khi đổi về `v1`, latency còn nhanh hơn và cost giảm, nên hạ tầng hoàn toàn "xanh". Để phát hiện sự cố chất lượng này cần:
1. **CI/CD Quality Gate:** chạy `eval/run_eval.py` trên golden dataset trước mọi lần deploy (`exit code 1` nếu accuracy tụt hoặc có regression).
2. **Metric nghiệp vụ RAG & Drift:** thêm alert cho `retrieval hit ratio` tụt đột ngột, tỉ lệ `input_tokens / request` giảm bất thường, hoặc giám sát nhãn `version` trên `agent_info`.
3. **Online Evaluation / User Feedback:** lấy mẫu traffic thật chấm bằng LLM-as-judge định kỳ và theo dõi tỉ lệ thumbs-up / thumbs-down của người dùng.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được (lấy từ Jaeger `/api/v3/traces/e08c79d81a5fd8e04f39a7073a19710f` và [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)):

- `trace_id`: `e08c79d81a5fd8e04f39a7073a19710f`
- Tổng thời gian: `1721.34 ms` (Jaeger UI hiển thị `1.7s`; `agent.run`: `1719.02 ms` = `99.9%`, `agent.retrieve_context`: `19.28 ms` = `1.1%`)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1699.48 ms`, `98.7%`)
- Dòng log tương ứng (grep từ `docker compose -p k5-day14-observability logs agent` theo `trace_id`):

```json
{"ts": "2026-11-26T04:13:04.215742+00:00", "level": "INFO", "service": "observable-agent", "instance": "d1c5c747dd9a", "event": "llm_call", "trace_id": "e08c79d81a5fd8e04f39a7073a19710f", "span_id": "081232e655302728", "request_id": "cc28ae51e756", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1698.8}
```

*(Trace lỗi tham khảo trong [jaeger-error-trace.png](screenshots/jaeger-error-trace.png): `trace_id = f41e802b5a343241e8d0efb1db50b8b3`, tổng thời gian `105.55 ms`, HTTP `503`, span `chat mock-llm-small` ghi event `exception` với `exception.message = Upstream LLM error: 503 Service Unavailable (mock)`.)*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Nguồn dữ liệu: [scale_1_stats.csv](benchmark-results/scale_1_stats.csv) và [scale_3_stats.csv](benchmark-results/scale_3_stats.csv) (dòng `Aggregated` — gồm `POST /ask` và `GET /health`):

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 64.87 | 190 | 500 | 1700 | 70 / 7699 (0.91%) |
| 3 | 65.75 | 190 | 250 | 1700 | 68 / 7865 (0.86%) |

*(Chi tiết riêng endpoint `POST /ask`: với `1` instance đạt `58.88 req/s`, p50=`200 ms`, p95=`580 ms`, p99=`1700 ms`, `70` fails / `6988` reqs; với `3` instances đạt `59.74 req/s`, p50=`190 ms`, p95=`250 ms`, p99=`1700 ms`, `68` fails / `7146` reqs.)*

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Scale từ 1 lên 3 instance **cải thiện rõ rệt `p95`** (`500 ms → 250 ms` trên `Aggregated`, và `580 ms → 250 ms` riêng trên `/ask`) vì với 1 container bị giới hạn `0.5` CPU, 100 user đồng thời tạo ra hàng đợi nhẹ ở event loop của uvicorn; khi chia tải qua 3 instance bằng Nginx round-robin, hiện tượng xếp hàng biến mất. Tuy nhiên `p50` (`190 ms`), `p99` (`1700 ms`) và `RPS` (`64.87 → 65.75 req/s`) gần như không đổi vì hai nút thắt:
1. **Upstream LLM latency:** mỗi request đều phải chờ `mock_llm.generate()` (~120–180 ms, và ~3% request dính tail latency `+1500 ms`), việc tăng số instance agent không làm LLM trả lời nhanh hơn.
2. **Tải sinh ra từ client Locust:** 100 user với `wait_time = between(0.5, 2)` (trung bình nghỉ 1.25s + ~0.24s xử lý ≈ 1.5s/vòng) chỉ tạo tối đa ~`100 / 1.5 ≈ 66 req/s`, nên cả 1 và 3 instance đều đáp ứng đủ tải mà chưa chạm ngưỡng bão hoà thông lượng.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average che giấu tail latency:** SLO hiệu năng phải đặt theo `p95`/`p99`; chỉ 3% request chậm đã đẩy `p99` lên ~`1.7 s` trong khi `avg` vẫn đẹp (~`251 ms`).
  2. **3 trụ cột Metrics + Traces + Logs liên kết chặt với nhau:** Prometheus/Grafana phát hiện bất thường tổng thể (Golden Signals), Jaeger xác định chính xác span nút thắt (`chat mock-llm-small` chiếm `98.7%`), và `trace_id` trong JSON log nối thẳng tới chi tiết sự kiện/lỗi.
  3. **Infra observability không bắt được lỗi chất lượng:** Hệ thống có thể "xanh toàn bộ" dù agent trả lời sai (Thí nghiệm E); cần kết hợp `eval` trên golden dataset làm quality gate trong CI/CD cùng metric chi phí (`cost / câu đúng`) và cảnh báo chất lượng.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Tích hợp **Alertmanager** gửi cảnh báo tới Slack / PagerDuty và bổ sung **Nginx / Load Balancer metrics + synthetic probe** để bắt lỗi `502`/`504` trước khi vào agent.
  - Theo dõi các chỉ số đặc thù cho production agent: **tỉ lệ `429` (rate limit)**, **tỉ lệ `402` (cost guard / budget còn lại)**, **Redis latency & connection errors**, và **online eval / retrieval hit-ratio drop alert** để phát hiện suy giảm chất lượng câu trả lời sớm.
