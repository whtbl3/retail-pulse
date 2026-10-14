# Làm việc với Claude Code trong repo này

Trang này giải thích bằng tiếng Việt các file cấu hình Claude Code (viết bằng tiếng Anh để người ngoài đọc được).
Đây là bước 1 của lộ trình phát triển theo SDLC: cho Claude "trí nhớ" về quy ước của repo và các rào chắn tự động,
trước khi làm những bước sau (cổng chất lượng trong CI, spec cho từng tính năng, review, vận hành).

## Các file và vai trò

| File | Là gì | Khi nào được dùng |
|---|---|---|
| `CLAUDE.md` | Hướng dẫn chung: lệnh, quy tắc dễ sai, quy trình, ngôn ngữ | Claude đọc ở đầu **mọi** phiên |
| `.claude/rules/dbt.md` | Quy ước riêng cho dbt | Chỉ nạp khi Claude đọc hoặc sửa file trong `dbt/` |
| `.claude/settings.json` | Quyền (allow, ask, deny) và hook | Claude Code áp dụng, Claude không tự bỏ qua được |
| `.claude/hooks/protect_secrets.py` | Hook chặn sửa file bí mật | Trước mỗi lần Claude sửa hoặc tạo file |
| `.claude/hooks/ruff_after_edit.py` | Hook format và lint file Python | Sau mỗi lần Claude sửa file `.py` |

Ranh giới quan trọng nhất: `CLAUDE.md` và rules là **lời khuyên**, Claude có thể quên hoặc hiểu sai.
Settings và hook là **luật**, chạy bằng code nên luôn đúng. Điều gì bắt buộc phải đúng mọi lúc thì cần có luật đứng sau.

