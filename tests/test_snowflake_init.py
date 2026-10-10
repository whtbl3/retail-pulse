from retail_pulse.ingestion.snowflake_init import load_statements, mask


def test_statements_split_comments_removed_and_each_user_gets_its_own_key():
    keys = {"DLT_LOADER": "KEY_DLT", "DBT_TRANSFORMER": "KEY_DBT", "GITHUB_CI": "KEY_CI"}
    statements = load_statements(keys)
    assert all(s and not s.lstrip().startswith("--") for s in statements)
    assert any("ALTER USER DLT_LOADER SET RSA_PUBLIC_KEY = 'KEY_DLT'" in s for s in statements)
    assert any("ALTER USER DBT_TRANSFORMER SET RSA_PUBLIC_KEY = 'KEY_DBT'" in s for s in statements)
    assert any("ALTER USER GITHUB_CI SET RSA_PUBLIC_KEY = 'KEY_CI'" in s for s in statements)
    assert not any("_PUBLIC_KEY__" in s for s in statements)
    assert statements[0] == "USE ROLE ACCOUNTADMIN"
    alter_ci = next(s for s in statements if s.startswith("ALTER USER GITHUB_CI"))
    assert "KEY_CI" not in mask(alter_ci, keys)
