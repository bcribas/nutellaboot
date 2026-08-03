# shellcheck shell=sh
# Firewall da maratona + desligamento de serviços que atrapalham a prova.
nb3_post_firewall() {
    log_begin_msg "Configuring the firewall"
    if [ -n "$FIREWALL_ALLOWLIST" ]; then
        # formato: "HOSTNAME IP" separados por vírgula
        _old_ifs=$IFS
        IFS=,
        for _entry in $FIREWALL_ALLOWLIST; do
            IFS=$_old_ifs
            _host=$(echo "$_entry" | awk '{print $1}')
            _ip=$(echo "$_entry" | awk '{print $2}')
            [ -n "$_host" ] && [ -n "$_ip" ] &&
                echo "$_ip" > "${rootmnt?}/usr/share/maratona-firewall/hosts/$_host"
            IFS=,
        done
        IFS=$_old_ifs
    fi
    [ "$DISABLE_FIREWALL" = t ] &&
        ln -s /dev/null "${rootmnt?}/etc/systemd/system/maratona-firewall.service"

    echo 127.0.1.1 > "${rootmnt?}/usr/share/maratona-firewall/hosts/maratona"
    ln -s /dev/null "${rootmnt?}/etc/systemd/system/systemd-resolved.service"
    rm -f "${rootmnt?}/etc/resolv.conf"
    cp /etc/resolv.conf "${rootmnt?}/etc/resolv.conf"
    for _svc in cups cups-browsed avahi-daemon ModemManager unattended-upgrades \
        webfs exim4 fwupd networkd-dispatcher geoclue packagekit; do
        ln -s /dev/null "${rootmnt?}/etc/systemd/system/$_svc.service"
    done
    rm -f "${rootmnt?}/etc/cron.d/cron-boca-submit" "${rootmnt?}/etc/cron.d/cron-boca-log"
    log_end_msg
}
