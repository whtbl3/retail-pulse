## Thay đổi gì

<!-- Trước: ... / Sau: ... (người đọc thấy gì khác) -->

## Vì sao

<!-- Link spec, issue hoặc specs/NNN-ten/ nếu có -->

## Definition of Done (Project-Spec §16)

- [ ] Hành vi khớp `docs/Project-Spec.md` và kiến trúc hiện có
- [ ] Có test cho trường hợp bình thường và các lỗi quan trọng
- [ ] `make check` xanh (ruff + pytest); đổi dbt thì `make dbt-parse` chạy được
- [ ] Lệnh và cấu hình mới đã ghi vào tài liệu (`docs/phases/`, `docs/design/`, `make help`)
- [ ] Không commit bí mật hay file runtime (`.env`, key, `dbt/target/`...)
- [ ] Đổi một quyết định Final thì đã cập nhật decision log (§17) trong cùng PR

## Đã kiểm tra thế nào

<!-- Lệnh đã chạy và kết quả -->
