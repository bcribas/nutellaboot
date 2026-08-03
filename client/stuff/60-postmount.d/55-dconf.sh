# shellcheck shell=sh
# Teclados, navegador padrão e ajustes de shell via dconf.
nb3_post_dconf() {
    _db=${rootmnt?}/etc/dconf/db/local.d
    mkdir -p "$_db/locks"

    if [ -n "$INPUT_SOURCES" ]; then
        cat > "$_db/80-keyboards" << EOF
[org/gnome/desktop/input-sources]
sources=[$INPUT_SOURCES]
EOF
    fi

    if [ -n "$DEFAULTBROWSERURL" ]; then
        # texto livre indo para dentro de aspas simples do GVariant: uma aspa
        # no endereço quebraria o keyfile, e o dconf recusa o local.d inteiro
        _url=$(nb3_gvariant_escape "$DEFAULTBROWSERURL")
        cat > "$_db/90-browserurl" << EOF
[org/gnome/epiphany]
restore-session-policy='crashed'
homepage-url='$_url'
EOF
        echo "/org/gnome/epiphany/homepage-url" > "$_db/locks/90-browserurl"
    fi

    cat > "$_db/99-shomount" << 'EOF'
[org/gnome/shell/extensions/dash-to-dock]
show-mounts=false
EOF

    # A base já aponta `picture-uri` para o papel de parede da sede e trava a
    # chave, mas deixa `picture-uri-dark` no padrão do Ubuntu: numa máquina em
    # tema escuro aparece o fundo da Canonical, e com ele some o carimbo da
    # sede que o 70-wallpaper.sh desenha.
    cat > "$_db/91-wallpaper-dark" << 'EOF'
[org/gnome/desktop/background]
picture-uri-dark='file:///usr/share/maratona-background/maratona-common-wallpaper.png'

[org/gnome/desktop/screensaver]
picture-uri-dark='file:///usr/share/maratona-background/maratona-common-wallpaper.png'
EOF
    echo "/org/gnome/desktop/background/picture-uri-dark" > "$_db/locks/91-wallpaper-dark"
}
