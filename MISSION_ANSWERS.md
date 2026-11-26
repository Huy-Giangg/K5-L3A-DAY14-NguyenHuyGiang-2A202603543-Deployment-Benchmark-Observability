# Day 14 Lab - Mission Answers

> **Môn:** AICB-P1 · Day 14 — Deployment, Benchmark & Observability (K5)  
> **Lưu ý bảo mật:** Toàn bộ JWT token trong output bên dưới đã được che (`<REDACTED>`); không có secret, email hay số điện thoại thật trong tài liệu này.

---

## Part 1: Localhost vs Production (`01-localhost-vs-production/`)

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret và thông tin kết nối DB trong mã nguồn (`develop/app.py` dòng 17–18):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên Git, secret bị lộ ngay lập tức trong lịch sử commit.
2. **Không có quản lý cấu hình theo môi trường (`develop/app.py` dòng 21–22):**
   - `DEBUG = True` và `MAX_TOKENS = 500` được gán cứng thay vì đọc từ biến môi trường (`os.getenv`), khiến việc đổi cấu hình giữa dev/staging/production phải sửa code.
3. **Dùng `print()` để debug và in thẳng secret ra stdout (`develop/app.py` dòng 33–34, 38):**
   - `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa làm lộ API key vào log, vừa tạo log dạng text tự do thay vì structured JSON logging khó parse/tìm kiếm trên hệ thống log tập trung.
4. **Thiếu health check / readiness endpoint (`develop/app.py` dòng 42–43):**
   - Không có `GET /health` hay `GET /ready`. Cloud platform (Railway, Render, Cloud Run, Kubernetes) và load balancer không thể biết khi nào app còn sống hoặc sẵn sàng nhận traffic để tự động restart hay route traffic.
5. **Bind `localhost`, cố định `port=8000` và bật `reload=True` (`develop/app.py` dòng 49–53):**
   - `host="localhost"` chỉ nhận kết nối nội bộ (không nhận traffic từ bên ngoài container); `port=8000` cố định không đọc biến `PORT` do cloud platform cấp; `reload=True` bật file watcher tốn tài nguyên và không an toàn trên production.
6. **Không có cơ chế Graceful Shutdown và CORS (`develop/app.py`):**
   - Thiếu `lifespan` / xử lý `SIGTERM` nên khi container tắt, các request đang xử lý có thể bị cắt ngang; cũng chưa cấu hình `CORSMiddleware` và validate biến môi trường bắt buộc khi chạy production (`fail fast`).

### Exercise 1.2: Kết quả chạy bản develop (`01-localhost-vs-production/develop/app.py`)

Chạy `python app.py` trong `01-localhost-vs-production/develop/` và gọi `curl -i -X POST "http://localhost:8000/ask?question=Hello"` (theo lưu ý K5 #3, bản develop nhận `question` qua query parameter):

```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:01:18 GMT
server: uvicorn
content-length: 126
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

*(Server console đồng thời in `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this` — minh họa rủi ro lộ secret qua log.)*

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` & `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`, `MAX_TOKENS=500` trong code | `Settings` dataclass trong `config.py` đọc từ `os.getenv(...)` và `validate()` fail fast nếu thiếu `AGENT_API_KEY` ở `production` | Tuân thủ 12-Factor App: tách biệt code và config, thay đổi theo môi trường không cần sửa code, tránh lộ secret lên Git |
| **Network & Port** | `host="localhost"`, `port=8000`, `reload=True` | `host=settings.host` (`0.0.0.0`), `port=settings.port` (từ `PORT` env), `reload=settings.debug` | Container/cloud cần bind `0.0.0.0` để nhận request từ ngoài và lắng nghe đúng `PORT` do platform cấp |
| **Health Check** | Không có `/health` hay `/ready` | Có `GET /health` (liveness: uptime, version, env) và `GET /ready` (readiness: trả `503` khi `not is_ready`) | Orchestrator/load balancer dựa vào `/health` để restart container lỗi và `/ready` để chỉ route traffic khi app sẵn sàng |
| **Logging** | `print("[DEBUG] ...")`, log cả `OPENAI_API_KEY` | `logging` với format JSON (`{"time":...,"level":...,"msg":...}`) + `json.dumps(...)`, không log secret | Log JSON có cấu trúc giúp công cụ như Datadog, Loki, Grafana dễ parse, filter, cảnh báo và bảo vệ thông tin nhạy cảm |
| **Shutdown** | Tắt đột ngột, không có lifecycle hook | `@asynccontextmanager async def lifespan` set `is_ready = False` khi tắt + `signal.signal(signal.SIGTERM, handle_sigterm)` | Tránh ngắt ngang request đang xử lý (in-flight requests) và giúp đóng kết nối DB/Redis an toàn khi deploy/scale |
| **CORS & Input** | Không có CORS, nhận `question` qua query param | `CORSMiddleware` với `settings.allowed_origins`; `/ask` nhận JSON body và trả `422` nếu thiếu `question` | Giới hạn domain được phép gọi API từ trình duyệt và chuẩn hóa contract API JSON |

---

## Part 2: Docker (`02-docker/`)

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` (dòng 8: `FROM python:3.11`) — bản Python đầy đủ (~1 GB) chứa sẵn OS Debian, compiler và nhiều công cụ không cần thiết ở runtime.
2. **Working directory là gì?**
   - `/app` (dòng 11: `WORKDIR /app`) — mọi lệnh `COPY`, `RUN`, `CMD` sau đó thực thi tương đối trong `/app`.
