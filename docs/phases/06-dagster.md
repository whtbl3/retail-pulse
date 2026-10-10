# Phase 6 — Dagster (điều phối dlt, dbt và kiểm tra chất lượng)

Sau phase 5, cả chuỗi vẫn chạy bằng tay: `make ingest`, rồi `make dbt-build`, nhớ đúng thứ tự, nhớ chạy mỗi ngày.
Dagster gom lại thành một đồ thị: biết cái nào chạy trước, chạy theo lịch, dừng đúng chỗ khi có lỗi, và cho xem trạng thái
cùng lineage của từng bảng. Phạm vi theo [Project-Spec, mục 11](../Project-Spec.md#11-orchestration-specification).
Chưa làm: thử lại tự động, cảnh báo, sensor và triển khai lên máy chủ.

## Khái niệm

| Khái niệm | Là gì | Trong dự án |
|---|---|---|
| **Asset** | Một thứ dữ liệu được tạo ra (bảng RAW, model dbt), có phụ thuộc vào asset khác. Giống model của dbt nhưng mở rộng ra cả bước nạp dữ liệu | 10 asset RAW của dlt, 20 asset dbt |
| **Asset check** | Phép kiểm gắn vào một asset | Test dbt; kiểm tra Great Expectations trên RAW |
| **Job** | Nhóm asset được đặt tên để chạy cùng lúc, tự xếp thứ tự theo phụ thuộc | `full_pipeline`, `fct_sales_full_refresh` |
| **Schedule** | Đến giờ thì tự launch một job | Hằng ngày 23:00 cho `full_pipeline` |
| **Definitions** (`defs`) | Danh sách mọi asset, job, lịch mà Dagster biết | `definitions.py` |
| **Code location** | Gói code Dagster nạp vào | module `retail_pulse.orchestration.definitions`, khai báo ở `pyproject.toml` (`[tool.dagster]`) |
| **Daemon** | Tiến trình nền kích hoạt lịch | `make dagster` bật sẵn |

Đọc thêm: [Assets](https://docs.dagster.io/guides/build/assets), [Jobs](https://docs.dagster.io/guides/build/jobs),
[Schedules](https://docs.dagster.io/guides/automate/schedules).

## Các file

| File (`src/retail_pulse/orchestration/`) | Việc |
|---|---|
| `dlt_assets.py` | Mỗi bảng RAW là một asset (bước 1) |
| `dbt_assets.py` | Mỗi model dbt là một asset (bước 2) |
| `quality_checks.py` | Kiểm tra Great Expectations gắn vào asset RAW, chặn dbt khi fail ([phase 8](08-great-expectations.md)) |
| `jobs.py` | Hai job và lịch chạy (bước 4, 5) |
| `definitions.py` | Gom tất cả vào `Definitions` |

## Chạy

```bash
uv run dagster definitions validate -m retail_pulse.orchestration.definitions   # kỳ vọng: Validation successful
make dagster                                                                    # mở giao diện http://localhost:3000
```

**Manifest của dbt.** `@dbt_assets` đọc `dbt/target/manifest.json` ngay lúc nạp code. `dagster dev` tự sinh nó
(`prepare_if_dev`), nhưng `validate` và chạy ngoài chế độ dev thì không. *Nếu thiếu* (sau `make clean` hoặc trên máy mới):
lỗi `DagsterDbtManifestNotFoundError: .../manifest.json does not exist`. Cách xử lý: `make dbt-parse` trước.

**Lịch sử chạy.** Chưa đặt `DAGSTER_HOME` thì lịch sử chạy mất khi tắt Dagster. Đặt biến này (xem `.env.example`) ra một
thư mục cố định, ví dụ `.dagster_home/` (đã nằm trong `.gitignore`).

## Những điều cần nhớ từ các phase trước

- RAW là nơi duy nhất giữ lịch sử SCD2 của `product` và `employee`. Chuỗi điều phối **không bao giờ** được chạy dlt với
  `replace` hay `refresh="drop_sources"` lên hai bảng đó.
- `fct_sales` sửa dòng khóa `-2` bằng `--full-refresh` của riêng nó (job `fct_sales_full_refresh`), không đụng RAW.
- dbt chạy từ thư mục `dbt/` và cần `SNOWFLAKE_ACCOUNT`, `DBT_PRIVATE_KEY_PATH` ([phase 5](05-dbt.md)); Dagster nạp `.env`
  ở thư mục gốc, nên **chạy Dagster từ thư mục gốc repo**.

## Bước 1 — Asset dlt

```python
@dlt_assets(
    dlt_source=retail_source(),
    dlt_pipeline=retail_pipeline(),
    name="retail_raw", group_name="raw",
    dagster_dlt_translator=RetailDltTranslator(),
)
def retail_raw_assets(context, dlt_res: DagsterDltResource):
    yield from dlt_res.run(context=context)
```

- `@dlt_assets` biến mỗi **resource** của dlt (mỗi bảng) thành **một asset riêng**: 10 asset `raw/<tên bảng>`. Asset riêng thì
  Dagster hiện trạng thái, số dòng nạp, thời gian cho từng bảng, và mỗi model dbt nối được vào đúng bảng nó đọc.
- `retail_pipeline()` (trong `ingestion/pipelines.py`) là **một nơi duy nhất** định nghĩa pipeline dlt, dùng chung cho
  `make ingest` và Dagster nên hai nơi không lệch nhau.
- `RetailDltTranslator` đổi key asset thành `["raw", <tên bảng>]`, trùng key mặc định của source dbt
  `source('raw', 'store')`. Nhờ vậy ở bước 2, đồ thị nối liền từ RAW sang staging mà không cần cấu hình thêm.

## Bước 2 — Asset dbt, và nối lineage

```python
dbt_project = DbtProject(project_dir=Path(__file__).parents[3] / "dbt",
                         profiles_dir=os.environ.get("DBT_PROFILES_DIR", str(Path.home() / ".dbt")))
dbt_project.prepare_if_dev()

@dbt_assets(manifest=dbt_project.manifest_path)
def retail_dbt_assets(context, dbt: DbtCliResource):
    args = ["build"]
    if context.run.tags.get("full_refresh") == "true":   # xem bước 4
        args.append("--full-refresh")
    yield from dbt.cli(args, context=context).stream()
```

- `@dbt_assets` đọc manifest và biến **mỗi model dbt thành một asset** (20 model). Các `ref()` thành mũi tên phụ thuộc
  nên đồ thị Dagster giống DAG của dbt; thêm model mới thì asset tự xuất hiện.
- `dbt.cli(["build"])` gọi `dbt build` thật dưới nền (cả model lẫn test) và gắn kết quả vào từng asset. Test dbt hiện thành
  **asset check** của đúng model, nên thấy ngay model nào có test fail.
- Dagster dùng dbt-core trong `.venv`, không dùng bản dbt ở `~/.local/bin`.

**Lineage nối liền từ Postgres tới `fct_sales`**, kiểm chứng trên đồ thị (40 asset: 10 asset RAW, 20 asset dbt, và 10 asset
`sql_database_<bảng>` do dagster-dlt tự tạo, đại diện cho bảng nguồn ở Postgres):

| Asset | Phụ thuộc vào |
|---|---|
| `staging/stg_store` | `raw/store` |
| `staging/stg_sales_transaction_item` | `raw/sales_transaction_item`, `staging/stg_sales_transaction` |
| `marts/fct_sales` | 7 dimension (gồm `dim_date`, `dim_time`), hai model staging bán hàng |

Tên asset gồm schema và model (key dbt là `[schema, model]`), asset dlt là `raw/<bảng>`.

Ảnh chụp **Global asset lineage** sau khi Materialize (`make dagster`, mục Lineage, chọn asset, Materialize selected):

![Global asset lineage trong Dagster](../../assets/diagrams/dagster-asset-lineage.png)

Trong ảnh: cột trái chia asset theo nhóm `default` (asset dbt) và `raw` (asset dlt); mỗi nút hiện thời điểm materialize, số
asset check đã pass và nhãn công nghệ; panel phải (đang chọn `fct_sales`) hiện danh sách check, metadata
`materialization_type: incremental`, `table_name: RETAIL_PULSE.marts.fct_sales`.

## Kiểm tra chất lượng RAW chặn dbt

Phase 8 gắn một asset check `great_expectations` vào bốn asset RAW (`sales_transaction`, `sales_transaction_item`,
`product`, `employee`) với `blocking=True`: nếu một check fail thì asset dbt phía sau **không chạy**.

*Vì sao:* build dbt trên RAW bẩn vẫn "xanh" nhưng cho số sai. Chặn ngay ở cửa vào rẻ hơn tìm lỗi ở dashboard.
Đọc thêm: [Asset checks](https://docs.dagster.io/guides/test/asset-checks).

## Bước 3 — Job

| Job | Chọn asset | Dùng khi |
|---|---|---|
| `full_pipeline` | `retail_raw_assets` (dlt) và `retail_dbt_assets` (dbt) | Chạy thường kỳ: dlt nạp RAW, rồi `dbt build` toàn bộ (model và test) |
| `fct_sales_full_refresh` | chỉ `marts/fct_sales`, kèm tag `full_refresh=true` | Sửa dòng khóa `-2` của fact; không chạy dlt, không đụng RAW |

**Làm sao một asset dbt biết phải `--full-refresh`:** hai job dùng chung asset dbt, chỉ khác tag của lần chạy; asset đọc
tag đó (đoạn code ở bước 2). Dagster tự thêm `--select` theo asset được chọn, nên job full-refresh chạy
`dbt build --full-refresh --select retail_pulse.marts.fct_sales`. (Một lần chạy thử: 26/26 test pass, `fct_sales` vẫn
271.766 dòng.) Dùng một asset với hai kiểu chạy thay vì hai asset trùng khóa, vì Dagster không cho hai asset cùng khóa.

```bash
uv run dagster job execute -m retail_pulse.orchestration.definitions -j full_pipeline   # không cần mở giao diện
```
Hoặc trong giao diện: mục **Jobs**, chọn job, **Launchpad**, **Launch Run**.

**An toàn:** đặt nhầm tag `full_refresh=true` cho `full_pipeline` thì mọi model dbt bị dựng lại (vô hại nhưng chậm hơn).
RAW không bao giờ bị ghi đè vì cờ này chỉ ảnh hưởng dbt.

## Bước 4 — Lịch chạy

| Quyết định | Chọn | Lý do |
|---|---|---|
| Job được lên lịch | `full_pipeline` | dlt nạp RAW rồi dbt build |
| Tần suất | Mỗi ngày 23:00, múi giờ `Asia/Ho_Chi_Minh` | Cửa hàng mở 7h–22h, chạy sau giờ đóng cửa thì đã đủ đơn cả ngày; dashboard xem theo ngày không cần mới hơn |
| `fct_sales_full_refresh` | Không lên lịch, chạy tay | Chỉ cần khi có dòng khóa `-2`; dựng lại cả bảng tốn tài nguyên |
| dlt lỗi thì sao | Không build dbt | Mặc định của Dagster, không cần cấu hình thêm |

*Vì sao dlt lỗi thì dbt không chạy mà không cần code gì:* asset dbt phụ thuộc asset dlt trong đồ thị; asset phía trên fail
thì mọi asset phía dưới bị bỏ qua (skipped). Ngược lại nếu dlt xong mà dbt fail, RAW đã có dữ liệu mới, lần sau chỉ cần chạy
lại các asset dbt.

**Lịch chỉ chạy khi daemon chạy.** `make dagster` bật sẵn daemon, nên máy phải mở và tiến trình còn sống lúc 23:00. Production
thật dùng `dagster-daemon run` chạy nền (systemd hoặc Docker), không dùng `dagster dev`. Xem và bật tắt lịch ở mục
**Automation**; lịch đặt `default_status=RUNNING` nên tự bật. Thử ngay không cần đợi 23:00: vào lịch, **Test Schedule**, hoặc
launch `full_pipeline` bằng tay.

Đọc thêm: [Defining schedules](https://docs.dagster.io/guides/automate/schedules/defining-schedules),
[Dagster daemon](https://docs.dagster.io/guides/deploy/execution/dagster-daemon),
[Instance configuration](https://docs.dagster.io/guides/deploy/dagster-instance-configuration) (`DAGSTER_HOME`).

## Lỗi đã gặp

| Triệu chứng | Nguyên nhân | Cách sửa |
|---|---|---|
| `No module named 'orchestration'` | Import thiếu tên package | Dùng `from retail_pulse.orchestration....` |
| `connection to server ... port 5432 failed` khi `validate` lúc Postgres tắt | `sql_database(...)` đọc cấu trúc bảng từ Postgres **ngay lúc import** (reflection) | `sql_database(..., reflection_level="full", defer_table_reflect=True)` |
| `ValidationError for DbtCliResource ... does not contain a profiles.yml` | `profiles.yml` ở `~/.dbt/`, còn `DbtCliResource` chỉ tìm trong thư mục dự án dbt | Truyền `profiles_dir` (mặc định `~/.dbt`, ghi đè bằng `DBT_PROFILES_DIR`) |
| Cùng lỗi trên nhưng chỉ khi `dagster dev` | `prepare_if_dev()` tự tạo `DbtCliResource` riêng từ `DbtProject` | Đặt `profiles_dir` ngay ở `DbtProject`, không chỉ ở resource |
| `DagsterDbtManifestNotFoundError` | Chưa có `dbt/target/manifest.json` | `make dbt-parse` |

**Bài học từ lỗi Postgres:** code chạy lúc **import** phải rẻ và không phụ thuộc hệ thống ngoài; việc cần kết nối (đọc cấu
trúc, gọi API, truy vấn) nên hoãn đến lúc **thực thi**. Lỗi này hay gặp ở mọi framework nạp code trước rồi chạy sau
(Dagster, Airflow). `defer_table_reflect=True` an toàn: đã so sánh cột trích xuất có và không có tùy chọn này cho ba bảng
(`product`, `sales_transaction_item`, `promotion`), giống hệt nhau (ví dụ `unit_price`, `unit_cost` đều `decimal(12, 2)`), nên RAW
không đổi kiểu cột (nếu đổi, dlt tạo thêm cột `..._v_text` rất khó dọn). Kiểm tra bằng cách nạp code khi Postgres không
tồn tại: `PG_PORT=59999 uv run python -c "import retail_pulse.orchestration.dlt_assets"` phải chạy được.

**Bài học từ lỗi `profiles_dir`:** `dagster definitions validate` không bao phủ các bước chỉ chạy ở chế độ dev, nên cần thử
bằng `dagster dev` thật.

## Kiểm thử

`tests/test_orchestration.py`: mỗi bảng RAW có một asset; hai job tồn tại với đúng lựa chọn asset và tag (`full_pipeline`
chứa `raw/product` và `marts/fct_sales`, job full-refresh chỉ chọn `fct_sales`); lịch đúng cron và múi giờ.

## Còn có thể cải thiện

- 20 asset dbt đang nằm chung nhóm `default`; có thể chia nhóm theo tầng (`staging`, `intermediate`, `marts`) bằng cách ghi
  đè `get_group_name` của `DagsterDbtTranslator`.
- Đổi tên 10 asset `sql_database_<bảng>` cho gọn bằng `get_deps_asset_keys` của translator.
- Thử lại tự động, cảnh báo khi lỗi, sensor, và triển khai bằng `dagster-daemon` trên máy chủ.

Đọc thêm: [thư viện dagster-dbt](https://docs.dagster.io/api/libraries/dagster-dbt),
[thư viện dagster-dlt](https://docs.dagster.io/api/libraries/dagster-dlt).

Tiếp theo: [Phase 7 — Preset](07-preset.md).
