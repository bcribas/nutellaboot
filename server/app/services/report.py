"""Relatório de uma sede por período: inventário e uso.

Serve para depois da prova — "o que essas máquinas eram e o que aconteceu nelas
entre 14h e 18h". O painel responde o presente; isto responde o passado, que é
outra pergunta e precisa de outra fonte (`services/samples.py`).

O HTML sai autocontido: CSS embutido e gráficos em SVG desenhados aqui, sem
biblioteca nem imagem externa. É um arquivo só, que se salva e se manda por
e-mail — e que abre numa máquina sem internet, que é onde ele costuma ser
lido.
"""

from __future__ import annotations

import html
import time
from collections import Counter

from .. import fsdb
from . import alerts, logs, machines, samples
from .store import get_site_image, site_image_dir

# Linhas de dmesg que valem a pena mostrar sem alguém pedir. Cada uma é um
# problema que explica uma máquina lenta, travada ou que reiniciou sozinha — e
# que passaria despercebido num journal de 2 MiB.
SUSPEITAS = (
    ("disco", r"I/O error|ata\d+\.\d+: failed|Buffer I/O error|medium error|SMART error"),
    ("memória", r"Out of memory|oom-kill|Killed process"),
    ("programa", r"segfault|general protection fault|traps:"),
    ("hardware", r"Machine Check Exception|mce:|Hardware Error"),
    ("temperatura", r"thermal throttling|CPU\d+: Core temperature above threshold"),
    ("usb", r"usb \S+: device descriptor read|usb \S+: reset .* device"),
    ("arquivos", r"EXT4-fs error|NTFS-fs error|remounting filesystem read-only"),
)

T = {
    "titulo": {"pt": "Relatório da sede", "en": "Site report", "es": "Informe de la sede"},
    "periodo": {"pt": "Período", "en": "Period", "es": "Período"},
    "gerado": {"pt": "Gerado em", "en": "Generated at", "es": "Generado el"},
    "maquinas": {"pt": "Máquinas", "en": "Machines", "es": "Máquinas"},
    "inventario": {"pt": "Inventário", "en": "Inventory", "es": "Inventario"},
    "processador": {"pt": "Processador", "en": "Processor", "es": "Procesador"},
    "nucleos": {"pt": "Núcleos", "en": "Threads", "es": "Núcleos"},
    "memoria": {"pt": "Memória", "en": "Memory", "es": "Memoria"},
    "resumo_ram": {"pt": "Perfil de memória", "en": "Memory profile", "es": "Perfil de memoria"},
    "resumo_cpu": {"pt": "Processadores", "en": "Processors", "es": "Procesadores"},
    "times": {"pt": "Times vinculados", "en": "Bound teams", "es": "Equipos vinculados"},
    "assento": {"pt": "Assento", "en": "Seat", "es": "Asiento"},
    "time": {"pt": "Time", "en": "Team", "es": "Equipo"},
    "organizacao": {"pt": "Organização", "en": "Organization", "es": "Organización"},
    "sem_time": {"pt": "sem time", "en": "no team", "es": "sin equipo"},
    "editores": {"pt": "Uso dos editores", "en": "Editor usage", "es": "Uso de los editores"},
    "editor": {"pt": "Editor", "en": "Editor", "es": "Editor"},
    "amostras": {"pt": "% das amostras", "en": "% of samples", "es": "% de las muestras"},
    "acumulado": {"pt": "min (contados na máquina)", "en": "min (counted on the machine)",
                  "es": "min (contados en la máquina)"},
    "recursos": {"pt": "Memória e carga", "en": "Memory and load", "es": "Memoria y carga"},
    "media": {"pt": "média", "en": "average", "es": "promedio"},
    "pico": {"pt": "pico", "en": "peak", "es": "pico"},
    "alertas": {"pt": "Alertas do período", "en": "Alerts in the period", "es": "Alertas del período"},
    "quando": {"pt": "Quando", "en": "When", "es": "Cuándo"},
    "oque": {"pt": "O quê", "en": "What", "es": "Qué"},
    "dispensado": {"pt": "Dispensado por", "en": "Dismissed by", "es": "Descartado por"},
    "dmesg": {"pt": "Estranhezas no dmesg", "en": "Odd lines in dmesg", "es": "Rarezas en dmesg"},
    "ocorrencias": {"pt": "Ocorrências", "en": "Occurrences", "es": "Ocurrencias"},
    "nada": {"pt": "Nada no período.", "en": "Nothing in the period.", "es": "Nada en el período."},
    "sem_amostra": {
        "pt": "Sem amostras no período. A telemetria guarda cerca de um mês por máquina, e o mais antigo é descartado primeiro.",
        "en": "No samples in the period. Telemetry keeps about a month per machine, and the oldest is dropped first.",
        "es": "Sin muestras en el período. La telemetría guarda cerca de un mes por máquina, y lo más antiguo se descarta primero.",
    },
    "corte": {
        "pt": "O período pedido começa antes da amostra mais antiga que existe ({inicio}) — o que vem antes disso já foi descartado.",
        "en": "The requested period starts before the oldest sample kept ({inicio}) — anything earlier was already dropped.",
        "es": "El período pedido empieza antes de la muestra más antigua ({inicio}) — lo anterior ya fue descartado.",
    },
}