3. **Tại sao `COPY 02-docker/develop/requirements.txt .` đứng trước `COPY 02-docker/develop/app.py .`?**
   - Để tận dụng **Docker layer cache**. `requirements.txt` ít thay đổi hơn mã nguồn `app.py`; khi chỉ sửa code Python, Docker tái sử dụng layer `RUN pip install --no-cache-dir -r requirements.txt` đã cache thay vì cài lại toàn bộ thư viện từ đầu.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `CMD` định nghĩa lệnh/tham số mặc định khi chạy container và **có thể bị ghi đè dễ dàng** bằng đối số truyền cuối lệnh `docker run <image> <new-cmd>`.
   - `ENTRYPOINT` cố định executable chính của container; đối số truyền thêm vào `docker run` sẽ được nối vào sau `ENTRYPOINT` (chỉ bị ghi đè khi dùng cờ `--entrypoint`).

### Exercise 2.2 & 2.3: Build, test container & so sánh kích thước image (`develop` vs `production`)

Build từ thư mục gốc repo:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
```

**Kết quả test container `my-agent:develop` (`POST /ask?question=Hello`):**
```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:03:54 GMT
server: uvicorn
content-length: 126
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

**Phân tích Multi-stage build (`02-docker/production/Dockerfile`):**
- **Stage 1 (`builder` từ `python:3.11-slim AS builder`):** Cài build tools (`gcc`, `libpq-dev`) và cài Python packages bằng `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime` từ `python:3.11-slim AS runtime`):** Tạo non-root user `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local`, `main.py` và `utils/mock_llm.py`, cấu hình `HEALTHCHECK` và chạy `uvicorn` với 2 workers.
- **Vì sao image nhỏ hơn:** Stage `runtime` loại bỏ hoàn toàn `gcc`, `libpq-dev`, headers hệ thống và cache build của Stage 1, đồng thời dùng `python:3.11-slim` thay cho `python:3.11` đầy đủ.

**So sánh kích thước image đo thực tế (`docker images` & `docker image inspect`):**

| Image | Base / Kiến trúc | Disk Usage (`docker images`) | Content Size (`VirtualSize`) |
|---|---|---|---|
| `my-agent:develop` | Single-stage (`python:3.11`) | `1.67 GB` (1,670 MB) | `426 MB` (`426,320,219` bytes) |
| `my-agent:advanced` | Multi-stage (`python:3.11-slim`) | `240 MB` | `57.4 MB` (`57,408,820` bytes) |
| **Mức giảm** | | **−85.63%** (`1,430 MB` nhỏ hơn) | **−86.53%** (`368.9 MB` nhỏ hơn) |

### Exercise 2.4: Docker Compose stack & sơ đồ kiến trúc (`02-docker/production/docker-compose.yml`)

**Sơ đồ kiến trúc các services (cùng nằm trên network `internal`):**

