# Relógio do agente — chave de topo do status, para o servidor medir o desvio
# entre o relógio da máquina e o dele: uma máquina com hora errada desloca a
# série inteira no tempo da prova sem ninguém notar, e é a mesma máquina cujo
# certificado pode falhar no próximo boot.
python3 - <<'PY'
import json, time
print(json.dumps({"t_agent": int(time.time())})[1:-1])
PY
