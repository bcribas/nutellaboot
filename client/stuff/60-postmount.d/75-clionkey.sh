# shellcheck shell=sh
# Licença do CLion. No nb2 isto era `while ! download_file ...; do sleep 3; done`
# — sem rede, a máquina nunca terminava de bootar. Agora tem teto.
nb3_post_clionkey() {
    [ "$NB_CLION_KEY" = t ] || return 0
    _dir=${rootmnt?}/etc/skel/.config/JetBrains/${NB_CLION_VERSION:-CLion2024.3}
    mkdir -p "$_dir"
    if ! nb_download /clion.key 1 "$NB_SERVER/secret/clion.key"; then
        nb_warn "CLion licence not available - continuing without it"
        return 0
    fi
    mv /clion.key "$_dir/clion.key"
    _editores=${rootmnt?}/usr/share/maratona-usuario-icpc/editores-config/.config/JetBrains/${NB_CLION_VERSION:-CLion2024.3}
    mkdir -p "$_editores"
    cp -a "$_dir/clion.key" "$_editores/clion.key"
}
