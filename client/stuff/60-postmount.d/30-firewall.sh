# shellcheck shell=sh
# Firewall da maratona + desligamento de serviços que atrapalham a prova.
nb3_post_firewall() {
    log_begin_msg "Configuring the firewall"
    # A base publicada filtra o /etc/hosts com egrep por SUBSTRING sem âncora:
    # o hosts/maratona (escrito no fim desta função) apagava qualquer linha
    # contendo "maratona" — inclusive entradas legítimas do whitelist gravadas
    # pelas iterações anteriores. Enquanto a base não for reconstruída com o
    # pacote corrigido, o script entra aqui por inteiro (idêntico ao commit do
    # maratona-firewall); quando ela vier sem o padrão defeituoso, isto vira
    # no-op sozinho.
    _fwsh="${rootmnt?}/usr/share/maratona-firewall/maratona-firewall-configuration.sh"
    if [ -f "$_fwsh" ] && grep -q 'egrep -v' "$_fwsh"; then
        nb_warn "patching maratona-firewall /etc/hosts filter (old base image)"
        cat > "$_fwsh" << 'NB3FWEOF'
#!/bin/bash

# Reset no ufw - apaga tudo e volta para o padrao
ufw -f reset

# Por padrao, o firewall vem desligado
ufw enable

# Atribuindo o comportamento padrao
# Deve servir tanto para os pacotes ipv4 como o ipv6 que nao se encaixam nas
# regras descritas a seguir.
ufw default deny incoming
ufw default deny outgoing
ufw default deny routed

# Permitindo pacotes na interface loopback - Valido para IPv4 e v6.
ufw allow in on lo
ufw allow out on lo

# Para o $BOCAIP vale tudo
for LATAMHOST in /usr/share/maratona-firewall/hosts/* /etc/maratona-firewall/hosts/*; do
  if [[ ! -e "$LATAMHOST" ]]; then
    continue;
  fi
  HOSTNAME="$(basename $LATAMHOST)"
  echo "Enabling $HOSTNAME"
  for IP in $(< $LATAMHOST); do
    ufw allow out proto udp to $IP
    ufw allow out proto tcp to $IP
  done

  # Only the first IP in the file will have an entry in /etc/hosts
  IP="$(head -n1 $LATAMHOST)"
  TMPFILE=$(mktemp)
  # Compare whole fields, never substrings: the hostname used to be dropped
  # into an unanchored egrep ERE, so a file named "maratona" wiped every line
  # containing that word - including allowlist entries written by previous
  # loop iterations. Unescaped dots in $IP had the same problem.
  awk -v ip="$IP" -v host="$HOSTNAME" '
    /^[[:space:]]*#/ { print; next }
    $1 == ip { next }
    { for (i = 2; i <= NF; i++) if ($i == host) next }
    { print }
  ' /etc/hosts > $TMPFILE
  printf '%s\t%s\n' "$IP" "$HOSTNAME" | cat $TMPFILE - > /etc/hosts
  rm $TMPFILE
done

# configurações para UFW específicas

for MLUFW in /etc/maratona-firewall/ufwrules/*; do
  [[ ! -e "$MLUFW" ]] && continue
  . $MLUFW
done

# Rejeitando os pacotes udp e tcp para qualquer ip
ufw reject out proto udp to any
ufw reject out proto tcp to any

exit 0
NB3FWEOF
        chmod 755 "$_fwsh"
    fi

    if [ -n "$FIREWALL_ALLOWLIST" ]; then
        # formato: "HOSTNAME IP" separados por vírgula
        _old_ifs=$IFS
        IFS=,
        for _entry in $FIREWALL_ALLOWLIST; do
            IFS=$_old_ifs
            _host=$(echo "$_entry" | awk '{print $1}')
            _ip=$(echo "$_entry" | awk '{print $2}')
            # o nome vira NOME DE ARQUIVO: um "hostname" com barra escreveria
            # fora de hosts/, como root, dentro do sistema que a sala monta.
            # O servidor já valida o par, mas o stuff pode ter sido gerado por
            # uma versão anterior.
            case "$_host" in
                */* | .*) nb_warn "ignoring invalid host in the allowlist: $_host"; _host= ;;
                # o hostname da máquina: hosts/maratona é gravado com 127.0.1.1
                # logo abaixo e sobrescreveria a entrada em silêncio. O servidor
                # recusa o nome, mas o stuff pode vir de uma versão anterior.
                maratona) nb_warn "allowlist name 'maratona' is reserved (machine hostname) - skipped"; _host= ;;
            esac
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
    #rm -f "${rootmnt?}/etc/cron.d/cron-boca-submit" "${rootmnt?}/etc/cron.d/cron-boca-log"
    log_end_msg
}