```text
               ┌──────────────────────────────┐
  Client ─────►│  nginx (nginx:alpine)        │  port 80 / 443
               │  Reverse Proxy & Rate Limit  │  (10 req/s, burst=20)
               └──────────────┬───────────────┘
                              │ proxy_pass http://agent_backend
                              ▼
               ┌──────────────────────────────┐
               │  agent (FastAPI + uvicorn)   │  port 8000 (internal only)
               │  non-root appuser, 2 workers │
               └──────┬───────────────┬───────┘
                      │               │
      REDIS_URL       ▼               ▼  QDRANT_URL
        ┌───────────────────┐   ┌───────────────────┐
        │ redis:7-alpine    │   │ qdrant:v1.9.0     │
        │ port 6379         │   │ port 6333         │
        │ vol: redis_data   │   │ vol: qdrant_data  │
        └───────────────────┘   └───────────────────┘
```

- **Các services được khởi động (`docker compose -p k5-day14-part2 up -d --build`):**
  - `redis` (`redis:7-alpine`, healthy), `qdrant` (`qdrant/qdrant:v1.9.0`, healthy), `agent` (chỉ start sau khi `redis` và `qdrant` đạt `service_healthy`, giao tiếp nội bộ qua DNS `redis:6379` và `qdrant:6333`), và `nginx` (`nginx:alpine`, expose port 80/443 và proxy vào `agent:8000`).

**Kết quả test thực tế qua Nginx (`http://localhost/...`):**

1. `GET /health`:
```http
HTTP/1.1 200 OK
Server: nginx
Date: Thu, 26 Nov 2026 04:04:29 GMT
Content-Type: application/json
Content-Length: 95
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":1.5,"version":"2.0.0","timestamp":"2026-11-26T04:04:29.137603"}
```

2. `POST /ask` (`{"question":"Explain microservices"}`):
```http
HTTP/1.1 200 OK
Server: nginx
Date: Thu, 26 Nov 2026 04:04:29 GMT
Content-Type: application/json
Content-Length: 126
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

*(Đã chạy `docker compose -p k5-day14-part2 down -v`, xóa file tạm `.env.local` và dọn các image tạm `my-agent:*`.)*

---

## Part 3: Cloud Deployment (`03-cloud-deployment/` & `06-lab-complete/`)

### Exercise 3.1 / 3.2: Triển khai Agent Part 6 lên Cloud

- **Platform chính:** Railway (project `day14-production-agent`, gồm 2 services: `agent` + `Redis`)
- **Public URL:** https://agent-production-b4d250eb.up.railway.app
- **Kiểm tra live endpoints (CP6):**
  - `GET /health` → `200` (`{"status":"ok"}`)
  - `GET /ready` → `200` (`{"status":"ready","redis":"connected"}`)
  - `POST /ask` (không có `X-API-Key`) → `401`
  - `POST /ask` (có `X-API-Key` hợp lệ) → `200`
- **Screenshots:**
  - [Dashboard](screenshots/dashboard.png)
  - [Service running](screenshots/running.png)
  - [Test results](screenshots/test.png)
- **Chi tiết triển khai & lệnh test:** Xem [DEPLOYMENT.md](DEPLOYMENT.md).

### So sánh `06-lab-complete/railway.toml` vs `06-lab-complete/render.yaml`

So sánh hai file cấu hình triển khai của agent Part 6 (`06-lab-complete/railway.toml` và `06-lab-complete/render.yaml`):

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) | Tại sao khác nhau? |
|---|---|---|---|
| **Định dạng & Phạm vi** | File TOML gọn nhẹ cho **1 service** hiện tại (`[build]`, `[deploy]`) | File YAML khai báo **Infrastructure as Code (IaC)** cho cả hệ thống (`services:` danh sách nhiều service, có thể gồm web + redis) | Railway quản lý project/add-on (Redis, env vars) trực tiếp trên dashboard/CLI; Render Blueprint dùng 1 file `render.yaml` mô tả toàn bộ hạ tầng từ Git |
| **Cách build** | `builder = "DOCKERFILE"` | `runtime: docker` (trong service `type: web`) | Cả hai đều dùng `Dockerfile` multi-stage của `06-lab-complete/`, nhưng tên field theo schema riêng của từng platform |
| **Health check & Restart** | `healthcheckPath = "/health"`, `restartPolicyType = "ON_FAILURE"` | `healthCheckPath: /health` (Render tự quản lý restart khi healthcheck fail) | Railway cho phép cấu hình explicit chính sách restart (`ON_FAILURE`), còn Render gắn chặt vào lifecycle của web service |
| **Biến môi trường & Secrets** | Không khai báo env vars trong `railway.toml`; set qua Dashboard hoặc `railway variables set` | Khai báo rõ `envVars` trong `render.yaml`: giá trị tĩnh (`ENVIRONMENT=production`), `generateValue: true` (`AGENT_API_KEY`), `sync: false` (`REDIS_URL` nhập tay khi tạo Blueprint) | Render Blueprint muốn tái lập cấu hình biến môi trường ngay lúc import repo, nhưng vẫn chặn lộ secret bằng `sync: false` và `generateValue: true` |

### Exercise 3.3: GCP Cloud Run CI/CD Pipeline (`03-cloud-deployment/production-cloud-run/`)

Dựa trên `cloudbuild.yaml` và `service.yaml`, pipeline CI/CD trên GCP Cloud Build đi qua 4 bước tuần tự (`waitFor`) khi có push lên nhánh `main`:
1. **`test` (`python:3.11-slim`):** Cài dependencies từ `requirements.txt` cùng `pytest` và chạy `pytest tests/ -v --tb=short` — nếu test fail, pipeline dừng ngay.
2. **`build` (`gcr.io/cloud-builders/docker`):** Build Docker image gắn tag `$COMMIT_SHA` và `latest`, tận dụng `--cache-from` từ image `latest` trên GCR để tăng tốc.
3. **`push` (`gcr.io/cloud-builders/docker`):** Đẩy toàn bộ tags lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy` (`gcr.io/cloud-builders/gcloud`):** Chạy `gcloud run deploy ai-agent` triển khai image `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`, `min-instances=1` tránh cold start, `max-instances=10`, 512Mi/1 CPU), inject secret từ Secret Manager (`--set-secrets`) tương ứng với đặc tả `service.yaml` (có `livenessProbe` `/health` và `startupProbe` `/ready`).

