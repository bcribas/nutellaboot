# shellcheck shell=sh
# Orquestração do boot.
#
# ATENÇÃO: este arquivo NÃO redefine funções de rede. No nb2 o stuff
# sobrescrevia configure_localnetwork() e, ao fazê-lo, deixava de chamar
# configure_wifi() — era essa a razão de o wifi nunca funcionar apesar de o
# initrd trazer wpa_supplicant e todo o firmware. A rede é responsabilidade
# exclusiva do bootstrap do initrd; aqui ela já vem pronta.

runpostmountconfigs() {
    nb3_post_home
    nb3_post_machineid
    nb3_post_secrets
    nb3_post_rclocal
    nb3_post_firewall
    nb3_post_limits
    nb3_post_locale
    nb3_post_timezone
    nb3_post_autologin
    nb3_post_dconf
    nb3_post_polkit
    nb3_post_firefox
    nb3_post_wallpaper
    nb3_post_clionkey
    nb3_post_nm_wifi
    createzramswap
}

nb3_mountroot() {
    [ -z "$IMAGEROOT" ] && nb_fatal "IMAGEROOT is not set"
    BLOCKROOT=/secretdev
    STORAGEDIR=$BLOCKROOT/nutellaboot
    mkdir -p "$BLOCKROOT"

    nb_phase "STORAGE - looking for a disk to store the system"
    runpremountconfigs

    # Depois do disco (é onde os arquivos novos são conferidos antes de tocar
    # no pendrive) e ANTES das camadas: não adianta baixar 6 GB para reiniciar
    # em seguida. Depois do reinício elas já estão em cache.
    nb_usb_update

    nb_phase "SYSTEM - downloading and mounting the system layers"
    mount_layers

    [ "$SEEDIMAGE" = t ] && seedimage
    [ -z "$noswap" ] && createandactivateswap
    [ "$persistenthome" = y ] && mount_persistenthome

    nb_phase "SETUP - applying this site's configuration"
    runpostmountconfigs
    umount -l "$BLOCKROOT" 2>/dev/null
}

# Devolve a rede ao NetworkManager do sistema instalado.
fixnetworktoreconnect() {
    log_begin_msg "Handing the network back to NetworkManager"
    rm -f "${rootmnt?}"/usr/lib/NetworkManager/conf.d/10-glo*
    ln -s /dev/null "${rootmnt?}/etc/systemd/system/systemd-networkd.service"
    for _i in /sys/class/net/e* /sys/class/net/w*; do
        [ -e "$_i" ] || continue
        ip a flush dev "$(basename "$_i")" 2>/dev/null
    done
    rm -rf /run/netplan
    rm -f /run/net-*
    [ -e /run/initram-wpa_supplicant.pid ] &&
        kill "$(cat /run/initram-wpa_supplicant.pid)" 2>/dev/null
    log_end_msg
    IP=none
    IP6=none
}

mount_top() { local_top; }
mount_premount() { local_premount; }
mount_bottom() {
    fixnetworktoreconnect
    unset BLOCKROOT
    unset STORAGEDIR
}
