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
        cat > "$_db/90-browserurl" << EOF
[org/gnome/epiphany]
restore-session-policy='crashed'
homepage-url='$DEFAULTBROWSERURL'
EOF
        echo "/org/gnome/epiphany/homepage-url" > "$_db/locks/90-browserurl"
    fi

    cat > "$_db/99-shomount" << 'EOF'
[org/gnome/shell/extensions/dash-to-dock]
show-mounts=false
EOF
}
