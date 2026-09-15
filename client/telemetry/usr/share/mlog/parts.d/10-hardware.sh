# Inventário de hardware — fragmento JSON (sem chaves externas).
#
# Caminhos por variável de ambiente para o teste (tests/test_camada_telemetria.py)
# apontar para arquivos falsos; em campo valem os padrões.
python3 - <<'PY'
import json, os, socket, time

DMI = os.environ.get("NB_DMI_DIR", "/sys/class/dmi/id")
UPTIME = os.environ.get("NB_PROC_UPTIME", "/proc/uptime")
MAC_ARQ = os.environ.get("NB_MAC_ARQ", "/etc/mac-icpc")

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
try:
    uptime = int(float(read(UPTIME).split()[0]))
except (ValueError, IndexError):
    uptime = None

hw = {
    "processor": model,
    "cores": os.cpu_count(),
    "memtotal_mb": memtotal // 1024,
    "machine_id": read("/etc/machine-id").strip(),
    "boot_id": read("/home/.machine-id-boot").strip(),
    "image": read("/etc/imageroot-icpc").strip(),
    # a chave da máquina (MAC estável escolhido pelo initrd) e a identidade de
    # hardware que não depende de clone de disco
    "mac": read(MAC_ARQ).strip(),
    "hostname": socket.gethostname(),
    "dmi_uuid": read(f"{DMI}/product_uuid").strip().lower(),
    "product_name": read(f"{DMI}/product_name").strip(),
    "product_vendor": read(f"{DMI}/sys_vendor").strip(),
}
if uptime is not None:
    hw["uptime_s"] = uptime
    hw["last_boot"] = int(time.time()) - uptime
# campo vazio não vai: no servidor "ausente" é opcional, "" é um valor
hw = {k: v for k, v in hw.items() if v not in ("", None)}
print(json.dumps({"hwinfo": hw}, ensure_ascii=False)[1:-1])
PY
