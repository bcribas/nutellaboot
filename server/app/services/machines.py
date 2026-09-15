"""Estado das máquinas, fila de comandos e bloqueio de tela.

Diferença central em relação ao nb2: a fila é por máquina e tem confirmação
(ack). No nb2 havia um único arquivo de texto por sede em /tmp, nunca
truncado, que servia de fila E de histórico; a máquina filtrava as linhas dos
últimos 600 s e cada comando era um nome de função bash executado direto.

A janela de 600 s voltou, do lado do servidor (`command_ttl_sec`): uma ordem
que ninguém buscou dentro dela caduca. Sem isso, o alvo "all" — resolvido no
envio para toda máquina com machine.json, inclusive as desligadas — deixava
um poweroff de ontem esperando a máquina ligar hoje.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from .. import fsdb
from .store import server_conf, site_image_dir

MAC_RE = re.compile(r"^[0-9a-f]{2}(-[0-9a-f]{2}){5,7}$")

# Comandos aceitos. `mlupdatecommands` (que baixava e executava um script
# remoto sem autenticação nenhuma) foi deliberadamente removido.
ALLOWED_COMMANDS = {
    "donottouch",
    "cantouch",
    "cleanhomenow",
    "mlreboot",
    "mlpoweroff",
    "disablefirewall",
    "enablefirewall",
    "resetcontaeditores",
    "precontest",
}

# Comandos que impõem, na máquina, o valor de um campo do formulário — e o
# valor que cada um impõe.
#
# É o que liga o cadeado do modelo aos botões do laboratório. `DISABLE_FIREWALL`
# nasce travado ("o firewall é obrigatório durante a maratona"), e mesmo assim o
# botão do hotconfig desligava o firewall da sala inteira: a trava valia no
# configureitor e não valia aqui.
#
# O sentido importa. `enablefirewall` move a máquina PARA o valor travado, então
# continua liberado — recusá-lo impediria a sede de consertar o que a
# organização quer. Só o sentido permissivo é barrado.
COMANDOS_DE_CONFIG = {
    "disablefirewall": ("DISABLE_FIREWALL", True),
    "enablefirewall": ("DISABLE_FIREWALL", False),
}

ONLINE_WINDOW = 90  # segundos sem contato para considerar a máquina offline


def normalize_mac(mac: str) -> str:
    mac = mac.strip().lower().replace(":", "-")
    return mac


def valid_mac(mac: str) -> bool:
    return bool(MAC_RE.match(mac))


# Quantas identificações inválidas diferentes guardar por imagem. É diagnóstico,
# não histórico: o que importa é "alguém está tentando, e com o quê".
MAX_REJEITADAS = 10


def record_rejected(image_id: str, bruto: str) -> None:
    """Guarda quem tentou reportar com uma identificação que não é um MAC.

    Um agente com a detecção de MAC quebrada bate no servidor a cada 25 s e
    leva 400 em tudo — inclusive no `status`, então a máquina nunca chega a
    existir e o painel fica vazio, sem dizer que alguém está tentando. Isso
    aconteceu por 30 horas seguidas antes de alguém olhar o log do servidor.
    """
    d = site_image_dir(image_id)
    if not d.is_dir():
        return
    with fsdb.locked(d):
        atual = fsdb.read_json(d / "rejected.json", {}) or {}
        entrada = atual.get(bruto) or {"first_seen": time.time(), "count": 0}
        entrada["count"] += 1
        entrada["last_seen"] = time.time()
        atual[bruto] = entrada
        if len(atual) > MAX_REJEITADAS:
            velhas = sorted(atual.items(), key=lambda kv: kv[1].get("last_seen", 0))
            atual = dict(velhas[-MAX_REJEITADAS:])
        fsdb.write_json(d / "rejected.json", atual)


def rejected(image_id: str) -> list[dict]:
    dados = fsdb.read_json(site_image_dir(image_id) / "rejected.json", {}) or {}
    out = [{"id": k, **v} for k, v in dados.items()]
    return sorted(out, key=lambda e: -(e.get("last_seen") or 0))


def machine_dir(image_id: str, mac: str) -> Path:
    return site_image_dir(image_id) / "machines" / mac


def list_macs(image_id: str) -> list[str]:
    base = site_image_dir(image_id) / "machines"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "machine.json").is_file())


def _hwinfo(status) -> dict:
    hw = status.get("hwinfo") if isinstance(status, dict) else None
    return hw if isinstance(hw, dict) else {}


def _epoch(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def record_status(image_id: str, mac: str, status: dict) -> dict:
    d = machine_dir(image_id, mac)
    now = time.time()
    hw = _hwinfo(status)
    with fsdb.locked(d):
        info = fsdb.read_json(d / "machine.json", {}) or {}
        first = not info
        info.setdefault("mac", mac)
        info.setdefault("first_seen", now)
        info["last_seen"] = now
        # o boot_id (NBUID do stuff) muda a cada boot: é o que dá "quantas
        # vezes ligou" e "desde quando está de pé" sem depender do agente
        boot = str(hw.get("boot_id") or "").strip()[:64]
        if boot and boot != info.get("boot_id"):
            info["boot_id"] = boot
            info["boots"] = int(info.get("boots") or 0) + 1
            info["boot_seen_at"] = now
            # o agente novo manda o instante real do boot; senão vale o
            # primeiro contato deste boot (±1 ciclo de telemetria)
            info["last_boot"] = _epoch(hw.get("last_boot")) or now
        fsdb.write_json(d / "machine.json", info)
        fsdb.write_json(d / "status.json", status)
    # o status.json é sobrescrito a cada envio: sem esta linha, memória, carga
    # e editores só existem no presente e não há relatório de período possível
    from . import samples

    samples.record(image_id, mac, status)
    # fora do lock da máquina: o índice trava o diretório da IMAGEM
    alerta = _indexa_identidade(image_id, mac, hw)
    return {"first_seen": first, "info": info, "alert": alerta}


def _indexa_identidade(image_id: str, mac: str, hw: dict) -> dict | None:
    """machine_id → mac por sede (padrão do record_rejected: lock do
    diretório da imagem). Devolve o alerta criado quando o id já era de OUTRA
    máquina — duas máquinas com o mesmo /etc/machine-id (home clonada, imagem
    de disco) confundem tudo que usa o id como chave, e o MOJ usou.

    Custa 1 leitura + 1 escrita por status, contra varrer a sede inteira."""
    mid = str(hw.get("machine_id") or "").strip()[:64]
    if not mid:
        return None
    base = site_image_dir(image_id)
    with fsdb.locked(base):
        idx = fsdb.read_json(base / "machineids.json", {}) or {}
        outro = idx.get(mid)
        if outro == mac:
            return None
        idx[mid] = mac
        fsdb.write_json(base / "machineids.json", idx)
    if not outro:
        return None
    from . import alerts  # import local: alerts importa daqui

    # um alerta aberto por máquina e id; sem isto A e B alternando gerariam
    # um alerta por status até alguém dispensar
    if any(
        a.get("kind") == alerts.IDENTIDADE and a.get("machine_id") == mid
        for a in alerts.open_alerts(image_id, mac)
    ):
        return None
    return alerts.raise_alert(
        image_id,
        mac,
        alerts.IDENTIDADE,
        f"machine-id tambem reportado por {outro}",
        {"machine_id": mid, "other_mac": outro},
    )


def get_machine(image_id: str, mac: str) -> dict:
    d = machine_dir(image_id, mac)
    info = fsdb.read_json(d / "machine.json", {}) or {}
    now = time.time()
    last = info.get("last_seen", 0)
    return {
        **info,
        "mac": mac,
        "online": (now - last) < ONLINE_WINDOW,
        "seconds_since_contact": int(now - last) if last else None,
        "status": fsdb.read_json(d / "status.json", {}) or {},
        "binding": fsdb.read_json(d / "binding.json"),
        "lock": fsdb.read_json(d / "lockstate.json", {"locked": False}),
        "pending": len(pending_commands(image_id, mac)),
        # a tela usa isto para saber se vale abrir a aba de logs; o conteúdo
        # em si só é buscado quando alguém pede
        "logs": {
            "bytes": info.get("logs_bytes", 0),
            "at": info.get("logs_at"),
        },
        # alertas abertos: ficam até alguém dispensar, então sobrevivem a
        # reboot da máquina e a recarga da página
        "alerts": fsdb.read_json(d / "alerts.json", []) or [],
    }


def list_machines(image_id: str, active_since: float = 0) -> list[dict]:
    out = []
    for mac in list_macs(image_id):
        if active_since:
            # só o machine.json antes das outras 4 leituras e do glob da fila
            # (padrão de labs.resumo_de): numa sede grande é a diferença
            # entre 1 e 6 leituras por máquina que não interessa
            info = fsdb.read_json(machine_dir(image_id, mac) / "machine.json", {}) or {}
            if (info.get("last_seen") or 0) < active_since:
                continue
        out.append(get_machine(image_id, mac))
    return out


# --- fila de comandos ---

# Uma ordem que ninguém buscou em `command_ttl_sec` caduca. O relógio conta a
# partir de `not_before`, não de `created_at`: uma ordem com delay de 15 min
# não pode caducar antes de nascer.
COMMAND_TTL_PADRAO = 600


def _command_ttl() -> int:
    return int(server_conf().get("command_ttl_sec", COMMAND_TTL_PADRAO))


def _expirada(entry: dict, now: float, ttl: int) -> bool:
    piso = entry.get("not_before") or entry.get("created_at") or 0
    return now > piso + ttl


def enqueue(image_id: str, macs: list[str], command: str, args: str = "", delay: int = 0) -> str:
    cid = secrets.token_hex(6)
    entry = {
        "id": cid,
        "command": command,
        "args": args,
        "created_at": time.time(),
        "not_before": time.time() + max(0, delay),
    }
    for mac in macs:
        q = machine_dir(image_id, mac) / "queue"
        q.mkdir(parents=True, exist_ok=True)
        fsdb.write_json(q / f"{int(time.time() * 1000)}-{cid}.json", entry)
    return cid


def pending_commands(image_id: str, mac: str) -> list[dict]:
    """A fila da máquina, já sem o que caducou.

    O que caducou é APAGADO aqui (não só filtrado): senão queue/ cresceria
    para sempre — o ack nunca virá — e o `pending` do painel mentiria. Fica o
    rastro em acks.log, no formato do ack e com `status: "expired"`, para o
    operador ver na aba de logs que a ordem não foi executada porque caducou,
    e não porque se perdeu.
    """
    q = machine_dir(image_id, mac) / "queue"
    if not q.is_dir():
        return []
    from .logcap import append_capped

    now = time.time()
    ttl = _command_ttl()
    out = []
    for f in sorted(q.glob("*.json")):
        entry = fsdb.read_json(f)
        if not entry:
            continue
        if _expirada(entry, now, ttl):
            f.unlink(missing_ok=True)
            append_capped(
                machine_dir(image_id, mac) / "acks.log",
                json.dumps(
                    {
                        "id": entry.get("id"),
                        "mac": mac,
                        "at": now,
                        "status": "expired",
                        "command": entry.get("command"),
                        "created_at": entry.get("created_at"),
                        "not_before": entry.get("not_before"),
                    },
                    ensure_ascii=False,
                ),
            )
            continue
        out.append(entry)
    return out


def ready_commands(image_id: str, mac: str) -> list[dict]:
    now = time.time()
    return [c for c in pending_commands(image_id, mac) if c.get("not_before", 0) <= now]


# comandos cujo ack marca "a contagem de editores recomeçou aqui"
RESET_EDITORES = ("resetcontaeditores", "precontest")


def ack(image_id: str, mac: str, cid: str, result: dict) -> bool:
    d = machine_dir(image_id, mac)
    q = d / "queue"
    found, comando = False, None
    for f in list(q.glob(f"*-{cid}.json")) if q.is_dir() else []:
        # o nome do comando só existe no arquivo da fila: ler ANTES de apagar,
        # senão o acks.log diz que "algo" foi confirmado sem dizer o quê
        entry = fsdb.read_json(f, {}) or {}
        comando = comando or entry.get("command")
        f.unlink(missing_ok=True)
        found = True
    linha = {"id": cid, "mac": mac, "at": time.time(), **result}
    if comando:
        linha["command"] = comando
    from .logcap import append_capped

    append_capped(d / "acks.log", json.dumps(linha, ensure_ascii=False))
    if comando in RESET_EDITORES and str(result.get("status", "done")) not in ("error", "failed"):
        # quem lê `editors_time` precisa saber desde quando ele conta
        with fsdb.locked(d):
            info = fsdb.read_json(d / "machine.json", {}) or {}
            info["editors_reset_at"] = time.time()
            fsdb.write_json(d / "machine.json", info)
    return found


# --- bloqueio de tela ---


def set_lock(image_id: str, mac: str, locked: bool, by: str = "") -> dict:
    d = machine_dir(image_id, mac)
    state = {"locked": locked, "since": time.time(), "by": by}
    with fsdb.locked(d):
        fsdb.write_json(d / "lockstate.json", state)
    return state


def get_lock(image_id: str, mac: str) -> dict:
    return fsdb.read_json(machine_dir(image_id, mac) / "lockstate.json", {"locked": False})
