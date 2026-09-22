# Qual agente é este e o que ele sabe medir — chaves de topo do status.
#
# A frota é mista: o agente chega por uma camada, e uma sede pode estar com a
# camada velha por semanas. Quem consome a telemetria (o MOJ) adivinhava a
# versão pela presença de `t_agent`, que é frágil. `capabilities` diz o que
# ESTE agente manda quando o kernel e a sessão deixam; um campo ausente num
# agente que o anuncia é "não deu para medir", não "agente antigo".
#
# Esta parte SEMPRE imprime algo: o collect() junta as partes com vírgula, e
# uma parte vazia no começo quebraria o JSON inteiro.
python3 - <<'PY'
import json, os

aqui = os.environ.get("NB_AGENTE_DIR", "/usr/share/mlog")
try:
    with open(os.path.join(aqui, "VERSION"), encoding="utf-8") as f:
        versao = f.read().strip()
except OSError:
    versao = ""

# o que as outras partes deste mesmo pacote emitem
capacidades = ["psi", "oom", "idle", "skew", "editors_since", "monitors"]
# o MAC no User-Agent não é do agente: quem o põe é o stuff do boot, que também
# grava /etc/mac-icpc. Com o arquivo, o UA desta máquina tem o MAC no fim.
try:
    with open(os.environ.get("NB_MAC_ARQ", "/etc/mac-icpc"), encoding="utf-8") as f:
        if f.read().strip():
            capacidades.append("ua_mac")
except OSError:
    pass

print(json.dumps({"agent_version": versao, "capabilities": capacidades})[1:-1])
PY
