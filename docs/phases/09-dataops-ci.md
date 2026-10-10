# Phase 9 — CI/CD: GitHub Actions và slim CI cho dbt

Mục tiêu: mỗi pull request (PR) tự kiểm tra thay đổi dbt mà **không đụng dữ liệu thật** và **không build lại
toàn bộ**. Khớp khối "GitHub CI" trong [README gốc](../../README.md).

## Vì sao cần

Bạn sửa `dim_payment_method` rồi push thẳng lên `main`. Lúc 23:00 Dagster chạy, model sai logic nhưng không báo
đỏ, chỉ cho ra số sai. Sáng hôm sau dashboard lệch. CI chặn lỗi đó **trước khi** nó vào `main`.

- **CI:** máy tự kiểm tra mỗi thay đổi trước khi nhập vào `main` (như bếp thử món trước khi lên thực đơn).
- **CD:** tự đưa bản đã kiểm tra lên nơi chạy thật. Dự án này **mới có CI**; deploy là `git pull` rồi khởi động
  lại Dagster bằng tay.

> **Đọc thêm:** [Continuous Integration (Martin Fowler)](https://martinfowler.com/articles/continuousIntegration.html), bài
> kinh điển giải thích CI là gì và vì sao mọi người nên nhập code vào nhánh chính thường xuyên.

Dữ liệu khác code thường ở ba điểm, và thiết kế bên dưới trả lời từng điểm:
- Lỗi chỉ làm số sai chứ không làm chương trình chết, nên CI phải chạy cả `dbt test`.
- Test cần dữ liệu thật nhưng không được phá nó, nên có database CI riêng, chỉ đọc bản thật.
- Build toàn bộ mỗi PR tốn credit Snowflake, nên dùng slim CI.

## Slim CI chạy thế nào

dbt so `manifest.json` của PR với manifest của bản thật để biết model nào đổi, rồi chỉ build phần đó:

```bash
dbt build --select state:modified+ --defer --state <thư mục chứa manifest của bản thật>
```

> **Đọc thêm (tài liệu dbt):** [Best practices for workflows](https://docs.getdbt.com/best-practices/best-practice-workflows)
> (mục chạy chỉ model đã đổi, tức slim CI), [Node selector methods](https://docs.getdbt.com/reference/node-selection/methods)
> (`state:modified` hoạt động thế nào) và [Defer](https://docs.getdbt.com/reference/node-selection/defer)
> (`--defer` và `--state`).

Ví dụ PR số 7 sửa `dim_payment_method`:
- **Được build:** `dim_payment_method`, `fct_sales` (dùng dimension này) và 30 test của chúng. Ghi vào
  `RETAIL_PULSE_CI.PR_7_MARTS`, không đụng bản thật.

  | | Máy bạn | CI của PR 7 |
  |---|---|---|
  | `fct_sales` | `RETAIL_PULSE.MARTS.fct_sales` | `RETAIL_PULSE_CI.PR_7_MARTS.fct_sales` |

- **Không build:** 6 dimension còn lại, toàn bộ staging và intermediate. Nhờ `--defer`, `ref()` tới chúng trỏ về
  bản thật (`RETAIL_PULSE.marts.dim_product`...). Vì vậy user CI phải có quyền **đọc** schema thật.
- **Dọn dẹp:** bước cuối xóa schema `PR_7_*`. PR số 8 chạy song song dùng `PR_8_*`, hai PR không đè nhau.
  Tên schema theo PR do macro `generate_schema_name` quyết định; xem [Custom schemas](https://docs.getdbt.com/docs/build/custom-schemas).

Danh sách trên lấy từ `dbt ls --select state:modified+` chạy ở máy với đúng thay đổi của PR thử; log chi tiết của
GitHub cần đăng nhập nên không đọc được từ ngoài.

## Thiết lập (một lần, đúng thứ tự)

**1. Chuẩn bị tài khoản quản trị.** Cần user `ACCOUNTADMIN` và ba biến trong `.env`: `SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_ADMIN_USER`, `SNOWFLAKE_ADMIN_PASSWORD`.
*Vì sao:* chỉ `ACCOUNTADMIN` tạo được database, role và user. Thiếu biến thì lệnh dừng, chưa tạo gì trên Snowflake.

**2. Tạo môi trường CI trên Snowflake.**
```bash
make snowflake-init-dry   # xem trước, không kết nối
make snowflake-init       # chạy thật; chạy lại nhiều lần vẫn an toàn
```
Tạo ra: database `RETAIL_PULSE_CI` (nơi CI ghi), warehouse `RETAIL_CI_WH` với resource monitor `RETAIL_CI_RM`
(trần 2 credit/tháng), role `CI_RUNNER` (ghi trong database CI, chỉ đọc bản thật), user `GITHUB_CI` (đăng nhập
bằng key pair, file `.snowflake/github_ci.p8`).
*Vì sao:* tách riêng để CI lỗi không thể đè dữ liệu thật hay đốt hết credit.
*Kiểm tra:* `DESC USER GITHUB_CI;` có `RSA_PUBLIC_KEY_FP` dạng `SHA256:...`.
> **Đọc thêm (tài liệu Snowflake):** [Key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth)
> (đăng nhập bằng key thay mật khẩu) và [Resource monitors](https://docs.snowflake.com/en/user-guide/resource-monitors)
> (đặt trần credit, tự dừng warehouse).

**3. Thêm hai secret vào GitHub.** Settings, Secrets and variables, Actions, New **repository** secret:
`SNOWFLAKE_ACCOUNT` (giống `.env`) và `CI_PRIVATE_KEY` (toàn bộ nội dung `.snowflake/github_ci.p8`, gồm dòng
BEGIN/END).
*Vì sao:* workflow đọc hai secret này để đăng nhập. Phải là repository secret vì workflow không khai `environment:`;
đặt vào Environment thì giá trị rỗng. Không dán key vào chat hay commit.
> **Đọc thêm:** [Using secrets in GitHub Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

**4. Chạy workflow `Prod manifest`.** Tab Actions, bấm `manifest.yml` ở cột trái, **Run workflow**, chọn `main`.
*Vì sao:* tạo manifest bản thật (artifact `prod-manifest`) để PR so sánh. Thiếu thì PR đầu tiên build toàn bộ.
Xanh ở bước này chưa chứng minh đăng nhập đúng, vì `dbt parse` không kết nối Snowflake.

**5. Mở một PR thử.** Tạo nhánh, thêm một dòng chú thích vào một model, mở PR; `lint` và `dbt-slim-ci` phải xanh.
Xong thì đóng PR và xóa nhánh, không merge.
*Vì sao:* đây là lần đầu CI thật sự đăng nhập Snowflake; thử trước để lỗi cấu hình không rơi vào PR thật.

**6. Bật bảo vệ `main`** theo bảng dưới.
*Vì sao để sau cùng:* ô chọn check bắt buộc chỉ liệt kê check đã chạy, và rule sẽ chặn việc đẩy workflow lên `main`.

## Cài đặt GitHub

| Ở đâu | Làm gì | Vì sao |
|---|---|---|
| Settings, General, Pull Requests | Chỉ bật **Squash merging** (mặc định lấy tiêu đề PR); bật **Automatically delete head branches** | Mỗi PR thành một commit gọn; merge xong nhánh tự xóa |
| Settings, Actions, General | **Require approval for all external contributors** | Repo public, ai cũng fork và mở PR được; người lạ không tự chạy workflow |
| Cùng chỗ | Workflow permissions: **Read repository contents**; để trống "Allow GitHub Actions to create and approve pull requests" | Workflow chỉ đọc; bot không tự duyệt PR |
| Settings, Rules, Rulesets | Tạo ruleset `protect-main`: **Active**, áp cho default branch, **bypass để trống** | Chủ repo cũng phải đi qua PR |
| Trong ruleset | **Restrict deletions** và **Block force pushes** | Không xóa nhầm hoặc ghi đè lịch sử `main` |
| Trong ruleset | **Require a pull request before merging** (approvals = 0; làm nhóm thì 1) | Không thì vẫn push thẳng được và CI vô dụng |
| Trong ruleset | **Require status checks to pass**: `lint`, `dbt-slim-ci` | CI đỏ thì không merge được |

Secret không được truyền cho PR từ fork (chủ ý): nếu truyền, người ngoài chỉ cần sửa workflow trong fork để in key
ra log. `ci.yml` không có bộ lọc `paths` nên hai check luôn chạy; nếu có, PR không đụng đường dẫn đó sẽ không có
check và bị treo chờ.

> **Đọc thêm (tài liệu GitHub):** [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
> và [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
> (từng rule ở bảng trên), [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)
> (vì sao phải cẩn thận với PR từ fork) và [Pull request merges](https://docs.github.com/en/pull-requests/reference/pull-request-merges)
> (squash merge).

## Làm việc hằng ngày (trunk-based)

Một nhánh chính `main`; mỗi việc một nhánh ngắn (vài giờ đến vài ngày), PR nhỏ, CI xanh thì merge. Không dùng
GitFlow (`develop`, `release`): nặng nề, chỉ hợp khi phát hành theo chu kỳ.

> **Đọc thêm:** [Trunk Based Development](https://trunkbaseddevelopment.com/) và riêng phần
> [Short-lived feature branches](https://trunkbaseddevelopment.com/short-lived-feature-branches/); với người đã quen
> GitHub thì xem [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow).

```bash
git switch main && git pull
git switch -c fix/ten-ngan
# sửa, rồi:
git add -A && git commit -m "..."
git push -u origin fix/ten-ngan     # git in link mở PR
```
Mở PR, đợi hai check xanh, bấm **Squash and merge**. Sau đó `git switch main && git pull && git fetch --prune`,
và `git branch -D <nhánh>` (squash làm Git tưởng nhánh chưa merge).

## Các file

| File | Việc |
|---|---|
| `.github/workflows/ci.yml` | Mỗi PR: `ruff` + slim CI dbt + dọn schema |
| `.github/workflows/manifest.yml` | Mỗi lần merge đổi `dbt/**`: `dbt parse --target prod`, lưu artifact `prod-manifest` |
| `dbt/ci/profiles.yml` | Profile CI (target `ci`, `prod`); chỉ dùng `env_var()` nên được commit |
| `dbt/macros/generate_schema_name.sql` | Target `ci` thì thêm tiền tố `PR_<số>_` |
| `dbt/macros/drop_ci_schemas.sql` | Xóa schema của PR; từ chối chạy nếu target không phải `ci` |
| `infras/snowflake/init.sql` | Phần CI ở cuối file, chạy cùng `make snowflake-init` |

## Lưu ý

- **Manifest lệch bản thật:** manifest sinh khi merge vào `main`, còn dữ liệu thật do Dagster build. Merge xong mà
  chưa chạy `full_pipeline` thì PR kế tiếp `--defer` đọc bảng thật còn cũ. Dự án một người chấp nhận được.
- **`fct_sales` incremental:** schema CI mới chưa có bảng nên lần build đầu chạy đầy đủ (~270 nghìn dòng, nhẹ).
- **Chưa ghim SHA cho action.** Mỗi lần chạy GitHub báo `checkout@v4` và `setup-uv@v5` còn dùng Node.js 20, và
  `ubuntu-latest` chuyển sang Ubuntu 26 từ 19/10/2026. Không làm CI đỏ; nếu hỏng sau ngày đó, thử `ubuntu-24.04`.
- **Chưa có `pytest` và `sqlfluff` trong CI:** cả hai cần manifest hoặc kết nối dbt. Thêm khi cần.

## Đã chạy thật

`make snowflake-init`, `Prod manifest` và PR thử đều chạy xanh trên GitHub Actions và Snowflake (dbt build 17 giây,
dọn schema 5 giây). Hai lỗi gặp và đã sửa:
- `runner.temp` không dùng được ở `env` của job nên GitHub báo "Invalid workflow file". Sửa bằng `$RUNNER_TEMP`
  trong step ghi key và đặt biến qua `$GITHUB_ENV`. Chạy `actionlint` trước khi push workflow.
- `.gitignore` chặn mọi `profiles.yml` nên `dbt/ci/profiles.yml` suýt không lên GitHub. Thêm
  `!dbt/ci/profiles.yml`.
