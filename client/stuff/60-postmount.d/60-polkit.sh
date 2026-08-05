# shellcheck shell=sh
# Permissões opcionais (USB, rede) e sudo — antes eram `if` por sede no script
# compartilhado; agora são variáveis de configuração da imagem.
nb3_post_polkit() {
    # Os .pkla vêm do pacote maratona-usuario-icpc, e no Ubuntu 24.04 são
    # LETRA MORTA: o polkit 124 removeu o backend localauthority (virou o
    # pacote polkitd-pkla, que não vem instalado), e .pkla é ignorado sem
    # erro nem log — foi assim que o icpc trocou de wifi numa máquina com os
    # três arquivos no lugar. A remoção continua para a base 22.04, que ainda
    # os honra; quem VALE no 24.04 é a regra JS escrita logo abaixo.
    _pkla=${rootmnt?}/etc/polkit-1/localauthority/90-mandatory.d
    [ "$ALLOWUSBMOUNT" = t ] && rm -f "$_pkla/icpc-udisks.pkla"
    [ "$ALLOWNETWORKCHANGE" = t ] && rm -f "$_pkla/icpc-networkmanager.pkla"
    nb3_post_polkit_rules
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

# A regra de verdade do polkit moderno (>= 106): JavaScript em rules.d.
# Escrita a cada boot, montada conforme as flags — assim a sede que ganha
# permissão de rede no configureitor perde o bloqueio no boot seguinte, e o
# resto do país continua travado.
nb3_post_polkit_rules() {
    _rules_dir=${rootmnt?}/etc/polkit-1/rules.d
    mkdir -p "$_rules_dir"
    _rules=$_rules_dir/90-maratona-icpc.rules
    {
        echo "// Gerado pelo NutellaBoot a cada boot - nao edite (será sobrescrito)."
        echo "polkit.addRule(function(action, subject) {"
        echo "    if (subject.user != \"icpc\") return polkit.Result.NOT_HANDLED;"
        # o relógio é da prova: sem flag, sempre bloqueado
        echo "    if (action.id.indexOf(\"org.freedesktop.timedate1.\") == 0) return polkit.Result.NO;"
        [ "$ALLOWNETWORKCHANGE" = t ] ||
            echo "    if (action.id.indexOf(\"org.freedesktop.NetworkManager.\") == 0) return polkit.Result.NO;"
        [ "$ALLOWUSBMOUNT" = t ] ||
            echo "    if (action.id.indexOf(\"org.freedesktop.udisks2.\") == 0) return polkit.Result.NO;"
        echo "    return polkit.Result.NOT_HANDLED;"
        echo "});"
    } > "$_rules"
    chmod 644 "$_rules"
    return 0
}
