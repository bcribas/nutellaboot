# Estado operacional: firewall, tela de bloqueio e editores abertos.
python3 - <<'PY'
import json, os, subprocess

def firewall():
    try:
        r = subprocess.run(["systemctl", "is-active", "maratona-firewall.service"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return None

EDITORES = ("emacs", "vim", "geany", "clion", "code", "pycharm", "idea",
            "gedit", "codeblocks", "sublime")

def editores():
    try:
        r = subprocess.run(["ps", "-U", "icpc", "-o", "comm="],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    nomes = r.stdout.lower().split()
    return sorted({e for e in EDITORES if any(e in n for n in nomes)})

def acumulado():
    """Minutos com cada editor aberto, contados pelo laço do agente.

    O instantâneo acima diz o que está aberto AGORA — e é o único dado que o
    nb3 tinha. O nb2 acumulava (`/home/.idesacumula`) e o painel mostrava
    "usado/amostrado"; isso se perdeu na reescrita, junto com o sentido do
    botão `resetcontaeditores`, que apagava um arquivo que ninguém escrevia.
    """
    dados = {}
    try:
        with open("/home/.nb3/editores") as fh:
            for linha in fh:
                chave, _, valor = linha.strip().partition("=")
                if chave and valor.isdigit():
                    dados[chave] = int(valor)
    except OSError:
        return None
    return dados or None

print(json.dumps({
    "operations": {
        "firewall": firewall(),
        "screen_lock": os.path.exists("/home/.nb3/locked"),
        "editors": editores(),
        "editors_time": acumulado(),
    }
}, ensure_ascii=False)[1:-1])
PY
