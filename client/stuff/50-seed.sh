# shellcheck shell=sh
# Seeding P2P: serve o cache local por HTTP e mantém o registro vivo.
#
# No nb2 a máquina "estacionava" em `iftop -t` para seguir semeando e só saía
# do pool quando alguém apertava q — se ela morresse, o IP ficava no pool para
# sempre e 1/N dos boots caía num seeder morto. Aqui o registro tem TTL: um
# heartbeat em background renova enquanto a máquina viver, e o servidor expira
# sozinho quem parar de responder.

NB_SEED_HEARTBEAT=${NB_SEED_HEARTBEAT:-60}

seedimage() {
    log_begin_msg "Preparando para semear"
    MYIP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n1)
    [ -z "$MYIP" ] && {
        nb_warn "sem IP para semear"
        return 1
    }
    printf ' ip=%s' "$MYIP"
    log_end_msg

    echo 'nogroup:x:65534:' > /etc/group
    echo 'root:x:0:0:root:/:/bin/sh' > /etc/passwd
    /usr/bin/webfsd -p 80 -g nogroup -~ "$STORAGEDIR" -r "$STORAGEDIR"

    _url="$NB_SERVER/boot/v3/$IMAGEROOT/seeders"
    if ! nb_get "$_url/join?ip=$MYIP&pw=$NB_MACHINE_KEY" | grep -q ok; then
        nb_warn "não foi possível entrar no pool de seeders"
        killall -9 webfsd 2>/dev/null
        return 1
    fi
    nb_log "no pool de seeders como $MYIP"

    # Heartbeat em background: mantém a entrada viva enquanto a máquina estiver de pé.
    (
        while :; do
            sleep "$NB_SEED_HEARTBEAT"
            nb_get "$_url/heartbeat?ip=$MYIP&pw=$NB_MACHINE_KEY" > /dev/null 2>&1
        done
    ) &

    nb_warn "Esta máquina está semeando a imagem para as outras — deixe-a ligada"
    return 0
}
