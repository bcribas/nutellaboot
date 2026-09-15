# Uso de recursos e sinais de alerta — fragmento JSON.
#
# Além de memória, swap e carga: a PRESSÃO (PSI, o que o kernel mede antes de
# paginar — swap é só a ponta visível), os OOM kills (o evento que o time
# sente) e a ociosidade da sessão gráfica (separa máquina abandonada de
# máquina em uso melhor do que "algum editor aberto"). Cada um fica AUSENTE
# quando não dá para medir: o servidor trata como opcional.
python3 - <<'PY'
import json, os, pwd, re, subprocess, time

PRESSURE = os.environ.get("NB_PROC_PRESSURE", "/proc/pressure")
VMSTAT = os.environ.get("NB_PROC_VMSTAT", "/proc/vmstat")
MEMINFO = os.environ.get("NB_PROC_MEMINFO", "/proc/meminfo")
LOADAVG = os.environ.get("NB_PROC_LOADAVG", "/proc/loadavg")

def meminfo():
    out = {}
    with open(MEMINFO) as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            out[key] = int(rest.split()[0])
    return out

def psi(recurso):
    """avg60 da linha `some` de /proc/pressure/<recurso>; None sem PSI."""
    try:
        with open(f"{PRESSURE}/{recurso}") as fh:
            for linha in fh:
                if linha.startswith("some "):
                    campos = dict(c.split("=", 1) for c in linha.split()[1:])
                    return float(campos["avg60"])
    except (OSError, KeyError, ValueError):
        pass
    return None

def oom_kills():
    try:
        with open(VMSTAT) as fh:
            for linha in fh:
                if linha.startswith("oom_kill "):
                    return int(linha.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None

def idle_s():
    """Segundos desde a última tecla/mouse na sessão do icpc.

    Sem X11 tools na imagem: 1) o IdleMonitor do Mutter, que é o que o
    próprio GNOME usa para apagar a tela (X11 ou Wayland), perguntado no bus
    da sessão do icpc; 2) o IdleHint do logind, que só vira `yes` depois do
    idle-delay do GNOME — grosseiro, mas não depende de o shell responder;
    3) ausente.
    """
    try:
        uid = pwd.getpwnam("icpc").pw_uid
    except KeyError:
        uid = 1001
    try:
        r = subprocess.run(
            ["runuser", "-u", "icpc", "--", "env",
             f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
             "gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
             "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
             "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"],
            capture_output=True, text=True, timeout=5)
        m = re.search(r"uint64 (\d+)", r.stdout)
        if m:
            return int(m.group(1)) // 1000
    except Exception:
        pass
    try:
        r = subprocess.run(["loginctl", "show-user", "icpc", "-p", "Sessions", "--value"],
                           capture_output=True, text=True, timeout=5)
        for sessao in r.stdout.split():
            r2 = subprocess.run(["loginctl", "show-session", sessao, "-p", "IdleHint",
                                 "-p", "IdleSinceHintMonotonic", "--value"],
                                capture_output=True, text=True, timeout=5)
            hint, desde = (r2.stdout.split() + ["", ""])[:2]
            if hint == "yes" and desde.isdigit() and int(desde) > 0:
                return int(time.clock_gettime(time.CLOCK_MONOTONIC) - int(desde) / 1e6)
    except Exception:
        pass
    return None

mi = meminfo()
total = mi.get("MemTotal", 1)
disp = mi.get("MemAvailable", 0)
swap_total = mi.get("SwapTotal", 0)
swap_livre = mi.get("SwapFree", 0)
load1, load5, load15 = open(LOADAVG).read().split()[:3]

usados = total - disp
alerta = []
if usados / total > 0.85:
    alerta.append("memoria")
if swap_total and (swap_total - swap_livre) / swap_total > 0.05:
    alerta.append("swap")
if float(load1) > 4.0:
    alerta.append("carga")

res = {
    "mem_used_mb": usados // 1024,
    "mem_total_mb": total // 1024,
    "mem_pct": round(100 * usados / total),
    "swap_used_mb": (swap_total - swap_livre) // 1024,
    "swap_total_mb": swap_total // 1024,
    "loadavg": [float(load1), float(load5), float(load15)],
    "alerts": alerta,
}
for nome, valor in (("psi_mem", psi("memory")), ("psi_cpu", psi("cpu")), ("psi_io", psi("io")),
                    ("oom_kills", oom_kills()), ("idle_s", idle_s())):
    if valor is not None:
        res[nome] = valor

print(json.dumps({"sysresources": res}, ensure_ascii=False)[1:-1])
PY
