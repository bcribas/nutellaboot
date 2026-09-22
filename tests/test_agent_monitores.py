"""Alerta de mais de um monitor, no agente.

Na prova normalmente só um monitor é permitido (campo "Monitores permitidos",
`NB_MAX_MONITORS`). O agente conta os monitores ACESOS no sysfs do DRM e, acima
do limite por duas passadas seguidas, põe um evento `display.multiple` na
mesma fila dos dispositivos USB. Vale também o que já estava ligado no boot.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTE = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "agent.sh"


def _funcao(texto, nome):
    inicio = texto.index(f"{nome}() {{")
    return texto[inicio:texto.index("\n}\n", inicio) + 3]


class Maquina:
    def __init__(self, tmp_path):
        self.drm = tmp_path / "drm"
        self.drm.mkdir()
        (self.drm / "card1").mkdir()  # o nó da placa não é conector
        self.estado = tmp_path / "estado"
        self.estado.mkdir()
        self.fila = self.estado / "usb-events"

    def conector(self, nome, status="connected", enabled="enabled"):
        d = self.drm / f"card1-{nome}"
        d.mkdir(exist_ok=True)
        (d / "status").write_text(status + "\n")
        (d / "enabled").write_text(enabled + "\n")

    def tira(self, nome):
        self.conector(nome, "disconnected", "disabled")

    def tick(self, limite="1"):
        texto = AGENTE.read_text()
        script = (
            "log() { :; }\n"
            f'NB3_SYSFS_DRM="{self.drm}"\nSTATE_DIR="{self.estado}"\n'
            f'USB_FILA="{self.fila}"\nMONITORES_ARQ="{self.estado}/monitores"\n'
            f"NB_MAX_MONITORS='{limite}'\n"
            + _funcao(texto, "monitores_ativos") + _funcao(texto, "monitores_tick") + "monitores_tick\n"
        )
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        assert r.returncode == 0, r.stderr
        return self.eventos()

    def eventos(self):
        if not self.fila.is_dir():
            return []
        return [dict(l.split("=", 1) for l in f.read_text().splitlines()) for f in sorted(self.fila.iterdir())
                if not f.name.endswith(".tmp")]


def test_um_monitor_nao_avisa(tmp_path):
    m = Maquina(tmp_path)
    m.conector("DP-1")
    for _ in range(4):
        assert m.tick() == []


def test_dois_monitores_avisam_na_segunda_passada_e_uma_vez_so(tmp_path):
    m = Maquina(tmp_path)
    m.conector("DP-1")
    m.conector("HDMI-A-1")
    assert m.tick() == [], "uma passada só pode ser o instante da subida da sessão"
    ev = m.tick()
    assert ev == [{"kind": "display.multiple", "vendor": "", "detail": "2 monitores: DP-1, HDMI-A-1"}]
    assert len(m.tick()) == 1 and len(m.tick()) == 1, "não reenfileira a cada passada"


def test_tampa_fechada_e_writeback_nao_contam(tmp_path):
    m = Maquina(tmp_path)
    m.conector("HDMI-A-1")
    m.conector("eDP-1", "connected", "disabled")
    m.conector("Writeback-1", "unknown", "disabled")
    for _ in range(3):
        assert m.tick() == []


def test_voltar_a_um_zera_e_um_novo_segundo_avisa_de_novo(tmp_path):
    m = Maquina(tmp_path)
    m.conector("DP-1")
    m.conector("HDMI-A-1")
    m.tick(), m.tick()
    assert len(m.eventos()) == 1
    m.tira("HDMI-A-1")
    m.tick()
    m.conector("HDMI-A-1")
    m.tick(), m.tick()
    assert len(m.eventos()) == 2


def test_o_limite_vem_do_formulario(tmp_path):
    m = Maquina(tmp_path)
    m.conector("DP-1")
    m.conector("HDMI-A-1")
    for _ in range(3):
        assert m.tick(limite="2") == []
    for _ in range(3):
        assert m.tick(limite="0") == [], "0 é sem limite"
    m.conector("DP-2")
    m.tick(limite="2"), m.tick(limite="2")
    assert m.eventos()[0]["detail"] == "3 monitores: DP-1, DP-2, HDMI-A-1"


def test_limite_invalido_vale_um(tmp_path):
    m = Maquina(tmp_path)
    m.conector("DP-1")
    m.conector("HDMI-A-1")
    m.tick(limite="dois")
    assert len(m.tick(limite="dois")) == 1


def test_o_laco_comeca_depois_do_descarte_da_fila():
    """O usb_loop descarta a fila do boot na primeira passada; o laço dos
    monitores dorme antes da primeira passada e ainda exige duas."""
    texto = AGENTE.read_text()
    laco = _funcao(texto, "monitores_loop")
    assert laco.index("sleep 5") < laco.index("monitores_tick")
    fim = texto[texto.rindex('log "iniciando'):]
    assert fim.index("usb_loop &") < fim.index("monitores_loop &")
