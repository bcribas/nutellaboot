#!/bin/sh
# Chamado pelo udev quando um dispositivo USB e conectado.
#
# Regra de ouro: sai rapido. Este script roda DENTRO da fila de eventos do
# udev; qualquer coisa que espere rede aqui atrasa a enumeracao de dispositivos
# da maquina inteira. Ele so grava um arquivo e volta — quem fala com o
# servidor e o agente, que varre esta fila a cada segundo.
#
# Uso: usb-event.sh TIPO MODELO FABRICANTE DETALHE

set -u

FILA=/home/.nb3/usb-events
mkdir -p "$FILA" 2> /dev/null || exit 0

TIPO=${1:-other}
MODELO=${2:-}
FABRICANTE=${3:-}
DETALHE=${4:-}

# udev troca espaco por underscore nas propriedades; devolver o espaco deixa o
# texto legivel na tela do fiscal
limpa() {
    printf '%s' "$1" | tr '_' ' ' | tr -cd '[:print:]' | cut -c1-60
}

ARQ="$FILA/$(date +%s)-$$"
{
    echo "kind=usb.$TIPO"
    echo "vendor=$(limpa "$FABRICANTE") $(limpa "$MODELO")"
    echo "detail=$(limpa "$DETALHE")"
} > "$ARQ.tmp" 2> /dev/null && mv "$ARQ.tmp" "$ARQ" 2> /dev/null

exit 0