def _t(chave: str, lang: str) -> str:
    return T[chave].get(lang, T[chave]["pt"])


def _quando(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def _faixa_ram(mb) -> str:
    try:
        gb = int(mb) / 1024
    except (TypeError, ValueError):
        return "?"
    for limite, rotulo in ((4.5, "≤ 4 GB"), (8.5, "8 GB"), (16.5, "16 GB"), (32.5, "32 GB")):
        if gb < limite:
            return rotulo
    return "> 32 GB"


def coletar(image_id: str, since: float, until: float) -> dict:
    """Os números do relatório, sem uma linha de HTML — é o que a rota devolve
    em `format=json` e o que os testes conferem."""
    info = get_site_image(image_id) or {}
    roster = {
        str(e.get("user_id")): e
        for e in (fsdb.read_json(site_image_dir(image_id) / "roster.json", []) or [])
        if isinstance(e, dict)
    }

    itens, ram, cpus = [], Counter(), Counter()
    usos, total_amostras = Counter(), 0
    acumulado = Counter()
    acumulado_total = 0
    todos_alertas, achados = [], Counter()
    corte = 0.0

    for m in machines.list_machines(image_id):
        mac = m["mac"]
        status = m.get("status") or {}
        hw = status.get("hwinfo") or {}
        binding = m.get("binding") or {}
        entrada = roster.get(str(binding.get("user_id", ""))) or {}

        serie = samples.series(image_id, mac, since, until)
        total_amostras += len(serie)
        for s in serie:
            for ed in s.get("ed") or []:
                usos[ed] += 1
        mems = [s["mem"] for s in serie if isinstance(s.get("mem"), (int, float))]
        cargas = [s["ld"] for s in serie if isinstance(s.get("ld"), (int, float))]

        # "faltou dado" só quando o TETO comeu o histórico. Deduzir isso de
        # "a amostra mais antiga é recente" acusaria toda máquina que ligou no
        # meio da prova — e o aviso deixaria de significar alguma coisa.
        primeira = samples.primeira_amostra(image_id, mac)
        if since and primeira > since and samples.foi_truncado(image_id, mac):
            corte = max(corte, primeira)

        # o acumulado contado na própria máquina (o que o nb2 fazia)
        tempos = (status.get("operations") or {}).get("editors_time") or {}
        if isinstance(tempos, dict):
            for ed, minutos in tempos.items():
                if ed == "total":
                    acumulado_total = max(acumulado_total, int(minutos or 0))
                elif isinstance(minutos, int):
                    acumulado[ed] += minutos

        for ev in alerts.history(image_id, mac):
            quando = ev.get("at") or 0
            if since and quando < since:
                continue
            if until and quando > until:
                continue
            if ev.get("event") == "raised":
                todos_alertas.append({**ev, "mac": mac})

        for rotulo, quantas in _dmesg(image_id, mac, since, until).items():
            achados[rotulo] += quantas

        ram[_faixa_ram(hw.get("memtotal_mb"))] += 1
        cpus[str(hw.get("processor") or "?")] += 1
        itens.append(
            {
                "mac": mac,
                "processor": hw.get("processor") or "—",
                "cores": hw.get("cores"),
                "memtotal_mb": hw.get("memtotal_mb"),
                "seat": binding.get("seat") or entrada.get("seat") or "",
                "team": binding.get("name")
                or entrada.get("display_name")
                or entrada.get("name")
                or binding.get("user_id")
                or "",
                "organization": (entrada.get("organization") or {}).get("name", "")
                if isinstance(entrada.get("organization"), dict)
                else "",
                "country": entrada.get("country") or "",
                "amostras": len(serie),
                "mem_media": round(sum(mems) / len(mems)) if mems else None,
                "mem_pico": max(mems) if mems else None,
                "carga_media": round(sum(cargas) / len(cargas), 2) if cargas else None,
                "carga_pico": max(cargas) if cargas else None,
                "serie": serie,
            }
        )

    itens.sort(key=lambda i: (str(i["seat"]), i["mac"]))
    todos_alertas.sort(key=lambda a: a.get("at") or 0)
    return {
        "image": image_id,
        "fullname": info.get("fullname") or image_id,
        "since": since,
        "until": until,
        "gerado_em": time.time(),
        "corte": corte,
        "machines": itens,
        "ram": dict(ram),
        "cpus": dict(cpus),
        "editors": dict(usos),
        "samples": total_amostras,
        "editors_time": dict(acumulado),
        "editors_time_total": acumulado_total,
        "alerts": todos_alertas,
        "dmesg": dict(achados),
    }


def _dmesg(image_id: str, mac: str, since: float, until: float) -> Counter:
    """Conta as linhas suspeitas nos blocos do journal dentro do intervalo.

    O journal é gravado em blocos com cabeçalho datado (o carimbo é o da
    RECEPÇÃO, com granularidade de 5 min); a linha em si tem o formato do
    syslog, sem ano e no fuso da máquina. Recortar por bloco é o que dá para
    fazer de forma determinística com o que existe.
    """
    import calendar
    import re

    achados = Counter()
    texto = logs.tail(image_id, mac, 20000)
    if not texto:
        return achados
    dentro = not since
    for linha in texto.splitlines():
        cab = re.match(r"^===== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC", linha)
        if cab:
            # timegm e nao mktime: o carimbo do bloco e UTC, e mktime o leria
            # como hora local — o recorte erraria pelo fuso inteiro
            quando = calendar.timegm(time.strptime(cab.group(1), "%Y-%m-%d %H:%M:%S"))
            dentro = (not since or quando >= since - 300) and (not until or quando <= until)
            continue
        if not dentro:
            continue
        for rotulo, padrao in SUSPEITAS:
            if re.search(padrao, linha, re.I):
                achados[rotulo] += 1
                break
    return achados


# --- desenho ----------------------------------------------------------------


def _esc(v) -> str:
    return html.escape(str(v if v is not None else "—"))


def _barras(dados: dict, largura: int = 520) -> str:
    """Barras horizontais em SVG. Nada de biblioteca: o relatório precisa abrir
    numa máquina sem internet, e é isso que "autocontido" quer dizer."""
    if not dados:
        return ""
    itens = sorted(dados.items(), key=lambda kv: -kv[1])
    maior = max(v for _, v in itens) or 1
    alt_linha, rotulo = 26, 190
    altura = alt_linha * len(itens) + 10
    partes = [
        f'<svg viewBox="0 0 {largura} {altura}" width="100%" height="{altura}" '
        f'role="img" xmlns="http://www.w3.org/2000/svg">'
    ]
    for i, (nome, valor) in enumerate(itens):
        y = i * alt_linha + 8
        w = int((largura - rotulo - 60) * valor / maior)
        partes.append(
            f'<text x="0" y="{y + 12}" font-size="13" fill="#333">{_esc(nome)[:28]}</text>'
            f'<rect x="{rotulo}" y="{y}" width="{max(w, 1)}" height="16" fill="#3b6ea5" rx="3"/>'
            f'<text x="{rotulo + max(w, 1) + 8}" y="{y + 13}" font-size="12" fill="#555">{valor}</text>'
        )
    partes.append("</svg>")
    return "".join(partes)


def _linha_tempo(serie: list[dict], chave: str, teto: float, cor: str) -> str:
    """Curva de uma máquina no período. Sem eixo: o que interessa aqui é a
    forma (subiu, ficou no talo, caiu) e o valor de pico, que vai ao lado."""
    pontos = [(s.get("t", 0), s.get(chave)) for s in serie if s.get(chave) is not None]
    if len(pontos) < 2:
        return ""
    t0, t1 = pontos[0][0], pontos[-1][0]
    span = (t1 - t0) or 1
    largura, altura = 260, 34
    coords = " ".join(
        f"{(t - t0) / span * largura:.1f},{altura - min(float(v), teto) / teto * altura:.1f}"
        for t, v in pontos
    )
    return (
        f'<svg viewBox="0 0 {largura} {altura}" width="{largura}" height="{altura}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{coords}" fill="none" stroke="{cor}" stroke-width="1.5"/></svg>'
    )


CSS = """
body{font:15px/1.5 system-ui,sans-serif;color:#222;max-width:1100px;margin:2rem auto;padding:0 1rem}
h1{margin-bottom:.2rem} h2{margin-top:2.2rem;border-bottom:2px solid #eee;padding-bottom:.3rem}
.sub{color:#666;margin-top:0}
table{border-collapse:collapse;width:100%;margin:.8rem 0;font-size:14px}
th,td{text-align:left;padding:.35rem .6rem;border-bottom:1px solid #eee;vertical-align:middle}
th{background:#fafafa;font-weight:600}
td.mono,th.mono{font-family:ui-monospace,monospace;font-size:13px}
.aviso{background:#fff8e1;border-left:4px solid #f0b429;padding:.6rem .9rem;margin:1rem 0}
.nada{color:#888;font-style:italic}
.par{display:flex;gap:1.5rem;flex-wrap:wrap}
.par>div{flex:1;min-width:300px}
@media print{body{max-width:none;margin:0} h2{page-break-after:avoid}}
"""


def html_report(dados: dict, lang: str = "pt") -> str:
    def t(k):
        return _t(k, lang)

    p = [
        "<!doctype html><html lang=", f'"{lang}"', "><head><meta charset='utf-8'>",
        f"<title>{_esc(dados['fullname'])} — {t('titulo')}</title>",
        f"<style>{CSS}</style></head><body>",
        f"<h1>{_esc(dados['fullname'])}</h1>",
        f"<p class='sub'>{t('titulo')} · {t('periodo')}: {_quando(dados['since'])} → "
        f"{_quando(dados['until'])} · {t('gerado')} {_quando(dados['gerado_em'])}</p>",
    ]
    if dados["corte"]:
        p.append(
            f"<div class='aviso'>{_esc(T['corte'][lang].format(inicio=_quando(dados['corte'])))}</div>"
        )

    # inventário
    p.append(f"<h2>{t('inventario')} — {len(dados['machines'])} {t('maquinas').lower()}</h2>")
    p.append(
        f"<table><tr><th class='mono'>MAC</th><th>{t('processador')}</th>"
        f"<th>{t('nucleos')}</th><th>{t('memoria')}</th><th>{t('assento')}</th>"
        f"<th>{t('time')}</th></tr>"
    )
    for m in dados["machines"]:
        ram = f"{m['memtotal_mb']} MB" if m["memtotal_mb"] else "—"
        p.append(
            f"<tr><td class='mono'>{_esc(m['mac'])}</td><td>{_esc(m['processor'])}</td>"
            f"<td>{_esc(m['cores'])}</td><td>{_esc(ram)}</td><td>{_esc(m['seat'])}</td>"
            f"<td>{_esc(m['team'] or t('sem_time'))}</td></tr>"
        )
    p.append("</table>")

    p.append("<div class='par'>")
    p.append(f"<div><h3>{t('resumo_ram')}</h3>{_barras(dados['ram'])}</div>")
    p.append(f"<div><h3>{t('resumo_cpu')}</h3>{_barras(dados['cpus'])}</div>")
    p.append("</div>")

    # editores
    p.append(f"<h2>{t('editores')}</h2>")
    if dados["samples"]:
        pct = {
            k: round(v * 100 / dados["samples"])
            for k, v in dados["editors"].items()
        }
        p.append(_barras(pct))
        p.append(
            f"<table><tr><th>{t('editor')}</th><th>{t('amostras')}</th>"
            f"<th>{t('acumulado')}</th></tr>"
        )
        chaves = set(pct) | set(dados["editors_time"])
        for ed in sorted(chaves, key=lambda e: -pct.get(e, 0)):
            mins = dados["editors_time"].get(ed)
            p.append(
                f"<tr><td>{_esc(ed)}</td><td>{pct.get(ed, 0)}%</td>"
                f"<td>{_esc(mins) if mins is not None else '—'}</td></tr>"
            )
        p.append("</table>")
    else:
        p.append(f"<p class='nada'>{t('sem_amostra')}</p>")

    # memória e carga
    p.append(f"<h2>{t('recursos')}</h2>")
    if dados["samples"]:
        p.append(
            f"<table><tr><th class='mono'>MAC</th><th>{t('memoria')} ({t('media')}/{t('pico')})</th>"
            f"<th></th><th>{t('recursos').split(' ')[-1]} ({t('media')}/{t('pico')})</th><th></th></tr>"
        )
        for m in dados["machines"]:
            p.append(
                f"<tr><td class='mono'>{_esc(m['mac'])}</td>"
                f"<td>{_esc(m['mem_media'])}% / {_esc(m['mem_pico'])}%</td>"
                f"<td>{_linha_tempo(m['serie'], 'mem', 100, '#3b6ea5')}</td>"
                f"<td>{_esc(m['carga_media'])} / {_esc(m['carga_pico'])}</td>"
                f"<td>{_linha_tempo(m['serie'], 'ld', 8, '#a5533b')}</td></tr>"
            )
        p.append("</table>")
    else:
        p.append(f"<p class='nada'>{t('sem_amostra')}</p>")

    # alertas
    p.append(f"<h2>{t('alertas')}</h2>")
    if dados["alerts"]:
        p.append(
            f"<table><tr><th>{t('quando')}</th><th class='mono'>MAC</th>"
            f"<th>{t('oque')}</th><th>{t('dispensado')}</th></tr>"
        )
        for a in dados["alerts"]:
            p.append(
                f"<tr><td>{_quando(a.get('at'))}</td><td class='mono'>{_esc(a.get('mac'))}</td>"
                f"<td>{_esc(a.get('kind'))} · {_esc(a.get('detail'))}</td>"
                f"<td>{_esc(a.get('dismissed_by') or '')}</td></tr>"
            )
        p.append("</table>")
    else:
        p.append(f"<p class='nada'>{t('nada')}</p>")

    # dmesg
    p.append(f"<h2>{t('dmesg')}</h2>")
    if dados["dmesg"]:
        p.append(_barras(dados["dmesg"]))
    else:
        p.append(f"<p class='nada'>{t('nada')}</p>")

    p.append("</body></html>")
    return "".join(p)
