#!/bin/bash
# Agente do NutellaBoot 3 (sucessor do envia.sh).
#
# Dois laços independentes:
#   comandos   — long-poll: uma requisição fica pendurada até 25 s e volta no
#                instante em que o servidor recebe um comando. Latência de
#                segundos com ~1 requisição por máquina a cada 25 s.
#                (O envia.sh fazia polling a cada 5-30 s e ainda somava o
#                atraso configurado no servidor: passava de 30 s até travar.)
#   telemetria — envia o estado da máquina a cada ~45 s.
#
# Configuração vem de /etc/.nb3, escrito pelo stuff durante o boot.

set -u
. /etc/.nb3

API="$NB_SERVER/api/v1/images/$IMAGEROOT"
MACHINE_HDR="X-NB-Machine-Key: $NB_MACHINE_KEY"
STATE_DIR=/home/.nb3
mkdir -p "$STATE_DIR"

# Identidade da máquina para o servidor. O formato é `aa-bb-cc-dd-ee-ff`, e o
# servidor recusa qualquer outra coisa com 400.
#
# Isto lia `ip -o link show | awk '{print $(NF-2)}'`: contagem de campos a
# partir do fim de uma linha cujo formato muda (com `altname`, com `permaddr`,
# e com a barra invertida que o `ip -o` usa de separador virando parte de um
# campo). O resultado real numa máquina de teste foi `enp0s3\` — o NOME da
# interface. Todas as requisições do agente levaram 400 por 30 horas seguidas,
# e como o `status` também era recusado a máquina nunca chegava a existir: o
# hotconfig ficava vazio, sem nenhum sinal de que alguém estava tentando.
#
# Agora o valor vem de onde ele É o valor, sem formatação para interpretar.
NB3_SYSFS_NET=${NB3_SYSFS_NET:-/sys/class/net}

nb3_mac_de() {
    _end=$(cat "$NB3_SYSFS_NET/$1/address" 2> /dev/null) || return 1
    case "$_end" in
        "" | 00:00:00:00:00:00) return 1 ;;
    esac
    printf '%s' "$_end" | tr 'A-F:' 'a-f-'
}

nb3_detect_mac() {
    # 1. a interface da rota padrão: é por ela que se fala com o servidor
    _dev=$(ip -o route show default 2> /dev/null |
        awk '{for (i = 1; i < NF; i++) if ($i == "dev") {print $(i + 1); exit}}')
    if [ -n "${_dev:-}" ] && nb3_mac_de "$_dev"; then
        return 0
    fi
    # 2. a primeira física com endereço (ordem alfabética, determinística)
    for _cam in "$NB3_SYSFS_NET"/*; do
        _nome=${_cam##*/}
        [ "$_nome" = lo ] && continue
        # sem `device` é virtual (docker0, veth, bridge): o MAC é sorteado
        [ -e "$_cam/device" ] || continue
        nb3_mac_de "$_nome" && return 0
    done
    return 1
}

MAC=$(sed -n 's/.*BOOTIF=01-\([0-9a-f-]*\).*/\1/p' /proc/cmdline)
[ -n "$MAC" ] || MAC=$(nb3_detect_mac) || MAC=""
export MAC

log() { logger -t nb3-agent "$*"; }

curl_api() {
    curl --silent --show-error --max-time "${2:-30}" \
        --header "$MACHINE_HDR" "${@:3}" "$API/$1"
}

# --- comandos ---------------------------------------------------------------

run_command() {
    local id=$1 cmd=$2 args=$3 status=done
    if ! type -t "cmd_$cmd" > /dev/null; then
        log "comando desconhecido: $cmd"
        status=unknown
    else
        "cmd_$cmd" "$args" || status=failed
    fi
    curl_api "machines/$MAC/commands/$id/ack" 15 \
        -X POST -H 'Content-Type: application/json' \
        --data "{\"status\":\"$status\"}" > /dev/null
}

