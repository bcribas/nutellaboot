#!/bin/bash
# Agente do NutellaBoot 3 (sucessor do envia.sh).
#
# Dois laços independentes:
#   comandos   — long-poll: uma requisição fica pendurada até 25 s e volta no
#                instante em que o servidor recebe um comando. Latência de
#                segundos com ~1 requisição por máquina a cada 25 s.
#                (O envia.sh fazia polling a cada 5-30 s e ainda somava o
#                atraso configurado no servidor: passava de 30 s até travar.)
#   telemetria — envia o estado da máquina a cada 40 a 59 s (jitter de propósito).
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

# A chave é o MAC ESTÁVEL escolhido pelo initrd (stuff/10-identidade.sh), não
# o da placa por onde bootou: a mesma máquina boota por cabo, wifi ou USB e
# precisa continuar sendo a mesma máquina no painel. O BOOTIF e a detecção
# ficam de reserva para um initrd antigo, que não grava o arquivo.
NB3_MAC_ARQ=${NB3_MAC_ARQ:-/etc/mac-icpc}

nb3_mac_do_boot() {
    _m=$(tr -d '[:space:]' < "$NB3_MAC_ARQ" 2> /dev/null) || return 1
    case "$_m" in
        [0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]*) printf '%s' "$_m" ;;
        *) return 1 ;;
    esac
}

MAC=$(nb3_mac_do_boot) || MAC=$(sed -n 's/.*BOOTIF=01-\([0-9a-f-]*\).*/\1/p' /proc/cmdline)
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
            # o destravamento local pela senha de emergência vale até o
            # servidor mudar de ideia por um comando novo (donottouch limpa o
            # override) ou destravar — o estado repetido não retrava
            [ -e "$STATE_DIR/local-unlock" ] || ensure_locked
        else
            rm -f "$STATE_DIR/local-unlock"
            ensure_unlocked
        fi
    done
}

# --- tela de bloqueio -------------------------------------------------------
#
# Matar o processo NÃO destrava: enquanto o estado for "locked", o agente
# relança a tela. (No nb2 o desbloqueio era literalmente `pkill maratona-wait`.)
#
# QUEM CONFERE A SENHA DE EMERGÊNCIA É O AGENTE, não a tela. A tela roda como
# icpc e o hash mora em /etc/.nb3, 0600 root, junto com a chave de máquina —
# dar o arquivo à tela seria dar a chave ao competidor. A tela só coleta as
# teclas e as escreve no FIFO; aqui (root) o hash é conferido, e no acerto a
# tela é fechada por quem sempre a fechou (ensure_unlocked). Antes a tela
# tentava ler o hash, falhava em silêncio, e NENHUMA senha destravava.

NB_UNLOCK_FIFO=${NB_UNLOCK_FIFO:-/run/nb3-unlock.fifo}

ensure_locked() {
    touch "$STATE_DIR/locked"
    pgrep -f maratona-wait > /dev/null && return 0
    log "abrindo a tela de bloqueio"
    # a tela recebe o que precisa por argumento e ambiente — ela NÃO lê
    # /etc/.nb3 (não pode: 0600 root). A chave de boot vai por ambiente, não
    # por argumento, para não aparecer no ps de outros usuários.
    su icpc -c "DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1001 \
        NB_BOOT_KEY='$NB_BOOT_KEY' \
        /usr/bin/maratona-wait --image '$IMAGEROOT' --server '$NB_SERVER' \
        --theme '${NB_LOCK_THEME:-classico}' --lang '${NB_LANGUAGE:-pt}' \
        --mac '$MAC' --fifo '$NB_UNLOCK_FIFO'" 2>&1 | logger -t nb3-lock &
    # o que a tela disser vai para o journal: o agente nasce com o stderr no
    # /dev/null, e uma tela que morria em 1 s ficou uma semana sem explicação.
    # A tag NÃO pode conter "maratona-wait": o pgrep -f casaria o logger.
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

# salt$sha256(salt+senha) — o formato que config.hash_password grava no
# servidor. Shell puro de propósito: dá para testar sem gjs nem GTK.
verify_lock_password() {
    _hash=${NB_LOCK_FALLBACK_HASH:-}
    _typed=$1
    [ -n "$_hash" ] || return 1
    case "$_hash" in *\$*) ;; *) return 1 ;; esac
    _salt=${_hash%%\$*}
    _want=${_hash#*\$}
    _got=$(printf '%s' "$_salt$_typed" | sha256sum | awk '{print $1}')
    [ "$_got" = "$_want" ]
}

setup_unlock_fifo() {
    rm -f "$NB_UNLOCK_FIFO"
    mkfifo -m 620 "$NB_UNLOCK_FIFO" || return 1
    # o grupo icpc escreve; ninguém mais lê (620: dono root lê/escreve)
    chown root:icpc "$NB_UNLOCK_FIFO" 2> /dev/null || chmod 622 "$NB_UNLOCK_FIFO"
}

