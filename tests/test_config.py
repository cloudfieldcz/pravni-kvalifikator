from pravni_kvalifikator.shared.config import EMBEDDING_DIMENSIONS, Settings, get_settings


def test_embedding_dimensions_constant():
    assert EMBEDDING_DIMENSIONS == 1536


def test_settings_defaults():
    s = Settings(
        azure_openai_endpoint="https://test.openai.azure.com/",
        azure_openai_api_key="test-key",
    )
    assert s.laws_db_path.name == "laws.db"
    assert s.sessions_db_path.name == "sessions.db"
    assert s.mcp_server_port == 8001
    assert s.web_port == 8000
    assert s.scraper_delay == 1.5
    assert s.log_level == "INFO"


def test_get_settings_singleton():
    # Reset singleton for test isolation
    import pravni_kvalifikator.shared.config as cfg

    cfg._settings = None

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2

    # Cleanup
    cfg._settings = None