commands_loop() {
    while :; do
        resp=$(curl_api "machines/$MAC/commands?wait=25" 40)
        if [ -z "$resp" ]; then
            sleep 5
            continue
        fi
        echo "$resp" | nb3-json commands | while IFS=$'\t' read -r id cmd args; do
            [ -n "$id" ] && run_command "$id" "$cmd" "$args"
        done
        # o estado de bloqueio vem junto: garante a tela mesmo se o comando
        # tiver se perdido (rede caindo no meio, agente reiniciado)
        if echo "$resp" | nb3-json locked | grep -q true; then
            ensure_locked
        else
            ensure_unlocked
        fi
    done
}

# --- tela de bloqueio -------------------------------------------------------
#
# Matar o processo NÃO destrava: enquanto o estado for "locked", o agente
# relança a tela. (No nb2 o desbloqueio era literalmente `pkill maratona-wait`.)

ensure_locked() {
    touch "$STATE_DIR/locked"
    pgrep -f maratona-wait > /dev/null && return 0
    log "abrindo a tela de bloqueio"
    su icpc -c "DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1001 \
        /usr/bin/maratona-wait" &
    disown
}

ensure_unlocked() {
    rm -f "$STATE_DIR/locked"
    pgrep -f maratona-wait > /dev/null || return 0
    log "fechando a tela de bloqueio"
    pkill -f maratona-wait
}

lock_watchdog() {
    # Se o competidor matar a janela, ela volta em no máximo 3 s.
    while :; do
        [ -e "$STATE_DIR/locked" ] && ensure_locked
        sleep 3
    done
}

cmd_donottouch() { ensure_locked; }
cmd_cantouch() { ensure_unlocked; }
cmd_cleanhomenow() { echo cleannow > /dev/shm/icpc-clean-homed.fifo; }
cmd_mlreboot() { (sleep 20 && reboot) & disown; }
cmd_mlpoweroff() { (sleep 20 && poweroff) & disown; }
cmd_enablefirewall() { systemctl start maratona-firewall.service; }
cmd_disablefirewall() { systemctl stop maratona-firewall.service; }
cmd_resetcontaeditores() { rm -f "$STATE_DIR/editores"; }
cmd_precontest() {
    cmd_cleanhomenow
    cmd_enablefirewall
    ensure_locked
}

# --- telemetria -------------------------------------------------------------

