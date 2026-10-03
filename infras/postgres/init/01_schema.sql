-- =========================================================
-- RetailPulse - OLTP schema (PostgreSQL 16, 3NF)
-- =========================================================
CREATE SCHEMA IF NOT EXISTS retail;
SET search_path TO retail;

-- ---------- Hàm tự cập nhật updated_at ----------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------- Bảng danh mục ----------
CREATE TABLE store (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_name      VARCHAR(100) NOT NULL UNIQUE,
    address         VARCHAR(255) NOT NULL,
    phone_number    VARCHAR(20),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE category (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_name   VARCHAR(100) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE brand (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    brand_name      VARCHAR(100) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE payment_method (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    method          VARCHAR(50) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Nhân viên (nguồn cho dim_employee SCD2) ----------
CREATE TABLE employee (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id        BIGINT NOT NULL REFERENCES store (id),
    first_name      VARCHAR(50) NOT NULL,
    last_name       VARCHAR(50) NOT NULL,
    date_of_birth   DATE NOT NULL,
    address         VARCHAR(255),
    phone_number    VARCHAR(20),
    start_date      DATE NOT NULL,
    end_date        DATE,
    salary          NUMERIC(12, 2) NOT NULL CHECK (salary >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_employee_dates CHECK (end_date IS NULL OR end_date >= start_date)
);

-- ---------- Sản phẩm (nguồn cho dim_product SCD2) ----------
CREATE TABLE product (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_sku     VARCHAR(32) NOT NULL UNIQUE,
    category_id     BIGINT NOT NULL REFERENCES category (id),
    brand_id        BIGINT NOT NULL REFERENCES brand (id),
    product_name    VARCHAR(200) NOT NULL,
    unit_price      NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    unit_cost       NUMERIC(12, 2) NOT NULL CHECK (unit_cost >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Khuyến mãi ----------
CREATE TABLE promotion (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type            VARCHAR(20) NOT NULL CHECK (type IN ('percentage', 'fixed_amount')),
    amount          NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_promotion_dates   CHECK (end_date >= start_date),
    CONSTRAINT chk_promotion_percent CHECK (type <> 'percentage' OR amount <= 100)
);

CREATE TABLE promotion_product (
    product_id      BIGINT NOT NULL REFERENCES product (id),
    promotion_id    BIGINT NOT NULL REFERENCES promotion (id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, promotion_id)
);

-- ---------- Giao dịch ----------
CREATE TABLE sales_transaction (
    transaction_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id            BIGINT NOT NULL REFERENCES store (id),          -- cửa hàng tại thời điểm bán
    employee_id         BIGINT NOT NULL REFERENCES employee (id),
    payment_method_id   BIGINT NOT NULL REFERENCES payment_method (id),
    transaction_ts      TIMESTAMPTZ NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('completed', 'cancelled', 'returned')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sales_transaction_item (
    transaction_id  BIGINT NOT NULL REFERENCES sales_transaction (transaction_id) ON DELETE CASCADE,
    line_number     SMALLINT NOT NULL CHECK (line_number > 0),
    product_id      BIGINT NOT NULL REFERENCES product (id),
    promotion_id    BIGINT,                                            -- NULL = không khuyến mãi
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    regular_price   NUMERIC(12, 2) NOT NULL CHECK (regular_price >= 0), -- giá tại thời điểm bán
    coupon_amount   NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (coupon_amount >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (transaction_id, line_number),
    -- Chỉ cho phép promotion áp dụng cho đúng sản phẩm (bỏ qua khi promotion_id NULL)
    CONSTRAINT fk_item_promotion_product
        FOREIGN KEY (product_id, promotion_id)
        REFERENCES promotion_product (product_id, promotion_id)
);

-- ---------- Index ----------
-- FK (Postgres không tự tạo index cho FK)
CREATE INDEX idx_employee_store            ON employee (store_id);
CREATE INDEX idx_product_category          ON product (category_id);
CREATE INDEX idx_product_brand             ON product (brand_id);
CREATE INDEX idx_promotion_product_promo   ON promotion_product (promotion_id);
CREATE INDEX idx_txn_store                 ON sales_transaction (store_id);
CREATE INDEX idx_txn_employee              ON sales_transaction (employee_id);
CREATE INDEX idx_txn_ts                    ON sales_transaction (transaction_ts);
CREATE INDEX idx_item_product              ON sales_transaction_item (product_id);

-- Cursor cho dlt incremental
CREATE INDEX idx_txn_updated_at            ON sales_transaction (updated_at);
CREATE INDEX idx_item_updated_at           ON sales_transaction_item (updated_at);
CREATE INDEX idx_product_updated_at        ON product (updated_at);
CREATE INDEX idx_employee_updated_at       ON employee (updated_at);

-- ---------- Gắn trigger updated_at cho mọi bảng ----------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'store', 'category', 'brand', 'payment_method', 'employee', 'product',
        'promotion', 'promotion_product', 'sales_transaction', 'sales_transaction_item'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%1$s_updated_at BEFORE UPDATE ON retail.%1$I
             FOR EACH ROW EXECUTE FUNCTION retail.set_updated_at()', t);
    END LOOP;
END $$;
