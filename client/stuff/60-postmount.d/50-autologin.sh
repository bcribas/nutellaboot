# shellcheck shell=sh
nb3_post_autologin() {
    [ "$ICPC_AUTOLOGIN" = t ] || return 0
    _cfg=${rootmnt?}/etc/gdm3/custom.conf
    [ -e "$_cfg" ] || return 0
    sed -e 's,^#  Automatic,Automatic,g' -e 's,user1,icpc,' "$_cfg" > /tmp/gdm.conf
    cat /tmp/gdm.conf > "$_cfg"
    nb_log "autologin habilitado"
}
