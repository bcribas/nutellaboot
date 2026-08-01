# shellcheck shell=sh
# Permissões opcionais (USB, rede) e sudo — antes eram `if` por sede no script
# compartilhado; agora são variáveis de configuração da imagem.
nb3_post_polkit() {
    _pkla=${rootmnt?}/etc/polkit-1/localauthority/90-mandatory.d
    [ "$ALLOWUSBMOUNT" = t ] && rm -f "$_pkla/icpc-udisks.pkla"
    [ "$ALLOWNETWORKCHANGE" = t ] && rm -f "$_pkla/icpc-networkmanager.pkla"
    [ "$NB_ICPC_SUDO" = t ] && echo "icpc ALL=(ALL:ALL) ALL" >> "${rootmnt?}/etc/sudoers"

    if [ -n "$NB_ROOT_PW_HASH" ]; then
        grep -v '^root:' "${rootmnt?}/etc/shadow" > /tmp/shadow.new
        echo "root:$NB_ROOT_PW_HASH:20134:0:99999:7:::" >> /tmp/shadow.new
        cat /tmp/shadow.new > "${rootmnt?}/etc/shadow"
        rm -f /tmp/shadow.new
    fi

    [ "$NB_ENABLE_QUERO_SER_SEDE" = t ] &&
        chmod a+x "${rootmnt?}/usr/bin/quero-ser-sede" 2>/dev/null

    for _app in $NB_HIDE_DOCS_APPS; do
        rm -f "${rootmnt?}/usr/share/applications/$_app.desktop"
    done
    return 0
}
