# shellcheck shell=sh
# Gera os perfis do NetworkManager a partir do MESMO wifi.conf que o initrd usou.
#
# No nb2 havia duas bases de credencial de wifi mantidas à mão: o
# wpa_supplicant.conf embutido no initrd e a camada wifis.squash com perfis
# .nmconnection. Trocar a rede exigia mexer nas duas. Agora a fonte é única:
# o wifi.conf da partição do pendrive.
nb3_post_nm_wifi() {
    # o MESMO caminho que o initrd usa (`NB_RUN`), e não um literal repetido:
    # duas verdades sobre o mesmo lugar é como uma delas fica para trás — e era
    # o que impedia este módulo de ser exercitado em teste
    _conf=${NB_RUN:-/run/nutellaboot}/wifi.conf
    [ -s "$_conf" ] || return 0
    _dir=${rootmnt?}/etc/NetworkManager/system-connections
    mkdir -p "$_dir"

    # A limpeza do arquivo (CR do Windows, BOM, espaço nas pontas) é feita uma
    # vez só, pelo initrd, ao copiar do pendrive para a RAM — `nb_wifi_normalize`.
    # O `tr` aqui é para o pendrive que ainda tem initrd ANTIGO: o stuff é
    # servido novo a cada boot, o initrd não. Um `\r` no fim vira senha errada
    # gravada no perfil, e o NetworkManager não diz que a senha está errada:
    # ele só não conecta.
    tr -d '\r' < "$_conf" > "$_conf.nm" || return 0

    while IFS="$(printf '\t')" read -r _ssid _psk _flags; do
        case "$_ssid" in '' | '#'*) continue ;; esac
        # O SSID vira NOME DE ARQUIVO. Um SSID com barra escreveria fora de
        # system-connections/, como root, dentro do sistema que a sala monta —
        # a mesma armadilha do host do firewall. Este arquivo é editado à mão
        # pela sede, então errar aqui é mais fácil que ser atacado.
        case "$_ssid" in
            */* | .*)
                nb_warn "ignoring wifi network with invalid SSID: $_ssid"
                continue
                ;;
        esac
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
    done < "$_conf.nm"
    rm -f "$_conf.nm"
    nb_log "wifi profiles generated for NetworkManager"
}

# UUID determinístico por SSID (md5 formatado) — evita duplicar perfis a cada boot.
nb3_uuid_for() {
    _h=$(printf '%s' "$1" | md5sum | awk '{print $1}')
    printf '%s-%s-%s-%s-%s\n' \
        "$(echo "$_h" | cut -c1-8)" "$(echo "$_h" | cut -c9-12)" \
        "$(echo "$_h" | cut -c13-16)" "$(echo "$_h" | cut -c17-20)" \
        "$(echo "$_h" | cut -c21-32)"
}
