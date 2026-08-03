# shellcheck shell=sh
# Kit de interface do boot: cor, etapas e telas de erro com letras grandes.
#
# Este arquivo é a ÚNICA fonte das mensagens de tela do boot. Ele entra por
# dois caminhos:
#   1. concatenado no stuff servido (stuffgen varre client/stuff/**/*.sh em
#      ordem lexical, então "05-ui" vem logo depois de "00-header");
#   2. copiado para dentro do initrd como /scripts/nb3-ui pelo hook, e
#      carregado pelo bootstrap antes de qualquer mensagem.
# Não duplique estas funções em outro lugar: initrd e stuff mostram a mesma
# coisa porque leem o mesmo arquivo.
#
# As letras grandes são desenhadas com ESPAÇOS EM FUNDO COLORIDO, não com
# caracteres de desenho. No console do initrd não há tput, terminfo nem
# garantia de fonte carregada; espaço é o único glifo que existe em qualquer
# fonte. É por isso que a tela de erro sai igual em toda máquina.
#
# Tudo em inglês: as sedes são de vários países e não há como carregar
# dicionário antes da rede subir. O campo LANGUAGE continua valendo para a
# tela de bloqueio e o agente, que rodam com o sistema já montado.

# Em sh POSIX não existe `local`: toda variável é global. Por isso todos os
# temporários daqui usam o prefixo _nbu_ — sem ele, a variável de laço de uma
# função apaga a de outra. Já aconteceu: nb_banner iterava as palavras em _w e
# destruía o _w do nb_fatal_screen, que então chamava `sleep RAM`.
NB_UI_COLS=${NB_UI_COLS:-78}

# ESC de verdade, uma vez só: printf '%s' não interpreta \033 no argumento.
NB_ESC=$(printf '\033')
NB_C_OFF="${NB_ESC}[0m"
NB_C_RED="${NB_ESC}[41m"
NB_C_YEL="${NB_ESC}[43m"
NB_C_LIT="${NB_ESC}[47m"
NB_C_TXT="${NB_ESC}[1;37m"
NB_C_DIM="${NB_ESC}[0;37m"
NB_C_OK="${NB_ESC}[1;32m"
NB_C_WARN="${NB_ESC}[1;33m"
NB_C_FAIL="${NB_ESC}[1;31m"

# NB_UI_PLAIN=1 desliga cor e letras grandes (usado nos testes e útil quando a
# saída do boot está sendo capturada para arquivo).
if [ "${NB_UI_PLAIN:-0}" = 1 ]; then
    NB_C_OFF= NB_C_RED= NB_C_YEL= NB_C_LIT= NB_C_TXT= NB_C_DIM=
    NB_C_OK= NB_C_WARN= NB_C_FAIL=
fi

# --- fonte de bitmap 4x5 ----------------------------------------------------
# Cinco linhas por caractere, separadas por "|". "#" acende, "." apaga.
# Cada pixel vira DOIS espaços na tela: 4x5 pixels dá 8x5 células, que é
# aproximadamente quadrado (célula de console é ~2:1).