collect() {
    local partes=()
    for parte in /usr/share/mlog/parts.d/*.sh; do
        [ -r "$parte" ] || continue
        partes+=("$(bash "$parte" 2> /dev/null)")
    done
    printf '{%s}\n' "$(
        IFS=,
        echo "${partes[*]}"
    )"
}

telemetry_loop() {
    while :; do
        collect > "$STATE_DIR/status.json"
        curl_api "machines/$MAC/status" 20 \
            -X POST -H 'Content-Type: application/json' \
            --data @"$STATE_DIR/status.json" > /dev/null
        sleep $((40 + RANDOM % 20))
    done
}

# --- logs (journal do kernel e do sistema) ----------------------------------
#
# O nb2 tinha isto e se perdeu na reescrita: journal do boot inteiro na
# partida e o incremento a cada 5 minutos. É o que responde "o que aconteceu
# naquela máquina às 14h32" depois que a prova acabou.
#
# NÃO vai em parts.d/: aquela saída é concatenada dentro do status.json, que é
# sobrescrito a cada 45 s. Log precisa de histórico, então tem canal próprio.

LOG_CURSOR="$STATE_DIR/journal.cursor"
LOG_MAX_BYTES=${NB_LOG_MAX_BYTES:-524288}
LOG_INTERVALO=${NB_LOG_INTERVAL:-300}

# Corta antes de sair da máquina: o servidor recusa acima de 1 MiB, e mandar
# para levar 413 é gastar rede da sala à toa.
send_log() {
    local origem=$1 texto=$2
    [ -n "$texto" ] || return 0
    printf '%s' "$texto" | tail -c "$LOG_MAX_BYTES" > "$STATE_DIR/journal.part"
    curl_api "machines/$MAC/logs?origem=$origem" 30 \
        -X POST -H 'Content-Type: text/plain' \
        --data-binary @"$STATE_DIR/journal.part" > /dev/null
    rm -f "$STATE_DIR/journal.part"
}

# --cursor-file marca onde parou e continua exatamente dali: não repete nem
# perde linha entre um envio e outro. Sem ele (journalctl antigo), cai para a
# janela de tempo, que pode duplicar nas bordas.
journal_incremento() {
    if journalctl --cursor-file="$LOG_CURSOR" -n 0 > /dev/null 2>&1; then
        journalctl --cursor-file="$LOG_CURSOR" --no-pager 2> /dev/null
    elif command -v journalctl > /dev/null 2>&1; then
        journalctl -S "-${LOG_INTERVALO}s" --no-pager 2> /dev/null
    else
        dmesg -T 2> /dev/null
    fi
}

logs_loop() {
    # Na partida vai o boot inteiro: é onde estão os erros de hardware e de
    # driver que explicam uma máquina que não sobe direito.
    if command -v journalctl > /dev/null 2>&1; then
        rm -f "$LOG_CURSOR"
        send_log boot "$(journalctl -b --no-pager 2> /dev/null | tail -n 5000)"
        journalctl --cursor-file="$LOG_CURSOR" -n 0 > /dev/null 2>&1
    else
        send_log boot "$(dmesg -T 2> /dev/null | tail -n 5000)"
    fi

    while :; do
        sleep "$LOG_INTERVALO"
        # incremento vazio não vira requisição: numa sala parada isso é a
        # diferença entre nada e 100 requisições a cada 5 minutos
        send_log journal "$(journal_incremento)"
    done
}

# --- eventos de USB --------------------------------------------------------
#
# A regra em /etc/udev/rules.d/99-nb3-usb.rules enfileira um arquivo por
# dispositivo conectado; aqui a fila é esvaziada e enviada NA HORA. Um pendrive
# que fica dez segundos na máquina precisa chegar ao fiscal mesmo depois de
# removido — por isso o alerta não sai da tela sozinho, só quando alguém
# dispensa.

USB_FILA="$STATE_DIR/usb-events"

send_usb_event() {
    local arq=$1 kind="" vendor="" detail=""
    # shellcheck disable=SC1090
    while IFS='=' read -r chave valor; do
        case "$chave" in
            kind) kind=$valor ;;
            vendor) vendor=$valor ;;
            detail) detail=$valor ;;
        esac
    done < "$arq"
    [ -n "$kind" ] || return 0
    log "dispositivo USB detectado: $kind $vendor $detail"
    curl_api "machines/$MAC/events" 15 \
        -X POST -H 'Content-Type: application/json' \
        --data "$(nb3-json --escape kind "$kind" vendor "$vendor" detail "$detail")" \
        > /dev/null
}

usb_loop() {
    mkdir -p "$USB_FILA"
    # O que já estava conectado quando a máquina ligou: o udev não dispara
    # "add" para isso, e ligar com o pendrive espetado é justamente o jeito
    # mais fácil de escapar da regra.
    for dev in /sys/block/*/removable; do
        [ -r "$dev" ] || continue
        [ "$(cat "$dev")" = 1 ] || continue
        nome=$(basename "$(dirname "$dev")")
        # o pendrive de boot é o único removível esperado
        if ! lsblk -no LABEL "/dev/$nome" 2> /dev/null | grep -q NB3CFG; then
            printf 'kind=usb.storage\nvendor=%s\ndetail=present at boot\n' \
                "$(cat "/sys/block/$nome/device/model" 2> /dev/null || echo "$nome")" \
                > "$USB_FILA/boot-$nome"
        fi
    done

    while :; do
        for arq in "$USB_FILA"/*; do
            [ -f "$arq" ] || continue
            send_usb_event "$arq" && rm -f "$arq"
        done
        sleep 1
    done
}

> "$STATE_DIR/mac" printf '%s\n' "$MAC"

# Sem MAC válido não há o que reportar: o servidor recusa tudo com 400 e a
# máquina some do painel. Melhor parar aqui, dizendo o porquê, do que bater no
# servidor a cada 25 s para sempre.
case "$MAC" in
    [0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-*) ;;
    *)
        log "SEM MAC VALIDO (encontrei '${MAC:-vazio}') — o agente nao vai reportar."
        log "confira as interfaces de rede em $NB3_SYSFS_NET"
        exit 1
        ;;
esac

log "iniciando (imagem=$IMAGEROOT mac=$MAC servidor=$NB_SERVER)"
telemetry_loop &
logs_loop &
usb_loop &
lock_watchdog &
commands_loop
