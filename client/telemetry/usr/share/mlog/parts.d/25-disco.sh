# Uso de disco — fragmento JSON (sem chaves externas).
#
# O /home das máquinas é a partição persistente local: é exatamente o que
# enche durante a prova (compilações, cores, o que o time baixar). O / vai
# junto porque é overlay em RAM — encher o / é outra doença, com outro
# remédio, e as duas apareciam misturadas como "acabou o espaço".
#
# NB_DISCO_HOME/NB_DISCO_ROOT existem para os testes exercitarem isto de
# verdade, sem depender do layout da máquina de CI.
python3 - <<'PY'
import json
import os

def uso(caminho):
    try:
        st = os.statvfs(caminho)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    livre = st.f_bavail * st.f_frsize
    usado = total - (st.f_bfree * st.f_frsize)
    if total <= 0:
        return None
    return {
        "used_mb": usado // (1024 * 1024),
        "free_mb": livre // (1024 * 1024),
        # a base é o que um processo comum ainda consegue usar (bavail):
        # é o número que interessa quando o time está a 200 MB do fim
        "pct": min(100, round(100 * usado / max(1, usado + livre))),
    }

home = uso(os.environ.get("NB_DISCO_HOME", "/home"))
raiz = uso(os.environ.get("NB_DISCO_ROOT", "/"))

saida = {}
if home:
    saida = {
        "home_used_mb": home["used_mb"],
        "home_free_mb": home["free_mb"],
        "home_pct": home["pct"],
    }
if raiz:
    saida["root_free_mb"] = raiz["free_mb"]

print(json.dumps({"sysdisk": saida}, ensure_ascii=False)[1:-1])
PY
