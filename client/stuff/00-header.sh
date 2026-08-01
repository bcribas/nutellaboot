# shellcheck shell=sh
# Base do stuff v3: logging e política de erro.
#
# REGRA DE OURO: nenhuma função deste script pode chamar `read`. Máquina de
# prova boota sozinha; erro que espera humano é erro que trava a sala.
# Use nb_fatal (mostra, espera, reinicia) ou nb_warn (segue em frente).

NB_CA_BUNDLE=${NB_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}
NB_FATAL_WAIT=${NB_FATAL_WAIT:-30}

nb_log() { log_begin_msg "$*"; log_end_msg; }
nb_warn() { log_warning_msg "$*"; }

# nb_fatal "mensagem" — informa, aguarda leitura humana e reinicia.
nb_fatal() {
    log_failure_msg "$*"
    log_failure_msg "Reiniciando em ${NB_FATAL_WAIT}s / rebooting in ${NB_FATAL_WAIT}s"
    sleep "$NB_FATAL_WAIT"
    reboot -f
    panic=60 panic "$*"
}

# nb_retry <tentativas> <espera> <comando...>
nb_retry() {
    _tries=$1
    _wait=$2
    shift 2
    _n=1
    while [ "$_n" -le "$_tries" ]; do
        if "$@"; then
            return 0
        fi
        [ "$_n" -lt "$_tries" ] && sleep "$_wait"
        _n=$((_n + 1))
    done
    return 1
}
