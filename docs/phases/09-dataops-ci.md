# Phase 9 — DataOps: GitHub Actions và slim CI cho dbt

Mục tiêu: mỗi pull request tự kiểm tra thay đổi dbt mà **không đụng dữ liệu thật** và **không build lại
toàn bộ**. Khớp khối "GitHub CI" trong [README gốc](../../README.md).

## Bối cảnh: vì sao cần CI/CD

Hình dung chuyện này. Bạn sửa `dim_product` rồi push thẳng lên `main`. Hơn 23:00 Dagster tự chạy. Model có lỗi
logic nhưng không báo đỏ, chỉ cho ra số sai. Sáng hôm sau dashboard hiện doanh thu lệch và bạn phải lần ngược xem
thay đổi nào gây ra. Nếu có một bước kiểm tra **trước khi** thay đổi vào `main`, lỗi đã bị chặn từ đầu.

- **CI (Continuous Integration, tích hợp liên tục):** mỗi thay đổi được máy tự kiểm tra trước khi nhập vào
  `main`. Giống nhà hàng thử món mới ở bếp thử rồi mới đưa lên thực đơn, thay vì thử trên khách.
- **CD (Continuous Delivery, giao liên tục):** tự đưa bản đã kiểm tra lên nơi chạy thật. Dự án này **mới có CI,
  chưa có CD**: sau khi merge, "deploy" là `git pull` rồi khởi động lại Dagster bằng tay.

**Vì sao dữ liệu khó hơn code thường**, và đó cũng là lý do bảng thiết kế bên dưới có những dòng như vậy:
1. Lỗi dữ liệu thường **không làm chương trình chết**, chỉ làm số sai. Nên CI phải chạy cả `dbt test`, không chỉ
   kiểm tra cú pháp.
2. Kiểm tra dữ liệu cần **dữ liệu thật** để chạy, mà không được phá nó. Nên cần database CI riêng và user chỉ có
   quyền đọc bản thật.
3. Build lại toàn bộ mỗi PR vừa chậm vừa tốn credit Snowflake. Nên có slim CI, chỉ build phần bị đổi.

Nối với kiến thức cũ: `dbt test` bạn đã viết ở phase 5 chính là "bài kiểm tra"; CI chỉ là cách tự động chạy chúng
đúng lúc, trên mọi thay đổi. `ref()` tạo DAG nên dbt biết sửa model nào thì phần nào bị ảnh hưởng.

**Khi nào KHÔNG cần:** dự án thử nghiệm một người, không có ai dùng dashboard, thì `make dbt-build` ở máy là đủ.
Dự án này làm CI vì là portfolio (cần thể hiện quy trình đúng) và vì repo public.

## Slim CI là gì
Build lại toàn bộ dbt cho mỗi PR thì chậm và tốn credit. Slim CI chỉ build **model bị sửa và mọi model phụ
thuộc vào chúng** (`state:modified+`); model không đổi thì đọc từ bản thật (`--defer`).

```bash
dbt build --select state:modified+ --defer --state <thư mục chứa manifest.json của bản thật>
```

`manifest.json` là bản chụp DAG của một lần parse. dbt so manifest của PR với manifest của bản thật để biết
model nào đổi. Nối với kiến thức cũ: `ref()` tạo DAG, nên dbt biết "sửa `dim_product` thì `fct_sales` bị ảnh
hưởng".

## Thiết kế (an toàn trước, rẻ sau)

| Vấn đề | Cách xử lý |
|---|---|
| CI không được ghi đè dữ liệu thật | Database riêng `RETAIL_PULSE_CI`; user `GITHUB_CI` chỉ có quyền **đọc** `RETAIL_PULSE` |
| Nhiều PR chạy song song | Schema theo PR: `PR_<số>_STAGING`, `PR_<số>_MARTS`... (macro `generate_schema_name` chỉ đổi khi target là `ci`, dev/prod giữ nguyên) |
| CI sinh rác | Bước cuối (`if: always()`) chạy `dbt run-operation drop_ci_schemas`; macro **từ chối chạy** nếu target không phải `ci` |
| CI chạy sai ăn hết credit | Warehouse riêng `RETAIL_CI_WH` + resource monitor `RETAIL_CI_RM` (2 credit/tháng, tự suspend ở 100%) |
| Lộ bí mật | Xác thực key pair, private key chỉ nằm trong GitHub Secrets, ghi ra file tạm quyền 600; secret truyền qua biến môi trường, không nhúng vào lệnh shell |
| Quyền workflow | `permissions` tối thiểu (`contents: read`, `actions: read`); PR từ fork không nhận secret nên không chạy được phần Snowflake (chủ ý) |
| Hai PR đẩy liên tiếp | `concurrency` hủy lần chạy cũ của cùng PR |

