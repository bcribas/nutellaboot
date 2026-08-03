#!/bin/sh
# Chamado pelo udev quando um dispositivo USB e conectado.
#
# Regra de ouro: sai rapido. Este script roda DENTRO da fila de eventos do
# udev; qualquer coisa que espere rede aqui atrasa a enumeracao de dispositivos
# da maquina inteira. Ele so grava um arquivo e volta — quem fala com o
# servidor e o agente, que varre esta fila a cada segundo.
#
# Uso: usb-event.sh TIPO MODELO FABRICANTE DETALHE
#
# TIPO vira o `kind` do alerta: storage, phone, network (todos `usb.*`) e cd
# (`media.cd`, disco inserido num drive optico — que pode ser interno).

set -u

FILA=/home/.nb3/usb-events
mkdir -p "$FILA" 2> /dev/null || exit 0

TIPO=${1:-other}
MODELO=${2:-}
FABRICANTE=${3:-}
DETALHE=${4:-}

# O pendrive de BOOT nao alarma: em muitas salas ele fica espetado o dia todo.
# A regra do udev exclui pela label NB3CFG, mas a label so existe no no da
# PARTICAO — o no do disco inteiro (sdb, sem label) escapava e alarmava a cada
# boot. Aqui da para olhar as particoes filhas, que e o que o `lsblk` sem -d
# faz, e resolver isso num lugar so.
case "$TIPO" in
    storage)
        if [ -b "/dev/$DETALHE" ] &&
            lsblk -no LABEL "/dev/$DETALHE" 2> /dev/null | grep -q '^NB3CFG$'; then
            exit 0
        fi
        ;;
esac

# `media.cd` e coisa de midia, nao de USB; o resto e barramento USB
case "$TIPO" in
    cd) KIND=media.cd ;;
    *) KIND=usb.$TIPO ;;
esac

# udev troca espaco por underscore nas propriedades; devolver o espaco deixa o
# texto legivel na tela do fiscal
limpa() {
    printf '%s' "$1" | tr '_' ' ' | tr -cd '[:print:]' | cut -c1-60
}

ARQ="$FILA/$(date +%s)-$$"
{
    echo "kind=$KIND"
    echo "vendor=$(limpa "$FABRICANTE") $(limpa "$MODELO")"
    echo "detail=$(limpa "$DETALHE")"
} > "$ARQ.tmp" 2> /dev/null && mv "$ARQ.tmp" "$ARQ" 2> /dev/null

exit 0
