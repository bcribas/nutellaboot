# shellcheck shell=sh
# Wallpaper servido pela API (upload feito no configureitor, md5 conhecido).
#
# No nb2 a URL era colada à mão pelo operador e o boot ficava preso num
# `read -p "Continue anyway?"` quando o download falhava — numa sala sem
# ninguém olhando, isso significa máquina parada. Aqui, falha só avisa.
nb3_post_wallpaper() {
    [ -z "$NB_WALLPAPER_MD5" ] && return 0
    _target=${rootmnt?}/home/.wallpaper.png
    _link=${rootmnt?}/usr/share/maratona-background/maratona-common-wallpaper.png

    rm -f "$_link"
    ln -s /home/.wallpaper.png "$_link"

    if [ -e "$_target" ] && nutella_md5sum "$NB_WALLPAPER_MD5" "$_target"; then
        return 0
    fi
    rm -f "$_target"

    if ! nb_download "$_target" 1 "$NB_SERVER/boot/v3/$IMAGEROOT/wallpaper"; then
        nb_warn "wallpaper could not be downloaded - keeping the default one"
        rm -f "$_link"
        return 0
    fi
    if ! nutella_md5sum "$NB_WALLPAPER_MD5" "$_target"; then
        nb_warn "wallpaper MD5 mismatch - keeping the default one"
        rm -f "$_target" "$_link"
    fi
    return 0
}
