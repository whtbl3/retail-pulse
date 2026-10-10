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

## Ví dụ: một PR chạy thì Snowflake có gì

Giả sử PR số 7 sửa `dim_payment_method`. Ba nhóm chữ trong tên là: database CI, schema theo PR, tên bảng.

| Model | Khi chạy ở máy bạn (dev) | Khi chạy trong CI của PR 7 |
|---|---|---|
| `stg_payment_method` | `RETAIL_PULSE.STAGING.stg_payment_method` | `RETAIL_PULSE_CI.PR_7_STAGING.stg_payment_method` |
| `int_product_scd2` | `RETAIL_PULSE.INTERMEDIATE.int_product_scd2` | `RETAIL_PULSE_CI.PR_7_INTERMEDIATE.int_product_scd2` |
| `dim_payment_method` | `RETAIL_PULSE.MARTS.dim_payment_method` | `RETAIL_PULSE_CI.PR_7_MARTS.dim_payment_method` |
| `fct_sales` | `RETAIL_PULSE.MARTS.fct_sales` | `RETAIL_PULSE_CI.PR_7_MARTS.fct_sales` |

(Tên lấy từ `dbt parse --target ci` với `CI_SCHEMA=PR_7`; Snowflake tự viết hoa khi lưu.)

Trong một lần chạy:
1. **Bị sửa và phía sau nó** (`dim_payment_method`, rồi `fct_sales` vì nó dùng dimension này) được build vào
   `RETAIL_PULSE_CI.PR_7_*`, kèm test của chúng. Đây là chỗ bạn thấy lỗi của PR, không đụng bản thật.
2. **Model không đổi** không được build lại. Nhờ `--defer`, mỗi lần model của PR gọi `ref()` tới chúng thì dbt
   trỏ sang bản thật, ví dụ `RETAIL_PULSE.MARTS.dim_product`. Đó là lý do user `GITHUB_CI` phải có quyền
   **đọc** các schema thật; thiếu quyền này thì bước build báo "does not exist or not authorized".
3. Bước cuối `drop_ci_schemas` xóa cả bốn schema `PR_7_*`. Bỏ qua bước này thì mỗi PR để lại một đống schema
   mồ côi trong `RETAIL_PULSE_CI`, tốn dung lượng và rối khi cần tìm.

**Đã tái hiện ở máy** (dbt dựng manifest từ `main`, rồi thêm đúng dòng chú thích như PR thử và chạy
`dbt ls --select state:modified+`): dbt chọn **2 model** (`dim_payment_method`, `fct_sales`) cùng **30 test** của
chúng. Sáu dimension còn lại (`dim_product`, `dim_employee`, `dim_store`, `dim_promotion`, `dim_date`, `dim_time`)
và toàn bộ staging, intermediate **không** được build mà đọc từ bản thật (ví dụ `RETAIL_PULSE.marts.dim_product`).
Các test `relationships` từ `fct_sales` tới những dimension đó vẫn chạy được nhờ `--defer`. Đây là tái hiện chứ
không phải log thật, vì log chi tiết của GitHub Actions bắt buộc đăng nhập mới xem được.

PR số 8 mở song song thì dùng `PR_8_*`, hai PR không đè nhau. Nếu mọi PR dùng chung một schema, PR này build có thể
xóa bảng mà PR kia đang test và cho kết quả đỏ vô lý.

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

## Thiết lập từ đầu: bắt đầu từ đâu và theo thứ tự nào

Làm **một lần**, theo đúng thứ tự dưới đây. Thứ tự quan trọng vì bước sau cần thứ do bước trước tạo ra.

| Bước | Việc | Làm ở đâu | Vì sao đứng ở vị trí này |
|---|---|---|---|
| 1 | Chuẩn bị tài khoản quản trị Snowflake | Máy của bạn (`.env`) | Tạo database, role, user cần quyền `ACCOUNTADMIN` |
| 2 | Tạo môi trường CI trên Snowflake | Máy của bạn (`make snowflake-init`) | Lệnh này sinh ra file key mà bước 3 cần dán lên GitHub |
| 3 | Thêm hai secret vào GitHub | Giao diện web GitHub | Workflow cần secret để đăng nhập Snowflake |
| 4 | Đẩy workflow lên `main`, chạy `Prod manifest` | GitHub | Tạo manifest "bản thật" đầu tiên để PR sau so sánh |
| 5 | Mở một PR thử | GitHub | Lần đầu CI thật sự kết nối Snowflake; thử trước khi người khác cần đến |
| 6 | Bật bảo vệ nhánh `main` | Giao diện web GitHub | Phải làm **sau cùng** (xem lý do ở cuối mục) |