## Các file
| File | Việc |
|---|---|
| `.github/workflows/ci.yml` | Mỗi PR: lint (`ruff`) + slim CI dbt + dọn schema |
| `.github/workflows/manifest.yml` | Mỗi lần merge vào `main` (có đổi `dbt/`): `dbt parse --target prod` rồi lưu `manifest.json` làm artifact `prod-manifest` |
| `dbt/ci/profiles.yml` | Profile cho CI (target `ci` và `prod`), chỉ dùng biến môi trường, được phép commit |
| `dbt/macros/generate_schema_name.sql` | Thêm nhánh `ci` (tiền tố PR) |
| `dbt/macros/drop_ci_schemas.sql` | Xóa schema của PR |
| `infras/snowflake/init.sql` | (phần CI ở cuối file) tạo database/warehouse/role/user cho CI; chạy cùng `make snowflake-init` |

Luồng một PR: lấy manifest mới nhất của `main` (nếu chưa có thì build toàn bộ) → `dbt build
--select state:modified+ --defer` vào `RETAIL_PULSE_CI.PR_<số>_*` → xóa schema.

## Thiết lập (làm một lần)

**1-2. Tạo key pair và môi trường CI trên Snowflake: một lệnh.** Phần CI nằm cuối `infras/snowflake/init.sql`
nên chạy cùng khởi tạo chung (xem [phase 3](03-ingestion-snowflake.md)):
```bash
make snowflake-init       # chạy lại an toàn; tự tạo .snowflake/github_ci.p8 và .pub nếu chưa có
```
Schema `STAGING`, `INTERMEDIATE`, `MARTS` được tạo bằng role `TRANSFORMER` (để dbt vẫn làm chủ sở hữu) rồi mới
cấp quyền đọc cho `CI_RUNNER`, nên chạy được ngay cả khi dbt chưa build lần nào.

**3. Thêm hai secret vào GitHub** (Settings, Secrets and variables, Actions):
- `SNOWFLAKE_ACCOUNT`: account identifier (như trong `.env`).
- `CI_PRIVATE_KEY`: toàn bộ nội dung `.snowflake/github_ci.p8`, gồm cả dòng BEGIN/END.

**4. Bật workflow:** push các file lên `main`. Workflow `Prod manifest` chạy và tạo artifact đầu tiên. Sau đó
mở một PR thử có sửa một model để xem slim CI chạy.

`.snowflake/` đã nằm trong `.gitignore`; dán xong vào GitHub thì giữ file ở máy hoặc xóa đều được.

## Quy trình làm việc: mọi thay đổi đi qua pull request

Có CI rồi thì phải bắt mọi thay đổi đi qua nó. Nếu vẫn push thẳng lên `main`, CI chỉ còn là đồ trang trí: nó
chạy sau khi lỗi đã nằm trong bản thật. Dự án theo **trunk-based development**: chỉ có một nhánh chính là
`main`; mỗi việc làm trên một nhánh ngắn (sống vài giờ đến vài ngày), mở PR nhỏ, CI xanh thì merge, không có
nhánh `develop` hay `release`.

### Việc hằng ngày
```bash
git switch main && git pull          # bắt đầu từ bản mới nhất
git switch -c fix/ten-ngan           # một việc, một nhánh
# sửa code, rồi:
git add -A && git commit -m "..."
git push -u origin fix/ten-ngan      # git in ra link để mở PR
```
Mở link, bấm **Create pull request**, đợi `lint` và `dbt-slim-ci` xanh, bấm **Squash and merge**. Nhánh tự xóa.

- *Vì sao nhánh ngắn:* nhánh sống càng lâu thì càng lệch khỏi `main`, lúc merge càng dễ xung đột và càng khó biết
  lỗi do ai. Bỏ qua thì PR to dần, khó review, CI chậm và dễ hỏng vì lý do không liên quan.
- *Vì sao squash:* mỗi PR thành đúng một commit trên `main`, lịch sử đọc như một danh sách việc đã xong. Bỏ qua thì
  `main` đầy commit "sửa lỗi chính tả", "thử lại" khiến khó truy ra thay đổi nào gây lỗi.

### Cài đặt GitHub (làm một lần, trên giao diện web)

**A. Settings, General, mục Pull Requests**

| Làm gì | Vì sao | Nếu bỏ qua |
|---|---|---|
| Chỉ bật **Allow squash merging** (tắt merge commit và rebase), chọn "Default to pull request title" | Mỗi PR thành một commit gọn | Lịch sử lẫn lộn ba kiểu merge, khó đọc |
| Bật **Automatically delete head branches** | Merge xong GitHub tự xóa nhánh | Nhánh cũ chất đống, mỗi lần chọn nhánh phải lọc qua rác |

**B. Settings, Actions, General** (quan trọng vì repo public)

| Làm gì | Vì sao | Nếu bỏ qua |
|---|---|---|
| **Require approval for all external contributors** | Repo public thì ai cũng fork và mở PR được; bước này bắt họ chờ bạn duyệt trước khi workflow chạy | Người lạ có thể kích hoạt workflow, tốn phút chạy Actions và thử lách vào quy trình của bạn |
| **Workflow permissions: Read repository contents** | Workflow chỉ được đọc code, không được ghi | Một workflow bị lợi dụng có thể sửa code hoặc tạo release |
| Để trống ô "Allow GitHub Actions to create and approve pull requests" | Không cho bot tự duyệt PR | Một workflow có thể tự tạo và tự duyệt PR, phá vòng kiểm soát |

