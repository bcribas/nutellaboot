"""Migração dos nomes antigos (template/image) para os novos (modelo/site-image)."""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FERRAMENTA = REPO / "tools" / "nb3-migrate-names"


def monta_dados_antigos(tmp_path: Path) -> Path:
    """Um data/ no formato anterior à renomeação."""
    d = tmp_path / "data"
    (d / "templates" / "modelo1").mkdir(parents=True)
    (d / "templates" / "modelo1" / "template.json").write_text(
        json.dumps({"layers": [{"md5": "a" * 32, "file": "base.squash"}], "public": True})
    )
    (d / "templates" / "modelo1" / "schema.json").write_text(json.dumps({"fields": []}))

    img = d / "images" / "sede1"
    img.mkdir(parents=True)
    (img / "image.json").write_text(
        json.dumps({"id": "sede1", "template": "modelo1", "invite": "NB3-AAAA-BBBB"})
    )
    (img / "token").write_text("nb3i_x\n")

    (d / "invites.json").write_text(
        json.dumps({"NB3-AAAA-BBBB": {"template": "modelo1", "max_images": 1, "used_images": ["sede1"]}})
    )
    (d / "layerbuilds" / "done").mkdir(parents=True)
    (d / "layerbuilds" / "done" / "j1.json").write_text(
        json.dumps({"id": "j1", "template": "modelo1", "packages": ["htop"]})
    )
    return d


def roda(data: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(FERRAMENTA), "--data", str(data), *args],
        capture_output=True,
        text=True,
        env={**os.environ},
    )


def test_dry_run_nao_muda_nada(tmp_path):
    d = monta_dados_antigos(tmp_path)
    antes = sorted(p.relative_to(d).as_posix() for p in d.rglob("*"))
    r = roda(d, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "simulação" in r.stdout
    assert sorted(p.relative_to(d).as_posix() for p in d.rglob("*")) == antes


def test_migra_estrutura_e_campos(tmp_path):
    d = monta_dados_antigos(tmp_path)
    r = roda(d)
    assert r.returncode == 0, r.stdout + r.stderr

    # diretórios
    assert (d / "models" / "modelo1" / "model.json").is_file()
    assert not (d / "templates").exists()
    assert (d / "site-images" / "sede1" / "image.json").is_file()
    assert not (d / "images").exists()
    # o schema veio junto
    assert (d / "models" / "modelo1" / "schema.json").is_file()

    modelo = json.loads((d / "models" / "modelo1" / "model.json").read_text())
    assert modelo["name"] == "modelo1"
    assert modelo["owner"] == "admin"
    assert modelo["layers"][0]["file"] == "base.squash"

    img = json.loads((d / "site-images" / "sede1" / "image.json").read_text())
    assert img["model"] == "modelo1"
    assert "template" not in img
    # o código do convite virou credencial de console: não pode continuar
    # legível para quem tem só o token da site-image
    assert "invite" not in img
    assert img["owner"] == "admin"
    # os segredos não foram tocados
    assert (d / "site-images" / "sede1" / "token").read_text() == "nb3i_x\n"

    convites = json.loads((d / "invites.json").read_text())
    assert convites["NB3-AAAA-BBBB"]["model"] == "modelo1"
    assert "template" not in convites["NB3-AAAA-BBBB"]

    job = json.loads((d / "layerbuilds" / "done" / "j1.json").read_text())
    assert job["model"] == "modelo1"


def test_idempotente(tmp_path):
    """Rodar duas vezes tem de dar exatamente no mesmo lugar."""
    d = monta_dados_antigos(tmp_path)
    roda(d)
    depois_1 = {
        p.relative_to(d).as_posix(): (p.read_bytes() if p.is_file() else None) for p in sorted(d.rglob("*"))
    }
    r = roda(d)
    assert r.returncode == 0, r.stdout + r.stderr
    depois_2 = {
        p.relative_to(d).as_posix(): (p.read_bytes() if p.is_file() else None) for p in sorted(d.rglob("*"))
    }
    # ignora o marcador (guarda a hora da última execução)
    depois_1.pop(".migrations.json", None)
    depois_2.pop(".migrations.json", None)
    assert depois_1 == depois_2


def test_instalacao_nova_nao_quebra(tmp_path):
    """Sem dados antigos, a migração não deve reclamar."""
    d = tmp_path / "data"
    (d / "models").mkdir(parents=True)
    r = roda(d)
    assert r.returncode == 0, r.stdout + r.stderr


def test_nao_sobrescreve_se_o_destino_ja_existe(tmp_path):
    """Segurança: se alguém já criou models/ à mão, não perder dados."""
    d = monta_dados_antigos(tmp_path)
    (d / "models" / "outro").mkdir(parents=True)
    r = roda(d)
    assert "não sobrescrevo" in r.stdout
    assert (d / "templates").exists(), "os dados antigos continuam lá para inspeção"
    # e o passo NÃO pode ficar marcado como aplicado: ele não fez nada
    assert r.returncode != 0, "desistir por conflito tem que sair diferente de zero"


def test_depois_de_resolver_o_conflito_a_migracao_completa(tmp_path):
    """O passo era marcado como aplicado mesmo tendo desistido: quem resolvia
    o conflito e rodava de novo ouvia "já aplicado" e ficava com o
    `templates/` intacto para sempre — e o relatório final ainda dizia
    "nenhum resíduo", porque procurava a palavra dentro dos JSON, e um
    `template.json` típico não a contém."""
    d = monta_dados_antigos(tmp_path)
    (d / "models" / "outro").mkdir(parents=True)
    roda(d)

    # o operador resolve o conflito
    (d / "models" / "outro").rmdir()
    (d / "models").rmdir()

    r = roda(d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (d / "models" / "modelo1" / "model.json").is_file()
    assert not (d / "templates").exists()


def test_o_relatorio_ve_o_diretorio_antigo(tmp_path):
    """Procurar a palavra dentro dos JSON dizia "nenhum resíduo" com o
    `templates/` inteiro parado ao lado — o conteúdo de um `template.json`
    típico (`{"layers": [...]}`) não contém a palavra em lugar nenhum."""
    d = monta_dados_antigos(tmp_path)
    roda(d)  # migra tudo, marcando os passos
    # e alguém repõe o diretório antigo (restauração de backup, por exemplo)
    (d / "templates" / "modelo1").mkdir(parents=True)
    (d / "templates" / "modelo1" / "template.json").write_text(json.dumps({"layers": []}))

    r = roda(d)
    assert r.returncode != 0, r.stdout
    assert "resíduos" in r.stdout
    assert "templates/" in r.stdout
