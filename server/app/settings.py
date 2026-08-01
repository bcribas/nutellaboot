"""Configuração do servidor via variáveis de ambiente NB3_*."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

VERSION = "3.0.0.dev0"


class Settings:
    def __init__(self) -> None:
        self.data_root = Path(os.environ.get("NB3_DATA_ROOT", str(REPO_ROOT / "data")))
        self.base_url = os.environ.get(
            "NB3_BASE_URL", "https://nutellaboot.charge.naquadah.com.br:8443"
        ).rstrip("/")
        self.host = os.environ.get("NB3_HOST", "127.0.0.1")
        self.port = int(os.environ.get("NB3_PORT", "8890"))


settings = Settings()