Secret `CI_PRIVATE_KEY` và `SNOWFLAKE_ACCOUNT` không được truyền cho PR từ fork. Đây là chủ ý: nếu truyền, người
ngoài chỉ cần sửa workflow trong fork để in key ra log.

**C. Settings, Rules, Rulesets: tạo `protect-main` (Active, bypass để trống, áp cho default branch)**

| Rule | Vì sao | Nếu bỏ qua |
|---|---|---|
| **Restrict deletions** | Không ai xóa nhầm `main` | Một lệnh sai là mất nhánh chính |
| **Block force pushes** | Không ai ghi đè lịch sử `main` | Commit đã merge có thể biến mất, ảnh hưởng cả manifest dùng để so sánh |
| **Require a pull request before merging** (approvals = 0) | Mọi thay đổi bắt buộc qua PR, ngay cả của chủ repo | Vẫn push thẳng lên `main` được, CI không có tác dụng. Approvals để 0 vì dự án một người không có ai duyệt; nhóm nhiều người thì đặt 1 |
| **Require status checks to pass** với hai check `lint` và `dbt-slim-ci` | Biến CI từ "tham khảo" thành "cổng chặn": đỏ thì không merge được | CI đỏ vẫn merge được, lỗi vào thẳng bản thật |
| **Bypass list để trống** | Chủ repo cũng phải đi qua PR | Có đường tắt thì sớm muộn bị dùng "cho nhanh" lúc vội, đúng lúc dễ sai nhất |

Hai check phải đã chạy ít nhất một lần gần đây thì mới tìm thấy trong ô **Add checks**. Tên check lấy từ tên job
trong `ci.yml` (`lint`, `dbt-slim-ci`); `ci.yml` không có bộ lọc `paths` nên hai check này luôn chạy trên mọi PR. Nếu
có bộ lọc, PR không đụng đường dẫn đó sẽ không có check, và GitHub chờ mãi vì tưởng nó chưa xong.

### Khi nào KHÔNG cần theo đúng như vậy
- Dự án một người không cần người duyệt (approvals = 0), nhưng vẫn nên đi qua PR để CI chạy.
- Đừng dùng GitFlow (`develop`, `release`, `hotfix`) cho dự án dữ liệu này: nặng nề, chỉ hợp khi phát hành phiên
  bản theo chu kỳ.

## Lưu ý
- **Manifest lệch bản thật:** manifest được sinh khi merge vào `main`, trong khi dữ liệu thật do Dagster build
  trên máy bạn. Nếu merge xong mà chưa chạy `full_pipeline`, PR kế tiếp so với code mới nhưng `--defer` đọc
  bảng thật còn cũ. Với dự án một người thì chấp nhận được; nhiều người thì cần deploy tự động.
- **`fct_sales` là incremental:** schema CI mới chưa có bảng nên lần build đầu chạy đầy đủ (khoảng 270 nghìn
  dòng, nhẹ). Đây cũng là cách kiểm tra lần build từ đầu.
- **Action chưa ghim theo mã commit** (`actions/checkout@v4`...). Best practice mạnh hơn là ghim SHA và để
  Dependabot cập nhật.
- Chưa có `sqlfluff lint` và `pytest` trong CI: `pytest` cần manifest và profile dbt, `sqlfluff` với templater
  dbt cần kết nối. Thêm khi cần.

## Kiểm chứng
Đã kiểm tra ở máy: YAML của workflow và profile hợp lệ; `dbt parse --target ci` biên dịch macro mới và ghi
đúng `RETAIL_PULSE_CI.PR_7_marts`; target dev vẫn ghi `RETAIL_PULSE.marts` (không đổi hành vi);
toàn bộ test Python vẫn đạt (53).

**Đã chạy thật trên GitHub Actions và Snowflake:** `make snowflake-init` tạo xong môi trường CI (user `GITHUB_CI`
có key, database `RETAIL_PULSE_CI`, role `CI_RUNNER`); workflow `Prod manifest` xanh và lưu artifact; PR thử chỉ
thêm một dòng chú thích vào `dim_payment_method.sql` cho kết quả `lint` và `dbt-slim-ci` đều xanh (dbt build 17 giây,
dọn schema 5 giây).

**Hai lỗi gặp khi chạy thật (đã sửa):**
- `runner.temp` không dùng được ở `env` của job (chỉ dùng trong step) nên GitHub báo "Invalid workflow file". Sửa
  bằng `$RUNNER_TEMP` trong step ghi key, rồi đặt biến đường dẫn qua `$GITHUB_ENV`. Nên chạy `actionlint` trước khi
  push workflow.
- `.gitignore` chặn mọi `profiles.yml` nên `dbt/ci/profiles.yml` suýt không lên GitHub. Thêm
  `!dbt/ci/profiles.yml` (file này chỉ có `env_var()`, không có bí mật).