---

## Part 4: API Security (`04-api-gateway/`)

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **Kiểm tra ở đâu:** Dependency `verify_api_key` (dòng 39–54) đọc header `X-API-Key` bằng `APIKeyHeader(name="X-API-Key", auto_error=False)` và được gắn vào route `POST /ask` qua `_key: str = Depends(verify_api_key)` (dòng 70).
- **Thiếu / sai key:** Thiếu header → `401 Unauthorized`; sai giá trị `AGENT_API_KEY` → `403 Forbidden`.
- **Rotate key:** Đổi biến môi trường `AGENT_API_KEY` trên nền tảng/secret manager và restart/redeploy service (trong production có thể hỗ trợ đồng thời 2 key cũ/mới trong giai đoạn chuyển tiếp để zero-downtime rotation).

**Kết quả test thực tế (`AGENT_API_KEY=secret-key-123`):**

1. **Không có `X-API-Key` (401):**
```http
HTTP/1.1 401 Unauthorized
date: Thu, 26 Nov 2026 04:01:21 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

2. **Có `X-API-Key: secret-key-123` (200):**
```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:01:21 GMT
server: uvicorn
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **JWT Flow (`auth.py`):** Client gửi username/password tới `POST /auth/token` → server xác thực (`authenticate_user`) và ký JWT (`HS256`, hạn 60 phút, payload chứa `sub`, `role`, `iat`, `exp`) → các request tới `POST /ask` gửi `Authorization: Bearer <token>` và được `verify_token` kiểm tra chữ ký không cần query DB mỗi request.
- **Rate Limiting (`rate_limiter.py`):**
  - **Thuật toán:** **Sliding Window Counter** dùng `deque` lưu timestamp các request trong cửa sổ `window_seconds=60` (trong production lưu vào Redis sorted set để dùng chung giữa nhiều instance).
  - **Giới hạn:** User (`student`, role `user`) bị giới hạn **10 requests/phút** (`rate_limiter_user`); Admin (`teacher`, role `admin`) được cấu hình **100 requests/phút** (`rate_limiter_admin`).
  - **Bypass/tách tier cho admin:** Trong `app.py` (dòng 141), dựa vào `user["role"] == "admin"` để chọn `rate_limiter_admin` (hoặc bỏ qua bước `limiter.check(...)` nếu muốn miễn hoàn toàn cho admin).

**Kết quả test thực tế (`student` / `demo123`, JWT token đã che):**

1. **Lấy token qua `POST /auth/token`:**
```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:02:11 GMT
server: uvicorn
content-length: 307
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"eyJhbGciOiJI...<REDACTED>...IaaH2Y","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJhbGciOiJI......"}
```

