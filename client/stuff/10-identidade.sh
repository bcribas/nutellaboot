# shellcheck shell=sh
# Identidade da máquina: qual MAC é "o" MAC.
#
# A chave da máquina no servidor é um MAC, e uma máquina pode bootar pelo
# cabo hoje, pelo wifi amanhã e por um adaptador USB depois de amanhã. Se a
# chave fosse "o MAC por onde bootou" (BOOTIF), a mesma máquina apareceria
# como três — e sem BOOTIF (boot por wifi) a tela de bloqueio nem consultava
# o estado. A regra aqui escolhe sempre a MESMA placa: a primeira cabeada
# interna; sem cabeada, a primeira wifi interna; USB nunca, porque pode não
# estar lá no próximo boot. Roda no initrd, ANTES do NetworkManager: o
# address do sysfs é o de fábrica.
#
# Só comandos que existem no initrd (cat, readlink, sed, tr): nada de ip,
# ethtool ou head. Os caminhos são parametrizados para os testes
# (tests/test_stuffgen_round_trip.py) com os mesmos nomes do bootstrap.
NB_SYS_NET=${NB_SYS_NET:-/sys/class/net}
NB_CMDLINE=${NB_CMDLINE:-/proc/cmdline}

# MAC de uma interface no formato do servidor (aa-bb-cc-dd-ee-ff); falha se
# não há endereço ou é zerado
nb3_mac_de_iface() {
    _mi_end=$(cat "$NB_SYS_NET/$1/address" 2> /dev/null) || return 1
    case "$_mi_end" in "" | 00:00:00:00:00:00) return 1 ;; esac
    printf '%s\n' "$_mi_end" | tr 'A-F:' 'a-f-'
}

# nb3_ifaces_candidatas wired|wifi — nomes, em ordem lexical, das placas
# físicas internas do tipo pedido
nb3_ifaces_candidatas() {
    for _ic_d in "$NB_SYS_NET"/*; do
        _ic_n=${_ic_d##*/}
        [ -e "$_ic_d/device" ] || continue
        case "$_ic_n" in
            lo | veth* | docker* | br-* | virbr* | tap* | tun* | wg* | vnet*) continue ;;
        esac
        case "$(readlink -f "$_ic_d/device" 2> /dev/null)" in */usb[0-9]*) continue ;; esac
        if [ -e "$_ic_d/wireless" ] || [ -e "$_ic_d/phy80211" ]; then
            [ "$1" = wifi ] || continue
        else
            [ "$1" = wired ] || continue
        fi
        echo "$_ic_n"
    done
}

nb3_mac_estavel() {
    for _me_tipo in wired wifi; do
        for _me_n in $(nb3_ifaces_candidatas "$_me_tipo"); do
            nb3_mac_de_iface "$_me_n" && return 0
        done
    done
    # só resta USB: vale a placa por onde bootou (o GRUB/PXE põe BOOTIF=01-mac)
    _me_m=$(sed -n 's/.*BOOTIF=01-\([0-9a-fA-F-]*\).*/\1/p' "$NB_CMDLINE" 2> /dev/null | tr 'A-F' 'a-f')
    if [ -n "$_me_m" ]; then
        printf '%s\n' "$_me_m"
        return 0
    fi
    for _me_d in "$NB_SYS_NET"/*; do
        _me_n=${_me_d##*/}
        [ "$_me_n" = lo ] && continue
        [ -e "$_me_d/device" ] || continue
        nb3_mac_de_iface "$_me_n" && return 0
    done
    return 1
}