NB_G_A='.##.|#..#|####|#..#|#..#'
NB_G_B='###.|#..#|###.|#..#|###.'
NB_G_C='.###|#...|#...|#...|.###'
NB_G_D='###.|#..#|#..#|#..#|###.'
NB_G_E='####|#...|###.|#...|####'
NB_G_F='####|#...|###.|#...|#...'
NB_G_G='.###|#...|#.##|#..#|.###'
NB_G_H='#..#|#..#|####|#..#|#..#'
NB_G_I='.##.|..#.|..#.|..#.|.##.'
NB_G_J='...#|...#|...#|#..#|.##.'
NB_G_K='#..#|#.#.|##..|#.#.|#..#'
NB_G_L='#...|#...|#...|#...|####'
NB_G_M='#..#|####|####|#..#|#..#'
NB_G_N='#..#|##.#|#.##|#..#|#..#'
NB_G_O='.##.|#..#|#..#|#..#|.##.'
NB_G_P='###.|#..#|###.|#...|#...'
NB_G_Q='.##.|#..#|#..#|#.#.|.#.#'
NB_G_R='###.|#..#|###.|#.#.|#..#'
NB_G_S='.###|#...|.##.|...#|###.'
NB_G_T='####|..#.|..#.|..#.|..#.'
NB_G_U='#..#|#..#|#..#|#..#|.##.'
NB_G_V='#..#|#..#|#..#|.##.|..#.'
NB_G_W='#..#|#..#|####|####|#..#'
NB_G_X='#..#|.##.|.##.|.##.|#..#'
NB_G_Y='#..#|#..#|.##.|..#.|..#.'
NB_G_Z='####|...#|.##.|#...|####'
NB_G_0='.##.|#.##|##.#|#..#|.##.'
NB_G_1='..#.|.##.|..#.|..#.|.###'
NB_G_2='###.|...#|.##.|#...|####'
NB_G_3='###.|...#|.##.|...#|###.'
NB_G_4='#..#|#..#|####|...#|...#'
NB_G_5='####|#...|###.|...#|###.'
NB_G_6='.###|#...|###.|#..#|.##.'
NB_G_7='####|...#|..#.|.#..|.#..'
NB_G_8='.##.|#..#|.##.|#..#|.##.'
NB_G_9='.##.|#..#|.###|...#|###.'
NB_G_DASH='....|....|####|....|....'
NB_G_BANG='.##.|.##.|.##.|....|.##.'
NB_G_QUERY='###.|...#|.##.|....|.##.'
NB_G_SPACE='....|....|....|....|....'

# Nome da variável de um caractere (letra/dígito viram sufixo direto; o resto
# tem nome próprio porque não pode entrar em nome de variável).
nb_ui_glyphvar() {
    case "$1" in
        [A-Z] | [0-9]) printf 'NB_G_%s' "$1" ;;
        -) printf 'NB_G_DASH' ;;
        '!') printf 'NB_G_BANG' ;;
        '?') printf 'NB_G_QUERY' ;;
        *) printf 'NB_G_SPACE' ;;
    esac
}

