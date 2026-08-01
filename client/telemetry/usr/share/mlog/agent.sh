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

MAC=$(sed -n 's/.*BOOTIF=01-\([0-9a-f-]*\).*/\1/p' /proc/cmdline)
if [ -z "$MAC" ]; then
    MAC=$(ip -o link show | awk '$2 !~ /lo:/ {print $(NF-2); exit}' | tr ':' '-')
fi
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

log "iniciando (imagem=$IMAGEROOT mac=$MAC servidor=$NB_SERVER)"
telemetry_loop &
lock_watchdog &
commands_loop
