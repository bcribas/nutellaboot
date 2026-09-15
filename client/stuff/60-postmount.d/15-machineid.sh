# shellcheck shell=sh
# machine-id DERIVADO do MAC estável (10-identidade.sh) + id do boot atual.
#
# Antes o arquivo era criado vazio e o systemd gerava um id aleatório, que
# ficava na home persistente — e portanto era clonado junto com ela (o MOJ
# achou 62 grupos de máquinas com o mesmo id), sumia com `cleanhome` e
# mudava no modo live. Derivado do MAC ele é único por placa e reproduzível
# na mão: `printf '%s' 'aa-bb-cc-dd-ee-ff' | md5sum`.
nb3_post_machineid() {
    _mid_mac=$(nb3_mac_estavel) || _mid_mac=""
    # o agente e a tela de bloqueio leem daqui: é a chave da máquina
    echo "$_mid_mac" > "${rootmnt?}/etc/mac-icpc"
    chmod 644 "${rootmnt?}/etc/mac-icpc"
    [ -n "$_mid_mac" ] || nb_warn "no stable MAC found; machine-id will be random"

    rm -f "${rootmnt?}/var/lib/dbus/machine-id" "${rootmnt?}/etc/machine-id"
    ln -s /home/.machine-id "${rootmnt?}/var/lib/dbus/machine-id"
    ln -s /home/.machine-id "${rootmnt?}/etc/machine-id"
    if [ -n "$_mid_mac" ]; then
        # sobrescreve SEMPRE: um id herdado de home clonada é justamente o que
        # não pode sobreviver
        printf '%s' "$_mid_mac" | md5sum | cut -c1-32 > "${rootmnt?}/home/.machine-id"
    else
        [ -f "${rootmnt?}/home/.machine-id" ] || touch "${rootmnt?}/home/.machine-id"
    fi
    echo "$NBUID" > "${rootmnt?}/home/.machine-id-boot"
    echo "$IMAGEROOT" > "${rootmnt?}/etc/imageroot-icpc"
    # arquivo separado, e não uma segunda linha no de cima: o imageroot-icpc
    # também alimenta o user-agent do Firefox e do Epiphany (65-firefox.sh),
    # que lê o arquivo inteiro com `$(< ...)`.
    echo "${NB_SITE_NAME:-}" > "${rootmnt?}/etc/sitename-icpc"
}
