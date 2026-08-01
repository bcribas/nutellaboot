# Inventário de hardware — fragmento JSON (sem chaves externas).
python3 - <<'PY'
import json, os, re

def read(path, default=""):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return default

cpuinfo = read("/proc/cpuinfo")
meminfo = read("/proc/meminfo")
model = next((l.split(":", 1)[1].strip() for l in cpuinfo.splitlines()
              if l.startswith("model name")), "")
memtotal = next((int(l.split()[1]) for l in meminfo.splitlines()
                 if l.startswith("MemTotal")), 0)

print(json.dumps({
    "hwinfo": {
        "processor": model,
        "cores": os.cpu_count(),
        "memtotal_mb": memtotal // 1024,
        "machine_id": read("/etc/machine-id").strip(),
        "boot_id": read("/home/.machine-id-boot").strip(),
        "image": read("/etc/imageroot-icpc").strip(),
    }
}, ensure_ascii=False)[1:-1])
PY
