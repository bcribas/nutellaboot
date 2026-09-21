"""Para onde uma chave de SERVIÇO pode mandar o servidor bater.

Webhook é o servidor fazendo HTTP para uma URL escolhida por quem o configura,
de dentro da rede da máquina de gestão. Enquanto só a administração
configurava, a confiança era dela. Com o escopo `webhooks:write`, quem tem uma
chave de serviço vazada escolheria o destino: o metadata da nuvem, o painel de
um equipamento, outro serviço do mesmo host. Por isso a entrada de dono
`service:*` só aceita https para endereço PÚBLICO, a não ser que a
administração tenha liberado o destino em `data/server.json`:

    {"webhooks": {"allow_hosts": ["moj.interno", "10.1.0.0/16"]}}

A conferência roda ao gravar e de novo na hora de entregar (o DNS pode ter
mudado). Entre conferir e conectar ainda sobra uma janela de DNS rebinding:
isto estreita o caminho, não o fecha. Entradas da administração não passam
por aqui.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from . import store


def _liberados() -> tuple[set[str], list]:
    conf = (store.server_conf().get("webhooks") or {}).get("allow_hosts") or []
    nomes, redes = set(), []
    for item in conf:
        item = str(item).strip().lower()
        try:
            redes.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            nomes.add(item)
    return nomes, redes


def _resolver(host: str) -> list[str]:
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})


def motivo_da_recusa(url: str) -> str | None:
    """None quando pode. Bloqueia (resolve DNS): chame de thread."""
    partes = urlsplit(url)
    host = (partes.hostname or "").lower()
    if partes.scheme not in ("http", "https") or not host:
        return "a url precisa ser http(s) com host"
    if partes.username or partes.password:
        return "a url não pode levar usuário e senha"
    nomes, redes = _liberados()
    if host in nomes:
        return None
    try:
        enderecos = _resolver(host)
    except OSError:
        return f"não consegui resolver {host}"
    ips = []
    for e in enderecos:
        ip = ipaddress.ip_address(e.split("%", 1)[0])
        ips.append(getattr(ip, "ipv4_mapped", None) or ip)
    if ips and all(any(ip in r for r in redes) for ip in ips):
        return None
    if partes.scheme != "https":
        return "só https (http apenas para destino liberado pela administração)"
    if not ips or not all(ip.is_global for ip in ips):
        return f"{host} não é um endereço público; peça à administração para liberá-lo"
    return None
