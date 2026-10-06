from retail_pulse.ingestion.snowflake_init import load_statements


def test_statements_split_comments_removed_and_key_substituted():
    statements = load_statements("KEY123")
    assert all(s and not s.lstrip().startswith("--") for s in statements)
    assert any("RSA_PUBLIC_KEY = 'KEY123'" in s for s in statements)
    assert not any("__RSA_PUBLIC_KEY__" in s for s in statements)
    assert statements[0] == "USE ROLE ACCOUNTADMIN"
