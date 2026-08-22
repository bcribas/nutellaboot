# shellcheck shell=sh
# Modo seed: SEGURA O BOOT no initrd servindo o cache por HTTP, com relatório
# ao vivo, até alguém apertar ENTER nesta máquina ou removê-la da lista de
# semeadores no configureitor (o heartbeat devolve released=t).
#
# O nb3 tentou deixar o webfsd sobreviver ao switch_root e semear com o
# sistema de pé — não funciona: o maratona-firewall bloqueia as conexões de
# entrada assim que sobe. Semear é coisa do initrd, como no nb2; a diferença
# é que aqui a saída não depende de teclado (liberação remota) e o registro
# tem TTL, então seeder morto expira sozinho do pool.
#
# Este é o único `read` de teclado do caminho de boot, e é deliberado: só
# roda com SEEDIMAGE=t (opt-in da sede), tem timeout de 1 s e sempre há
# saída desatendida pelo configureitor — a máquina nunca fica presa
# dependendo de alguém na frente dela.

NB_SEED_HEARTBEAT=${NB_SEED_HEARTBEAT:-60}
NB_SEED_LOG=${NB_SEED_LOG:-/run/nb3-seed.log}

# Uma linha de resumo a partir do log do webfsd (common log format:
# "IP - - [data] \"GET /arq HTTP/1.1\" 200 bytes").
nb_seed_report() {
    # $1 = segundos desde a última requisição atendida
    awk -v idle="${1:-0}" '
        ($9 == 200 || $9 == 206) { req++; ips[$1] = 1; bytes += $10 }
        END {
            peers = 0
            for (i in ips) peers++
            # %.0f e nunca %d: o awk do busybox trunca em 32 bits e a camada
            # base sozinha passa de 2 GiB (mesma armadilha da barra de
            # download)
            printf "reqs %.0f  machines %.0f  sent %.0f MB  idle %ss",
                req + 0, peers, bytes / 1048576, idle
        }' "$NB_SEED_LOG" 2> /dev/null
}

seedimage() {
    log_begin_msg "Getting ready to seed"
    # sem `head` no initrd (e o stuff roda dentro dele): o awk resolve sozinho
    MYIP=$(ip -4 -o addr show scope global | awk '{split($4, a, "/"); print a[1]; exit}')
    [ -z "$MYIP" ] && {
        nb_warn "no IP address available for seeding"
        return 1
    }
    printf ' ip=%s' "$MYIP"
    log_end_msg

    echo 'nogroup:x:65534:' > /etc/group
    echo 'root:x:0:0:root:/:/bin/sh' > /etc/passwd
    # o log fica FORA de $STORAGEDIR: tudo ali é servido por HTTP
    : > "$NB_SEED_LOG"
    /usr/bin/webfsd -p 80 -g nogroup -~ "$STORAGEDIR" -r "$STORAGEDIR" -L "$NB_SEED_LOG"

    _nbs_url="$NB_SERVER/boot/v3/$IMAGEROOT/seeders"
    _nbs_join=$(nb_get "$_nbs_url/join?ip=$MYIP")
    if printf '%s' "$_nbs_join" | grep -q '^accepted=f'; then
        # pool cheio não é erro: as primeiras máquinas da sala já semeiam
        nb_log "seeder pool is full - booting without seeding"
        killall webfsd 2> /dev/null
        return 0
    fi
    if ! printf '%s' "$_nbs_join" | grep -q '^accepted=t'; then
        nb_warn "could not join the seeder pool"
        killall -9 webfsd 2> /dev/null
        return 1
    fi
    nb_log "joined the seeder pool as $MYIP"

    nb_phase "SEEDING"
    nb_ui_text "This machine is seeding the image and will hold the boot here."
    nb_ui_dim "Press ENTER to stop seeding and finish booting, or remove this"
    nb_ui_dim "machine from the seeders list in the configureitor."

    _nbs_why=
    _nbs_seen=0
    _nbs_now=$(date +%s)
    _nbs_prev=0
    _nbs_last=$_nbs_now
    _nbs_hb=$_nbs_now
    while :; do
        if read -r -t 1 _nbs_key < /dev/console 2> /dev/null; then
            _nbs_why="ENTER pressed"
            break
        fi
        _nbs_now=$(date +%s)
        # console sem entrada (EOF imediato) não pode virar laço quente
        [ "$_nbs_now" = "$_nbs_prev" ] && sleep 1
        _nbs_prev=$_nbs_now

        _nbs_cur=$(wc -l < "$NB_SEED_LOG" 2> /dev/null || echo 0)
        if [ "$_nbs_cur" -gt "$_nbs_seen" ]; then
            _nbs_seen=$_nbs_cur
            _nbs_last=$_nbs_now
        fi
        printf '\r  %s  [ENTER stops]   ' "$(nb_seed_report $((_nbs_now - _nbs_last)))"

        if [ $((_nbs_now - _nbs_hb)) -ge "$NB_SEED_HEARTBEAT" ]; then
            _nbs_hb=$_nbs_now
            # resposta vazia (rede piscou) NÃO derruba o seed: o TTL do
            # servidor é 3x o heartbeat, há margem para tentar de novo
            if nb_get "$_nbs_url/heartbeat?ip=$MYIP" | grep -q '^released=t'; then
                _nbs_why="released from the configureitor"
                break
            fi
        fi
    done
    printf '\n'
    nb_log "seeding finished ($_nbs_why)"
    nb_get "$_nbs_url/leave?ip=$MYIP" > /dev/null 2>&1
    killall webfsd 2> /dev/null
    return 0
}
