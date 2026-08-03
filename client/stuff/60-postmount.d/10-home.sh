# shellcheck shell=sh
nb3_post_home() {
    if [ ! -d "${rootmnt?}/home/icpc" ]; then
        nb_log "preparing a fresh home for the icpc user"
        mkdir -p "${rootmnt?}/home/icpc"
        touch "${rootmnt?}/home/icpc/.clean-home"
    fi
    [ "$FORCE_CLEAN_HOME_ON_BOOT" = t ] && touch "${rootmnt?}/home/icpc/.clean-home"
    return 0
}