### Bước 1. Chuẩn bị tài khoản quản trị Snowflake

Bạn cần một user có role `ACCOUNTADMIN` (không phải `DLT_LOADER` hay `DBT_TRANSFORMER`) và ba biến này trong
`.env` hoặc `export` trước khi chạy:

```bash
SNOWFLAKE_ACCOUNT=...          # account identifier, cùng giá trị dbt đang dùng
SNOWFLAKE_ADMIN_USER=...       # user ACCOUNTADMIN
SNOWFLAKE_ADMIN_PASSWORD=...   # mật khẩu của user đó (chỉ để ở máy, không commit)
```

- *Vì sao:* chỉ `ACCOUNTADMIN` mới tạo được resource monitor, database, role và user.
- *Nếu thiếu:* lệnh dừng với thông báo "Thiếu ..." và chưa tạo gì trên Snowflake. Có thể file key đã được sinh
  ở máy; cứ giữ lại, lần chạy sau sẽ dùng tiếp đúng cặp key đó.

### Bước 2. Tạo môi trường CI trên Snowflake (một lệnh)

Xem trước, không kết nối Snowflake, chỉ in các câu lệnh sẽ chạy:
```bash
make snowflake-init-dry
```
Chạy thật:
```bash
make snowflake-init
```
Lệnh đọc file `infras/snowflake/init.sql` (53 câu lệnh) và **chạy lại nhiều lần vẫn an toàn**: mọi câu đều là
`IF NOT EXISTS` hoặc `GRANT`, nên thứ đã có (warehouse, user của dlt và dbt) không bị đổi, miễn là bạn giữ nguyên các file key trong `.snowflake/`. Lần đầu nó cũng tự sinh cặp key
cho user CI tại `.snowflake/github_ci.p8` (private) và `.snowflake/github_ci.pub` (public).

Phần dành cho CI tạo ra những thứ sau, và mỗi thứ có lý do riêng:

| Tạo ra | Để làm gì | Nếu không có |
|---|---|---|
| Database `RETAIL_PULSE_CI` | Nơi CI ghi các bảng thử (`PR_<số>_*`) | CI phải ghi vào database thật và có thể đè lên dữ liệu thật |
| Warehouse `RETAIL_CI_WH` (XSMALL, tự tắt sau 60 giây) | Máy tính riêng cho CI | CI dùng chung `RETAIL_WH`, tranh tài nguyên với pipeline thật |
| Resource monitor `RETAIL_CI_RM` (2 credit mỗi tháng, tự dừng ở 100%) | Trần chi phí cho CI | Một workflow lặp vô hạn có thể đốt hết credit của cả tài khoản |
| Role `CI_RUNNER`: **ghi** trong `RETAIL_PULSE_CI`, chỉ **đọc** `RETAIL_PULSE` | Quyền vừa đủ cho CI | Quyền rộng hơn thì một lỗi trong CI có thể sửa hoặc xóa dữ liệu thật |
| User `GITHUB_CI` (dạng service, đăng nhập bằng key pair) | Tài khoản riêng của GitHub Actions | Phải dùng chung tài khoản người; mật khẩu nằm trong GitHub, lộ là mất quyền |
| Các schema `STAGING`, `INTERMEDIATE`, `MARTS` trong `RETAIL_PULSE` (tạo bằng role `TRANSFORMER`) | Để cấp quyền đọc cho CI ngay cả khi dbt chưa build lần nào | Câu `GRANT` báo lỗi vì schema chưa tồn tại |

Lý do các schema ở dòng cuối do `TRANSFORMER` tạo: nếu `ACCOUNTADMIN` tạo thì chính `ACCOUNTADMIN` là chủ sở hữu
và dbt không ghi bảng vào được.

**Kiểm tra bước này đã xong:** chạy trong Snowsight `DESC USER GITHUB_CI;`. Cột `RSA_PUBLIC_KEY_FP` phải có giá
trị dạng `SHA256:...`; ô trống nghĩa là key chưa được gắn và CI sẽ không đăng nhập được.

### Bước 3. Thêm hai secret vào GitHub

Vào repo, **Settings, Secrets and variables, Actions, New repository secret**. Chọn **Repository secrets**, không
phải Environment secrets.