unlock_listener() {
    while :; do
        # um FIFO sem escritor bloqueia o read — é o comportamento certo aqui
        if IFS= read -r _pass < "$NB_UNLOCK_FIFO"; then
            if verify_lock_password "$_pass"; then
                log "destravado pela senha de emergência"
                # o override local segura o destravamento contra o long-poll:
                # sem ele, o servidor (que continua 'locked') retravaria a tela
                # em segundos e a senha certa viraria um piscar de olhos
                touch "$STATE_DIR/local-unlock"
                ensure_unlocked
            else
                log "senha de emergência recusada"
            fi
        fi
        _pass=""
    done
}

cmd_donottouch() {
    # comando NOVO de travar anula o destravamento local: a organização
    # retrava por cima, e vale ela
    rm -f "$STATE_DIR/local-unlock"
    ensure_locked
}
cmd_cantouch() {
    rm -f "$STATE_DIR/local-unlock"
    ensure_unlocked
}
cmd_cleanhomenow() { echo cleannow > /dev/shm/icpc-clean-homed.fifo; }
cmd_mlreboot() { (sleep 20 && reboot) & disown; }
cmd_mlpoweroff() { (sleep 20 && poweroff) & disown; }
cmd_enablefirewall() { systemctl start maratona-firewall.service; }
cmd_disablefirewall() { systemctl stop maratona-firewall.service; }
cmd_resetcontaeditores() { rm -f "$STATE_DIR/editores"; }
cmd_precontest() {
    cmd_cleanhomenow
    cmd_enablefirewall
    # zerar a contagem faz parte de "começar a prova": o que interessa no
    # relatório é o uso DURANTE a prova, não o da preparação da sala. O nb2
    # fazia isso e o nb3 tinha perdido.
    cmd_resetcontaeditores
    cmd_donottouch
}

# --- contagem de uso dos editores -------------------------------------------
#
# O instantâneo de `parts.d/30-operacoes.sh` diz o que está aberto no momento
# da amostra. Para responder "quanto o time usou cada editor" é preciso somar
# ao longo do tempo, e é isso que o nb2 fazia em /home/.idesacumula.
#
# Fica em arquivo (e não em memória) porque o agente pode ser reiniciado no
# meio da prova; e é o mesmo arquivo que o `resetcontaeditores` apaga.

EDITORES_ARQ="$STATE_DIR/editores"
EDITORES_INTERVALO=${NB_EDITORES_INTERVAL:-60}
EDITORES_LISTA="emacs vim geany clion code pycharm idea gedit codeblocks sublime"

# Uma passada da contagem (separada do laço para ser testável).
editors_tick() {
    abertos=$(ps -U icpc -o comm= 2> /dev/null | tr 'A-Z' 'a-z')
    # `since` é quando a contagem começou: o resetcontaeditores apaga o
    # arquivo e a próxima passada recomeça daqui — é o que diz "desde o
    # precontest", sem o qual o acumulado não tem data (o MOJ viu 7.972
    # minutos e nenhuma)
    since=$(sed -n 's/^since=//p' "$EDITORES_ARQ" 2> /dev/null | sed -n 1p)
    # `total` é o denominador: sem ele, "vim=142" não diz se são 142 de 150
    # amostras ou de 1000
    {
        echo "since=${since:-$(date +%s)}"
        for ed in $EDITORES_LISTA; do
            atual=$(sed -n "s/^$ed=//p" "$EDITORES_ARQ" 2> /dev/null | sed -n 1p)
            case "$abertos" in
                *"$ed"*) atual=$((${atual:-0} + 1)) ;;
                *) atual=${atual:-0} ;;
            esac
            [ "$atual" -gt 0 ] && echo "$ed=$atual"
        done
        total=$(sed -n "s/^total=//p" "$EDITORES_ARQ" 2> /dev/null | sed -n 1p)
        echo "total=$((${total:-0} + 1))"
    } > "$EDITORES_ARQ.tmp" && mv "$EDITORES_ARQ.tmp" "$EDITORES_ARQ"
}

editors_loop() {
    while :; do
        sleep "$EDITORES_INTERVALO"
        editors_tick
    done
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
# sobrescrito a cada ~50 s. Log precisa de histórico, então tem canal próprio.

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

# O que ja estava conectado quando o agente sobe nao e alerta. O alerta e
# de MUDANCA de estado — alguem espetou algo durante a prova —, e o que a fila
# tem antes do agente existir e o coldplug do boot: o udev reemite `add` para
# todo dispositivo presente, inclusive o pendrive de boot e o leitor de
# cartao da maquina. Uma varredura de "presente no boot" alarmava isso em
# toda sala com pendrive espetado o dia todo, e o fiscal parava de olhar a
# faixa vermelha.
usb_descarta_estado_inicial() {
    mkdir -p "$USB_FILA"
    for arq in "$USB_FILA"/*; do
        [ -f "$arq" ] || continue
        log "USB ja conectado no boot, sem alerta: $(sed -n 's/^vendor=//p' "$arq" | sed -n 1p)"
        rm -f "$arq"
    done
}

usb_loop() {
    usb_descarta_estado_inicial
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
setup_unlock_fifo && unlock_listener &
telemetry_loop &
logs_loop &
usb_loop &
editors_loop &
lock_watchdog &
commands_loop
