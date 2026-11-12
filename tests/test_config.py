import os

from medibytes.config import Settings


def test_env_file_exposes_hugging_face_settings_and_cors_origins(tmp_path, monkeypatch):
    hf_home = tmp_path / "hf-cache"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"HF_TOKEN=hf_test-token\nHF_HOME={hf_home}\n"
        "MEDIBYTES_CORS_ORIGINS=https://app.example.test, https://admin.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("MEDIBYTES_CORS_ORIGINS", raising=False)

    settings = Settings.from_env(env_file)

    assert os.environ["HF_TOKEN"] == "hf_test-token"
    assert os.environ["HF_HOME"] == str(hf_home)
    assert settings.cors_origins == ("https://app.example.test", "https://admin.example.test")
