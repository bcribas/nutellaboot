# shellcheck shell=sh
# machine-id estável por máquina (vive na home persistente) + id do boot atual.
nb3_post_machineid() {
    rm -f "${rootmnt?}/var/lib/dbus/machine-id" "${rootmnt?}/etc/machine-id"
    ln -s /home/.machine-id "${rootmnt?}/var/lib/dbus/machine-id"
    ln -s /home/.machine-id "${rootmnt?}/etc/machine-id"
    [ -f "${rootmnt?}/home/.machine-id" ] || touch "${rootmnt?}/home/.machine-id"
    echo "$NBUID" > "${rootmnt?}/home/.machine-id-boot"
    echo "$IMAGEROOT" > "${rootmnt?}/etc/imageroot-icpc"
    # arquivo separado, e não uma segunda linha no de cima: o imageroot-icpc
    # também alimenta o user-agent do Firefox e do Epiphany (65-firefox.sh),
    # que lê o arquivo inteiro com `$(< ...)`.
    echo "${NB_SITE_NAME:-}" > "${rootmnt?}/etc/sitename-icpc"
}