2. **Gọi `POST /ask` lần lượt — Request #1 (200), #10 (200, còn 0 lượt), #11 (429):**
```http
# Request #1
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:02:11 GMT
server: uvicorn
content-length: 187
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Test 1","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

# ... (Requests #2–#9 đều trả 200 OK, requests_remaining giảm từ 8 xuống 1) ...

# Request #10
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 04:02:13 GMT
server: uvicorn
content-length: 181
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Test 10","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000172}}

# Request #11 (vượt quá 10 req/phút)
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 04:02:13 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795665793
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Phân tích cài đặt Cost Guard (`04-api-gateway/production/cost_guard.py`)

Rate limit chỉ giới hạn **tần suất gọi** (requests/phút), không chặn được trường hợp mỗi prompt rất dài làm tốn nhiều token; ngược lại **Cost Guard** bảo vệ trực tiếp **chi phí tiền thật (USD)**:
- **Định giá token (`PRICE_PER_1K_INPUT_TOKENS = 0.00015`, `PRICE_PER_1K_OUTPUT_TOKENS = 0.0006`):** Dùng `UsageRecord` theo từng `(user_id, day)` để cộng dồn `input_tokens`, `output_tokens`, `request_count` và tính `total_cost_usd` chính xác tới 6 chữ số thập phân.
- **Hai tầng ngân sách trong `CostGuard`:**
  1. **Global daily budget (`global_daily_budget_usd = 10.0`):** Nếu tổng chi phí toàn hệ thống (`self._global_cost`) chạm ngưỡng, `check_budget` ghi log `CRITICAL` và trả `503 Service Unavailable` để bảo vệ ví toàn hệ thống.
  2. **Per-user daily budget (`daily_budget_usd = 1.0`):** Tự động reset theo ngày (`record.day != today` trong `_get_record`). Nếu user dùng đạt ngưỡng, `check_budget` trả `402 Payment Required` kèm chi tiết `used_usd`, `budget_usd`, `resets_at`. Khi đạt `warn_at_pct = 0.8` (80%), hệ thống ghi log `WARNING`.
- **Luồng thực thi trong `/ask` (`04-api-gateway/production/app.py` dòng 145–153):** Luôn gọi `cost_guard.check_budget(username)` **trước** khi gọi LLM để chặn sớm request vượt ngân sách, sau khi có kết quả mới tính token và gọi `cost_guard.record_usage(...)`. Trong môi trường production nhiều instance (như Part 6), bộ đếm này phải lưu trong Redis (`INCRBYFLOAT` + key theo ngày/tháng) thay vì `_records` trong RAM.

---

## Part 5: Scaling & Reliability (`05-scaling-reliability/`)

### Exercise 5.1: Liveness (`/health`) vs Readiness (`/ready`) (`05-scaling-reliability/develop/app.py`)

- **Liveness probe (`GET /health`):** Trả lời câu hỏi *"Process/container còn sống không?"*. Chỉ kiểm tra trạng thái nội bộ nhẹ (process chạy, uptime, memory) và luôn trả `200 OK` khi process không bị treo. Nếu fail hoặc timeout, orchestrator sẽ **restart container**. Không nên gắn check Redis/DB vào `/health` vì nếu Redis mất tạm thời mà restart đồng loạt các container agent thì hệ thống càng sập nặng hơn (cascading restart).
- **Readiness probe (`GET /ready`):** Trả lời câu hỏi *"Instance đã sẵn sàng nhận traffic chưa?"*. Kiểm tra `_is_ready` và kết nối dependencies (Redis, DB). Trả `503 Service Unavailable` khi app đang khởi động, đang tắt (`_is_ready = False`), hoặc mất kết nối Redis để Load Balancer tạm thời **ngừng route traffic mới** vào instance đó mà không kill container.

### Exercise 5.2: Graceful Shutdown (`05-scaling-reliability/develop/app.py`)

- Khi container dừng (deploy mới hoặc scale down), Docker/Kubernetes gửi tín hiệu **`SIGTERM`** (khác `SIGKILL` ở chỗ ứng dụng có thể bắt và xử lý được).
- Cơ chế trong `develop/app.py`:
  1. Middleware `track_requests` đếm số `_in_flight_requests` đang xử lý.
  2. `uvicorn` nhận `SIGTERM` (cấu hình `timeout_graceful_shutdown=30`), ngừng nhận kết nối mới và kích hoạt phần shutdown của `lifespan`.
  3. `lifespan` đặt `_is_ready = False` (để `/ready` trả `503` cho Load Balancer ngừng gửi request mới) và vòng lặp chờ `_in_flight_requests == 0` (tối đa 30s) rồi mới đóng kết nối và thoát sạch với exit code `0`.

### Exercise 5.3: Stateless Design (`05-scaling-reliability/production/app.py`)

- **Vấn đề của Stateful (lưu trong RAM):** Khi scale lên nhiều instance (`agent=3`) sau Nginx Load Balancer, request #1 có thể vào `agent-1` (lưu `session` vào RAM của `agent-1`), nhưng request #2 theo round-robin lại vào `agent-2` không có session đó → mất ngữ cảnh hoặc lỗi 404. Tương tự nếu 1 instance bị kill/restart, toàn bộ session trong RAM biến mất.
- **Giải pháp Stateless với Redis:** Mọi session và lịch sử hội thoại được serialize JSON và lưu vào Redis (`_redis.setex(f"session:{session_id}", ttl_seconds, serialized)` và `_redis.get(...)`). Nhờ vậy bất kỳ instance nào cũng đọc/ghi được chung một trạng thái, dễ dàng scale ngang hoặc thay thế instance khi lỗi.

### Exercise 5.4 & 5.5: Chạy Load Balanced Stack (`--scale agent=3`) & `test_stateless.py`

Chạy stack trong `05-scaling-reliability/production/` (mở cổng **8080**, endpoint **`POST /chat`**):
```bash
docker compose -p k5-day14-scaling up -d --build --scale agent=3
python test_stateless.py
```

**Kết quả `test_stateless.py` thực tế:**
```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: abdcbedc-49ca-4c84-96db-73f290886c13