# n-ésima linha (1-5) de um glifo, sem chamar cut: só expansão de parâmetro.
nb_ui_row() {
    _nbu_rowv=$1
    _nbu_rown=$2
    while [ "$_nbu_rown" -gt 1 ]; do
        _nbu_rowv=${_nbu_rowv#*|}
        _nbu_rown=$((_nbu_rown - 1))
    done
    printf '%s' "${_nbu_rowv%%|*}"
}

nb_ui_spaces() {
    _nbu_s=
    _nbu_i=$1
    while [ "$_nbu_i" -gt 0 ]; do
        _nbu_s="$_nbu_s "
        _nbu_i=$((_nbu_i - 1))
    done
    printf '%s' "$_nbu_s"
}

# nb_ui_word LINHA PALAVRA — desenha uma linha da palavra inteira.
nb_ui_word() {
    _nbu_line=
    _nbu_rest=$2
    while [ -n "$_nbu_rest" ]; do
        _nbu_ch=${_nbu_rest%"${_nbu_rest#?}"}
        _nbu_rest=${_nbu_rest#?}
        eval "_nbu_g=\$$(nb_ui_glyphvar "$_nbu_ch")"
        _nbu_pat=$(nb_ui_row "$_nbu_g" "$1")
        while [ -n "$_nbu_pat" ]; do
            _nbu_p=${_nbu_pat%"${_nbu_pat#?}"}
            _nbu_pat=${_nbu_pat#?}
            if [ "$_nbu_p" = '#' ]; then
                _nbu_line="$_nbu_line${NB_C_LIT}  ${NB_C_RED}"
            else
                _nbu_line="$_nbu_line  "
            fi
        done
        _nbu_line="$_nbu_line  " # espaço entre caracteres
    done
    printf '%s' "$_nbu_line"
}

# nb_banner COR PALAVRA... — letras grandes. Quebra por palavra quando não
# cabe na largura (cada caractere ocupa 10 colunas).
nb_banner() {
    _nbu_bnbg=$1
    shift
    [ "${NB_UI_PLAIN:-0}" = 1 ] && {
        printf '\n  === %s ===\n\n' "$*"
        return 0
    }
    _nbu_max=$(((NB_UI_COLS - 4) / 10))
    [ "$_nbu_max" -lt 1 ] && _nbu_max=1

    _nbu_cur=
    for _nbu_word in "$@"; do
        _nbu_try=$_nbu_cur
        [ -n "$_nbu_try" ] && _nbu_try="$_nbu_try "
        _nbu_try="$_nbu_try$_nbu_word"
        if [ "${#_nbu_try}" -gt "$_nbu_max" ] && [ -n "$_nbu_cur" ]; then
            nb_ui_bannerline "$_nbu_bnbg" "$_nbu_cur"
            _nbu_cur=$_nbu_word
        else
            _nbu_cur=$_nbu_try
        fi
    done
    [ -n "$_nbu_cur" ] && nb_ui_bannerline "$_nbu_bnbg" "$_nbu_cur"
    printf '\n'
}

# Conta as linhas que uma tela ainda pode usar depois do banner. Serve para as
# telas com conteúdo variável (a de disco) saberem quando cortar.
nb_ui_room() {
    printf '%s' "$((NB_UI_LINES - 10))"
}

nb_ui_bannerline() {
    _nbu_bg=$1
    _nbu_txt=$2
    _nbu_pad=$((NB_UI_COLS - 4 - ${#_nbu_txt} * 10))
    [ "$_nbu_pad" -lt 0 ] && _nbu_pad=0
    _nbu_fill=$(nb_ui_spaces "$_nbu_pad")
    _nbu_bar=$(nb_ui_spaces $((NB_UI_COLS - 2)))

    printf '  %s%s%s\n' "$_nbu_bg" "$_nbu_bar" "$NB_C_OFF"
    _nbu_n=1
    while [ "$_nbu_n" -le 5 ]; do
        printf '  %s  %s%s%s\n' "$_nbu_bg" "$(nb_ui_word "$_nbu_n" "$_nbu_txt")" "$_nbu_fill" "$NB_C_OFF"
        _nbu_n=$((_nbu_n + 1))
    done
    printf '  %s%s%s\n' "$_nbu_bg" "$_nbu_bar" "$NB_C_OFF"
}

# --- etapas e passos --------------------------------------------------------

# Faixa de etapa: separa visualmente as fases do boot na enxurrada do kernel.
nb_phase() {
    _nbu_t=$*
    _nbu_wid=$((NB_UI_COLS - 2))
    _nbu_phbar=$(nb_ui_spaces "$_nbu_wid")
    _nbu_phpad=$((_nbu_wid - 4 - ${#_nbu_t}))
    [ "$_nbu_phpad" -lt 0 ] && _nbu_phpad=0
    printf '\n  %s%s%s\n' "$NB_C_YEL" "$_nbu_phbar" "$NB_C_OFF"
    printf '  %s%s  %s  %s%s\n' \
        "$NB_C_YEL" "${NB_ESC}[1;30m" "$_nbu_t" "$(nb_ui_spaces "$_nbu_phpad")" "$NB_C_OFF"
    printf '  %s%s%s\n\n' "$NB_C_YEL" "$_nbu_phbar" "$NB_C_OFF"
}

# Estas quatro vêm do initramfs-tools e são redefinidas de propósito: o
# arquivo é carregado depois de /scripts/functions, então esta versão vale
# para todo o resto do boot (mesmo padrão de mount_bottom, redefinida no
# 90-main.sh). Se este arquivo não estiver presente num initrd antigo, as
# originais continuam valendo e o boot só perde o visual.
_NB_OPEN=0

log_begin_msg() {
    _nbu_msg=$*
    _nbu_lbpad=$((NB_UI_COLS - 12 - ${#_nbu_msg}))
    [ "$_nbu_lbpad" -lt 1 ] && _nbu_lbpad=1
    printf '  %s>%s %s%s' "$NB_C_OK" "$NB_C_OFF" "$_nbu_msg" "$(nb_ui_spaces "$_nbu_lbpad")"
    _NB_OPEN=1
}

log_end_msg() {
    if [ "$_NB_OPEN" = 1 ]; then
        printf '[ %s OK %s ]\n' "$NB_C_OK" "$NB_C_OFF"
        _NB_OPEN=0
    fi
}

nb_ui_closeline() {
    [ "$_NB_OPEN" = 1 ] && printf '\n'
    _NB_OPEN=0
}

log_warning_msg() {
    nb_ui_closeline
    printf '  [ %sWARN%s ] %s\n' "$NB_C_WARN" "$NB_C_OFF" "$*"
}

log_failure_msg() {
    nb_ui_closeline
    printf '  [ %sFAIL%s ] %s\n' "$NB_C_FAIL" "$NB_C_OFF" "$*"
}

nb_ui_text() {
    printf '  %s%s%s\n' "$NB_C_TXT" "$*" "$NB_C_OFF"
}

nb_ui_dim() {
    printf '  %s%s%s\n' "$NB_C_DIM" "$*" "$NB_C_OFF"
}

# --- tela cheia de erro -----------------------------------------------------

# O console pode ser VGA texto de 80x25. Uma tela de erro com banner mais
# explicação passa disso e o console rola: as letras grandes — a parte que faz
# a pessoa olhar — somem para fora da tela. Limpar antes de desenhar resolve, e
# é a única forma de garantir que o banner fique visível.
# Só as telas fatais limpam; o resto do boot continua rolando normalmente,
# porque ali o histórico é o que serve para diagnosticar.
NB_UI_LINES=${NB_UI_LINES:-25}

nb_ui_clear() {
    [ "${NB_UI_PLAIN:-0}" = 1 ] && return 0
    printf '%s[2J%s[H' "$NB_ESC" "$NB_ESC"
}

# nb_screen "PALAVRAS DO BANNER" "linha" "linha" ...
# Linha começando com "!" sai em destaque; as demais saem discretas.
nb_screen() {
    nb_ui_closeline
    _nbu_words=$1
    shift
    nb_ui_clear
    # shellcheck disable=SC2086
    nb_banner "$NB_C_RED" $_nbu_words
    for _nbu_l in "$@"; do
        case "$_nbu_l" in
            '!'*) nb_ui_text "${_nbu_l#!}" ;;
            *) nb_ui_dim "$_nbu_l" ;;
        esac
    done
}

# Quanto uma tela de erro fica no ar antes do reboot. É maior que a espera do
# nb_fatal simples porque estas telas trazem instrução, e quem está na sala
# precisa de tempo para ler (ou fotografar). NB_FATAL_WAIT=0 zera as duas —
# é o que os testes e a depuração em VM usam para não esperar um minuto a
# cada erro.
nb_screen_wait() {
    if [ "${NB_FATAL_WAIT:-30}" = 0 ]; then
        printf 0
    else
        printf '%s' "${NB_SCREEN_WAIT:-60}"
    fi
}

# nb_fatal_screen "PALAVRAS" "linha" ... — tela cheia, espera e reinicia.
nb_fatal_screen() {
    _nbu_fsw=$1
    shift
    _nbu_wait=$(nb_screen_wait)
    nb_screen "$_nbu_fsw" "$@" \
        "" \
        "!This machine will restart in ${_nbu_wait} seconds."
    sleep "$_nbu_wait"
    reboot -f
    panic=60 panic "$_nbu_fsw"
}
