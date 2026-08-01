# shellcheck shell=sh
# rc.local + agente de telemetria (long-poll de comandos).
nb3_post_rclocal() {
    mkdir -p "${rootmnt?}/etc/rc.local.d"
    cat > "${rootmnt?}/etc/rc.local" << 'EOF'
#!/bin/bash
. /etc/.nb3
run-parts /etc/rc.local.d/
dconf update || true
EOF
    chmod a+x "${rootmnt?}/etc/rc.local"

    cat > "${rootmnt?}/etc/rc.local.d/zz-agent" << 'EOF'
#!/bin/bash
(sleep 20; bash /usr/share/mlog/agent.sh) &>/dev/null & disown
EOF
    chmod a+x "${rootmnt?}/etc/rc.local.d/zz-agent"
}
