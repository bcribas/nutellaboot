"""Logs de máquina (journal do kernel e do sistema).

O nb2 tinha isto e se perdeu na reescrita: a máquina mandava
`journalctl -S today` no boot e o incremento a cada 5 minutos, e o servidor
guardava por máquina, datado. É o que responde "o que aconteceu com aquele
computador às 14h32" depois que a prova acabou.

Dois tetos, porque log é o tipo de dado que enche disco em silêncio:
  * por requisição — o servidor recusa acima de MAX_ENVIO;
  * por máquina — `logcap.append_capped` mantém a cauda e descarta o começo.

100 máquinas mandando a cada 5 min cabem em 200 MB por construção.
"""

from __future__ import annotations

import time

from .. import fsdb
from .logcap import append_capped
from .machines import machine_dir

# Um envio típico do incremento de 5 minutos tem alguns kB; o do boot chega a
# centenas. 1 MiB é folgado e ainda assim impede que uma máquina em laço de
# erro escreva sem limite.
MAX_ENVIO = 1 * 1024 * 1024
POR_MAQUINA = 2 * 1024 * 1024


def caminho(image_id: str, mac: str):
    return machine_dir(image_id, mac) / "journal.log"


def record(image_id: str, mac: str, texto: str, *, origem: str = "journal") -> dict:
    """Guarda um pedaço de log. Cada bloco entra com um cabeçalho datado para
    dar para separar os envios depois."""
    texto = texto.replace("\r\n", "\n").strip("\n")
    # só espaço em branco conta como vazio: não vale gastar um bloco datado
    # com nada dentro
    if not texto.strip():
        return {"stored": 0}

    agora = time.time()
    cabecalho = f"===== {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(agora))} UTC · {origem} ====="
    append_capped(caminho(image_id, mac), cabecalho + "\n" + texto, cap=POR_MAQUINA)

    d = machine_dir(image_id, mac)
    with fsdb.locked(d):
        info = fsdb.read_json(d / "machine.json", {}) or {}
        info["logs_at"] = agora
        info["logs_bytes"] = tamanho(image_id, mac)
        fsdb.write_json(d / "machine.json", info)
    return {"stored": len(texto), "at": agora}


def tamanho(image_id: str, mac: str) -> int:
    p = caminho(image_id, mac)
    return p.stat().st_size if p.is_file() else 0


def tail(image_id: str, mac: str, linhas: int = 500) -> str:
    """Últimas `linhas` do journal desta máquina."""
    p = caminho(image_id, mac)
    if not p.is_file():
        return ""
    # o teto por máquina é de 2 MiB, então ler inteiro e cortar é honesto e
    # mais simples que caçar o offset da n-ésima linha de trás para a frente
    conteudo = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(conteudo[-max(1, linhas):])


def acks(image_id: str, mac: str, linhas: int = 100) -> list[dict]:
    """Confirmações de comando desta máquina. O arquivo já era escrito desde o
    começo do projeto, mas nenhuma rota o devolvia — quem quisesse saber se um
    comando chegou tinha que abrir o disco do servidor."""
    import json

    p = machine_dir(image_id, mac) / "acks.log"
    if not p.is_file():
        return []
    out = []
    for linha in p.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:]:
        try:
            out.append(json.loads(linha))
        except ValueError:
            continue
    return out


def clear(image_id: str, mac: str) -> None:
    caminho(image_id, mac).unlink(missing_ok=True)