| Tên (viết đúng, phân biệt hoa thường) | Giá trị |
|---|---|
| `SNOWFLAKE_ACCOUNT` | Giá trị `SNOWFLAKE_ACCOUNT` trong `.env` |
| `CI_PRIVATE_KEY` | Toàn bộ nội dung `.snowflake/github_ci.p8`, gồm cả hai dòng `BEGIN` và `END` |

- *Vì sao cần:* workflow đọc `${{ secrets.SNOWFLAKE_ACCOUNT }}` và `${{ secrets.CI_PRIVATE_KEY }}` để đăng nhập.
  Private key chỉ nằm ở máy bạn và trong GitHub Secrets, không bao giờ nằm trong repo.
- *Vì sao Repository mà không phải Environment:* workflow này không khai báo `environment:`, nên chỉ đọc được
  repository secret; đặt nhầm chỗ thì giá trị rỗng và lỗi đăng nhập rất khó đoán.
- *Nếu bỏ qua hoặc sai tên:* CI chạy đến bước dbt thì đỏ với lỗi thiếu account hoặc key.
- *An toàn:* mở file bằng editor rồi copy, không dán key vào chat hay commit. `.snowflake/` đã nằm trong `.gitignore`.

### Bước 4. Đẩy workflow lên `main` và chạy `Prod manifest`

Workflow `Prod manifest` tạo bản chụp `manifest.json` của bản thật để PR sau so sánh. Nó tự chạy khi có thay đổi
trong `dbt/**` được đẩy lên `main`. Muốn chạy tay: tab **Actions**, bấm vào **`manifest.yml`** ở cột trái (nút
**Run workflow** chỉ hiện ở trang của từng workflow, không hiện ở trang "All workflows"), chọn nhánh `main`.

- *Vì sao:* slim CI cần "bản thật trông thế nào" để biết PR đã đổi model nào.
- *Nếu bỏ qua:* PR đầu tiên vẫn chạy được nhưng sẽ build toàn bộ (chậm, tốn credit), và từ đó mới có manifest.
- *Lưu ý:* lần này xanh **chưa chứng minh** đăng nhập Snowflake đúng, vì `dbt parse` không kết nối. Chuyện đó
  được kiểm tra ở bước 5.

### Bước 5. Mở một PR thử

Tạo nhánh, thêm một dòng chú thích vào một model (ví dụ `dim_payment_method.sql`), đẩy lên và mở PR. Kỳ vọng:
cả `lint` lẫn `dbt-slim-ci` xanh. Xong thì **đóng PR và xóa nhánh, không merge**.

- *Vì sao:* đây là lần đầu CI thật sự đăng nhập Snowflake bằng `GITHUB_CI`, tạo schema `PR_<số>_*` và dọn nó.
- *Nếu bỏ qua:* lỗi cấu hình đầu tiên bạn thấy sẽ nằm trên một PR thật, vào lúc đang vội.

### Bước 6. Bật bảo vệ nhánh `main`

Làm theo mục [Cài đặt GitHub](#cài-đặt-github-làm-một-lần-trên-giao-diện-web) ở dưới.

- *Vì sao để sau cùng:* ô chọn check bắt buộc (`lint`, `dbt-slim-ci`) chỉ liệt kê những check đã chạy gần đây, nên
  phải có PR thử trước. Ngoài ra rule bảo vệ chặn push thẳng lên `main`, mà bước 4 cần đẩy workflow lên `main`.
- *Nếu bật sớm:* không chọn được check bắt buộc, hoặc bị chặn khi đẩy workflow đầu tiên.

> Giao diện GitHub và Snowsight đôi khi đổi tên nút hoặc vị trí. Nếu thấy khác mô tả, chụp màn hình rồi đối chiếu
> với tên các mục ở trên, ý nghĩa vẫn giữ nguyên.

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
- **GitHub Actions báo hai thông báo ở mỗi lần chạy** (không làm CI đỏ): cảnh báo `actions/checkout@v4` và
  `astral-sh/setup-uv@v5` còn dùng Node.js 20 (đã bị chạy ép trên Node.js 24), và thông báo nhãn `ubuntu-latest`
  sẽ chuyển sang Ubuntu 26 từ 19/10/2026. Chưa cần sửa ngay; nếu CI bỗng hỏng sau ngày đó thì thử ghim
  `runs-on: ubuntu-24.04` trước.
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
