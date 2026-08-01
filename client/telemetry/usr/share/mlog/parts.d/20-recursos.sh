# Uso de recursos e sinais de alerta — fragmento JSON.
python3 - <<'PY'
import json

def meminfo():
    out = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            out[key] = int(rest.split()[0])
    return out

mi = meminfo()
total = mi.get("MemTotal", 1)
disp = mi.get("MemAvailable", 0)
swap_total = mi.get("SwapTotal", 0)
swap_livre = mi.get("SwapFree", 0)
load1, load5, load15 = open("/proc/loadavg").read().split()[:3]

usados = total - disp
alerta = []
if usados / total > 0.85:
    alerta.append("memoria")
if swap_total and (swap_total - swap_livre) / swap_total > 0.05:
    alerta.append("swap")
if float(load1) > 4.0:
    alerta.append("carga")

print(json.dumps({
    "sysresources": {
        "mem_used_mb": usados // 1024,
        "mem_total_mb": total // 1024,
        "mem_pct": round(100 * usados / total),
        "swap_used_mb": (swap_total - swap_livre) // 1024,
        "swap_total_mb": swap_total // 1024,
        "loadavg": [float(load1), float(load5), float(load15)],
        "alerts": alerta,
    }
}, ensure_ascii=False)[1:-1])
PY
