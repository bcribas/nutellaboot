# shellcheck shell=sh
nb3_post_timezone() {
    [ -z "$TIMEZONE" ] && return 0
    [ -e "${rootmnt?}/usr/share/zoneinfo/$TIMEZONE" ] || {
        nb_warn "invalid time zone: $TIMEZONE"
        return 0
    }
    rm -f "${rootmnt?}/etc/localtime"
    ln -s "/usr/share/zoneinfo/$TIMEZONE" "${rootmnt?}/etc/localtime"
    echo "$TIMEZONE" > "${rootmnt?}/etc/timezone"
}
