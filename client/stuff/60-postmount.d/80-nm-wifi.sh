# shellcheck shell=sh
# Gera os perfis do NetworkManager a partir do MESMO wifi.conf que o initrd usou.
#
# No nb2 havia duas bases de credencial de wifi mantidas à mão: o
# wpa_supplicant.conf embutido no initrd e a camada wifis.squash com perfis
# .nmconnection. Trocar a rede exigia mexer nas duas. Agora a fonte é única:
# o wifi.conf da partição do pendrive.
nb3_post_nm_wifi() {
    [ -s /run/nutellaboot/wifi.conf ] || return 0
    _dir=${rootmnt?}/etc/NetworkManager/system-connections
    mkdir -p "$_dir"

    while IFS="$(printf '\t')" read -r _ssid _psk _flags; do
        case "$_ssid" in '' | '#'*) continue ;; esac
        _file=$_dir/$_ssid.nmconnection
        {
            echo "[connection]"
            echo "id=$_ssid"
            echo "uuid=$(nb3_uuid_for "$_ssid")"
            echo "type=wifi"
            echo
            echo "[wifi]"
            echo "mode=infrastructure"
            echo "ssid=$_ssid"
            case "$_flags" in *hidden*) echo "hidden=true" ;; esac
            if [ -n "$_psk" ]; then
                echo
                echo "[wifi-security]"
                echo "auth-alg=open"
                echo "key-mgmt=wpa-psk"
                echo "psk=$_psk"
            fi
            echo
            echo "[ipv4]"
            echo "method=auto"
            echo
            echo "[ipv6]"
            echo "addr-gen-mode=default"
            echo "method=auto"
        } > "$_file"
        chmod 600 "$_file"
    done < /run/nutellaboot/wifi.conf
    nb_log "perfis de wifi gerados para o NetworkManager"
}

# UUID determinístico por SSID (md5 formatado) — evita duplicar perfis a cada boot.
nb3_uuid_for() {
    _h=$(printf '%s' "$1" | md5sum | awk '{print $1}')
    printf '%s-%s-%s-%s-%s\n' \
        "$(echo "$_h" | cut -c1-8)" "$(echo "$_h" | cut -c9-12)" \
        "$(echo "$_h" | cut -c13-16)" "$(echo "$_h" | cut -c17-20)" \
        "$(echo "$_h" | cut -c21-32)"
}