> **Đọc thêm:** [How Claude remembers your project](https://code.claude.com/docs/en/memory) (CLAUDE.md và rules),
> [Steering Claude Code](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more)
> (khi nào dùng CLAUDE.md, rule, skill, hook hay subagent).

## `CLAUDE.md`: viết gì và vì sao

Nguyên tắc: mỗi dòng phải trả lời được câu "bỏ dòng này đi thì Claude có làm sai không?". File dài thì Claude bỏ qua
bớt quy tắc, nên giữ dưới 200 dòng và không chép lại những gì đọc code là biết.

- **Commands:** lệnh Claude không đoán được, ví dụ `make test` cần `make up` trước, thiếu Postgres thì test bị skip
  chứ không báo đỏ. *Nếu bỏ:* Claude tưởng test đã qua trong khi thật ra bị bỏ qua.
- **Rules that are easy to break:** các quyết định Final trong spec mà sai một lần là mất dữ liệu, ví dụ `make seed`
  xóa RAW trên Snowflake (nơi duy nhất giữ lịch sử SCD2). Dòng này có chữ IMPORTANT vì hậu quả không sửa lại được.
- **Workflow:** mọi thay đổi qua PR, khi nào dùng plan mode, đổi quyết định Final thì cập nhật decision log.
- **Language:** cấu hình cho Claude bằng tiếng Anh, comment và tài liệu phase bằng tiếng Việt như hiện tại.

`CLAUDE.md` không import cả `docs/Project-Spec.md` bằng `@` vì spec dài hơn 500 dòng: import sẽ nạp toàn bộ vào mọi
phiên và làm loãng hướng dẫn. Thay vào đó file chỉ đường tới spec để Claude đọc đúng mục khi cần.

## `.claude/rules/dbt.md`: quy tắc theo đường dẫn

Phần đầu file có `paths: ["dbt/**"]`, nên quy tắc chỉ nạp khi Claude làm việc với dbt. Sửa Python thì không tốn
chỗ trong context cho quy tắc dbt. Nội dung tóm tắt quy ước đã có trong spec §10 và
`docs/design/analytical-data-modeling.md`: tên model theo tầng, khóa `-1`/`-2`, cách dựng SCD2, `fct_sales` incremental.

## `.claude/settings.json`: quyền

Claude Code xét quyền theo thứ tự **deny, rồi ask, rồi allow**; luật khớp đầu tiên quyết định.

| Nhóm | Lệnh | Vì sao |
|---|---|---|
| allow | `make test`, `make lint`, `make dbt-parse`, `uv run pytest`, `uv run ruff`... | Lệnh an toàn chạy thường xuyên, không cần hỏi mỗi lần |
| ask | `make seed`, `reseed`, `db-reset`, `clean-raw`, `snowflake-init`, `dbt-full-refresh`, `git push ... main` | Xóa RAW, đổi Snowflake hoặc đẩy thẳng lên `main`: luôn hỏi bạn, kể cả khi đang ở auto mode |
| deny | `git push --force`, đọc `.env`, `.dlt/secrets.toml`, `dbt/profiles.yml`, `.snowflake/`, `*.p8`, `*.pem` | Không bao giờ cần; đọc file bí mật sẽ đưa mật khẩu vào cuộc hội thoại |

Luật Bash khớp theo chữ của lệnh. Claude Code tách lệnh ghép (`cd x && make seed`) nên luật vẫn bắt được, nhưng không
bắt được lệnh viết theo cách khác hẳn (ví dụ gọi qua `sh -c`). Vì vậy đây là rào chắn cho thao tác thường gặp, không
phải bức tường bảo mật tuyệt đối.

> **Đọc thêm:** [Configure permissions](https://code.claude.com/docs/en/permissions).

## Hai hook

Hook là script Claude Code tự chạy ở một thời điểm cố định. Claude Code gửi thông tin lệnh gọi tool (dạng JSON) vào
stdin của script. Script thoát mã `0` là cho qua; thoát mã `2` là báo lỗi, nội dung stderr được gửi lại cho Claude.

**`protect_secrets.py` (PreToolUse, trước khi sửa file).** Nếu file đích là `.env`, `secrets.toml`, `profiles.yml`,
`*.p8`, `*.pem` hoặc nằm trong `.snowflake/` thì chặn. File mẫu `*.example` và `dbt/ci/profiles.yml` (chỉ dùng biến
môi trường) vẫn sửa được.
*Vì sao cần dù đã có `.gitignore`:* `.gitignore` chỉ ngăn commit, không ngăn Claude ghi đè mật khẩu thật của bạn.

**`ruff_after_edit.py` (PostToolUse, sau khi sửa file).** Với file `.py`, chạy `ruff format` và `ruff check --fix`.
Còn lỗi không tự sửa được thì trả mã 2 để Claude thấy lỗi và sửa tiếp ngay, thay vì đợi CI báo đỏ.
Hook bỏ qua F401 (import chưa dùng) vì Claude thường thêm import ở lần sửa này rồi mới dùng ở lần sửa sau; xóa import
giữa chừng sẽ làm lần sửa sau hỏng. CI vẫn bắt F401.

Hai hook viết bằng Python thư viện chuẩn để chạy được trên mọi máy có `python3`, không cần cài `jq`.

> **Đọc thêm:** [Hooks reference](https://code.claude.com/docs/en/hooks) (các sự kiện và ý nghĩa mã thoát).

## Kiểm tra

Kiểm tra hook mà không cần mở Claude, bằng cách gửi JSON giả vào stdin:

```bash
echo '{"tool_input":{"file_path":".env"}}' | python3 .claude/hooks/protect_secrets.py; echo $?
# in ra "Blocked: ..." và 2
echo '{"tool_input":{"file_path":".env.example"}}' | python3 .claude/hooks/protect_secrets.py; echo $?
# in ra 0
```

Trong Claude Code: gõ `/context` để thấy `CLAUDE.md` đã được nạp, `/hooks` để xem hai hook, `/permissions` để xem
các luật allow, ask, deny.

## Thay đổi so với trước

Trước đây `.gitignore` bỏ qua cả thư mục `.claude`. Giờ chỉ bỏ qua phần riêng từng máy: `.claude/settings.local.json`,
`.claude/worktrees/` và `CLAUDE.local.md`. Nếu máy bạn có file khác trong `.claude/` (ví dụ skill cá nhân) thì chúng
sẽ hiện là untracked; chuyển chúng sang `~/.claude/` hoặc thêm vào `.gitignore`.

## Khi nào sửa các file này

- Claude lặp lại cùng một lỗi: thêm một dòng vào `CLAUDE.md` (hoặc vào rule nếu chỉ liên quan một vùng code).
- Một quy tắc trong `CLAUDE.md` bị bỏ qua dù đã viết rõ: chuyển thành hook hoặc luật deny/ask.
- Quy trình nhiều bước lặp lại (ví dụ thêm một model dbt): viết thành skill trong `.claude/skills/` (bước 3 của lộ trình).
- Sở thích cá nhân không áp cho cả repo: để ở `.claude/settings.local.json` hoặc `~/.claude/`, không sửa file dùng chung.