Request 1: [instance-d681ef]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-3aad4a]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-d681ef]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 4: [instance-ebbf22]
  Q: How does load balancing work?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 5: [instance-3aad4a]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-3aad4a', 'instance-d681ef', 'instance-ebbf22'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: How does load balancing work?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

**Giải thích tại sao thành công qua cả 3 instance:**
1. **Nginx Load Balancer (`nginx.conf`):** Sử dụng Docker DNS `resolver 127.0.0.11` và `upstream agent_cluster { server agent:8000; }` nên các request liên tiếp được điều phối sang cả 3 instance khác nhau (`instance-d681ef`, `instance-3aad4a`, `instance-ebbf22`).
2. **Shared Redis State (`app.py`):** Mọi instance đều kết nối chung tới `redis://redis:6379/0`. Khi xử lý `POST /chat`, từng instance đọc/cập nhật key `session:<session_id>` (kèm TTL 3600s) trong Redis thay vì RAM cục bộ, nên dù request phân tán qua 3 container khác nhau thì `GET /chat/{session_id}/history` vẫn thu đủ **10 messages (5 turns)** liên tục.

*(Đã chạy `docker compose -p k5-day14-scaling down -v` và xóa file tạm `.env.local` để giải phóng cổng 8080.)*

---

## Part 6: Final Project — Checklist Deliverable (`06-lab-complete/`)

Chạy `python check_production_ready.py` trong container Linux (`os.name == "posix"`) — đạt **43/43 checks passed (`PASS 12/12`)**, image size cuối **56 MB** (`< 500 MB`), `docker stop` exit code `0` trong `0.7s`:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI log

- **Công cụ sử dụng:** Antigravity swarm (`parts1to5-runner`, `part6-builder`, `part7-bench`, `deployer`, `verifier`).
- **Đã hỏi / nhờ hỗ trợ gì:** Đọc và đối chiếu mã nguồn Parts 1–5 (`01-localhost-vs-production/`, `02-docker/`, `03-cloud-deployment/`, `04-api-gateway/`, `05-scaling-reliability/`), chạy các kịch bản kiểm thử local/Docker và tổng hợp câu trả lời vào `MISSION_ANSWERS.md`.
- **Đã tự kiểm tra và xác nhận thế nào:** Toàn bộ output HTTP (`200`, `401`, `429`), tham chiếu tên file/dòng code, kích thước Docker image, kết quả `test_stateless.py` đều được trích trực tiếp từ lần chạy thực tế trên máy và đối chiếu với mã nguồn hiện tại; kiểm tra che toàn bộ JWT token và xóa file `.env.local` tạm sau khi test.
