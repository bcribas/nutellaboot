# shellcheck shell=sh
# Base do stuff v3: logging e política de erro.
#
# REGRA DE OURO: nenhuma função deste script pode chamar `read`. Máquina de
# prova boota sozinha; erro que espera humano é erro que trava a sala.
# Use nb_fatal (mostra, espera, reinicia) ou nb_warn (segue em frente).
#
# O visual (cor, etapas, letras grandes) vem do 05-ui.sh, carregado logo
# depois deste arquivo. As mensagens de tela são todas em inglês — ver o
# cabeçalho daquele arquivo para o porquê.

NB_CA_BUNDLE=${NB_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}
NB_FATAL_WAIT=${NB_FATAL_WAIT:-30}

nb_log() { log_begin_msg "$*"; log_end_msg; }
nb_warn() { log_warning_msg "$*"; }

# nb_fatal "mensagem" — informa, aguarda leitura humana e reinicia.
# Para os casos em que dá para explicar o que fazer, prefira nb_fatal_screen
# (05-ui.sh): tela cheia, letras grandes e instrução.
nb_fatal() {
    log_failure_msg "$*"
    log_failure_msg "Restarting in ${NB_FATAL_WAIT}s"
    sleep "$NB_FATAL_WAIT"
    reboot -f
    panic=60 panic "$*"
}

# Escapa um valor do formulário para dentro de um JSON. Sem isto, uma aspa na
# página inicial quebra o policies.json inteiro — e um JSON inválido o Firefox
# ignora em silêncio, deixando a máquina sem política nenhuma.
nb3_json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# Os dois destinos abaixo re-envolvem o valor em aspas simples, e aí a proteção
# que o servidor deu (`_sh_quote`) não vale mais nada: uma aspa na página
# inicial quebra o keyfile do dconf — que recusa o local.d INTEIRO, levando
# teclado e favoritos junto — e, no /etc/.nb3, quem lê é o agente como root.
#
# São dois idiomas diferentes, e é por isso que são duas funções: no GVariant a
# aspa se escapa com barra invertida; em shell isso NÃO existe dentro de aspas
# simples — é preciso fechar, pôr a aspa e reabrir.
nb3_gvariant_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e "s/'/\\\\'/g"
}

nb3_sh_escape() {
    printf '%s' "$1" | sed "s/'/'\\\\''/g"
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
