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

print(json.dumps({
    "operations": {
        "firewall": firewall(),
        "screen_lock": os.path.exists("/home/.nb3/locked"),
        "editors": editores(),
    }
}, ensure_ascii=False)[1:-1])
PY
