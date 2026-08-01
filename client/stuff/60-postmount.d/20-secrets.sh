# shellcheck shell=sh
# /etc/.nb3 é o contrato entre o boot e o sistema: agente de telemetria e
# tela de bloqueio leem tudo daqui (no nb2 esses valores eram hardcoded no
# script e corrigidos em runtime com `sed -i` por número de linha).
nb3_post_secrets() {
    umask 077
    cat > "${rootmnt?}/etc/.nb3" << EOF
NB_SERVER='$NB_SERVER'
IMAGEROOT='$IMAGEROOT'
NB_MACHINE_KEY='$NB_MACHINE_KEY'
NB_BOOT_KEY='${NB_BOOT_KEY:-}'
NB_LOCK_THEME='${LOCK_THEME:-classico}'
NB_LOCK_FALLBACK_HASH='${NB_LOCK_FALLBACK_HASH:-}'
NB_LANGUAGE='${LANGUAGE:-pt}'
EOF
    chmod 600 "${rootmnt?}/etc/.nb3"
    chmod go-rw "${rootmnt?}/root/"
    umask 022
}
