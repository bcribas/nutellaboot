# shellcheck shell=sh
# /etc/.nb3 é o contrato entre o boot e o sistema: agente de telemetria e
# tela de bloqueio leem tudo daqui (no nb2 esses valores eram hardcoded no
# script e corrigidos em runtime com `sed -i` por número de linha).
nb3_post_secrets() {
    umask 077
    # este arquivo é `.`-sourced pelo agente COMO ROOT: o que entra aqui entre
    # aspas simples precisa do escape do shell, não do que veio do servidor
    _nb3_theme=$(nb3_sh_escape "${LOCK_THEME:-classico}")
    _nb3_lang=$(nb3_sh_escape "${LANGUAGE:-pt}")
    cat > "${rootmnt?}/etc/.nb3" << EOF
NB_SERVER='$NB_SERVER'
IMAGEROOT='$IMAGEROOT'
NB_MACHINE_KEY='$NB_MACHINE_KEY'
NB_BOOT_KEY='${NB_BOOT_KEY:-}'
NB_LOCK_THEME='$_nb3_theme'
NB_LOCK_FALLBACK_HASH='${NB_LOCK_FALLBACK_HASH:-}'
NB_LANGUAGE='$_nb3_lang'
EOF
    chmod 600 "${rootmnt?}/etc/.nb3"
    chmod go-rw "${rootmnt?}/root/"
    umask 022
}
