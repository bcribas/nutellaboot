# shellcheck shell=sh
# Firewall da maratona + desligamento de serviços que atrapalham a prova.
nb3_post_firewall() {
    # O maratona-firewall vem assado na camada base, e o filtro do /etc/hosts
    # dele estava errado de três jeitos, um por versão:
    #  - egrep por SUBSTRING sem âncora (20230113): o hosts/maratona apagava
    #    toda linha com "maratona", inclusive entradas do allowlist;
    #  - a mesma regex com grep --invert-match (20240530, a base publicada);
    #  - o awk por campo que ainda descartava pelo IP: dois nomes atrás do
    #    mesmo proxy (moj e nutellaboot de uma sede) se apagavam.
    # A primeira troca daqui só reconhecia o egrep e nunca disparou na base
    # publicada. Enquanto a base não vier com o pacote corrigido, o script
    # entra aqui por inteiro, idêntico ao maratona-firewall-configuration.sh
    # do pacote (commit "Match /etc/hosts entries by whole field, and keep
    # names sharing an IP"); com a base corrigida, isto vira no-op sozinho.
    # O texto abaixo não pode conter nenhum dos três padrões do gatilho.
    #
    # A troca vale em todo boot até a base ser reconstruída: vai na própria
    # linha do firewall, não num aviso, que a sala leria como defeito.
    _fwsh="${rootmnt?}/usr/share/maratona-firewall/maratona-firewall-configuration.sh"
    if [ -f "$_fwsh" ] && grep -qF -e 'egrep -v' -e '--invert-match' -e '$1 == ip { next }' "$_fwsh"; then
        log_begin_msg "Configuring the firewall (with the /etc/hosts filter fix)"
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
  HOSTNAME="$(basename "$LATAMHOST")"
  echo "Enabling $HOSTNAME"
  for IP in $(< "$LATAMHOST"); do
    ufw allow out proto udp to "$IP"
    ufw allow out proto tcp to "$IP"
  done

  # Only the first IP in the file will have an entry in /etc/hosts.
  # Compare whole fields, never substrings: a regex built from the name and
  # the IP wiped every line containing them (the file named "maratona" took
  # any allowlist entry with that word, and unescaped dots matched other
  # addresses). Dropping by IP made two names behind the same proxy erase
  # each other, so only this name's old line goes. The exception is
  # 127.0.1.1, the machine's own name: there the old line (the hostname of
  # the machine that built the image) goes by address too.
  IP="$(head -n1 "$LATAMHOST")"
  TMPFILE=$(mktemp)
  awk -v ip="$IP" -v host="$HOSTNAME" '
    /^[[:space:]]*#/ { print; next }
    $1 == ip && ip == "127.0.1.1" { next }
    { for (i = 2; i <= NF; i++) if ($i == host) next }
    { print }
  ' /etc/hosts > "$TMPFILE"
  printf '%s\t%s\n' "$IP" "$HOSTNAME" | cat "$TMPFILE" - > /etc/hosts
  rm "$TMPFILE"
done

# configurações para UFW específicas

for MLUFW in /etc/maratona-firewall/ufwrules/*; do
  [[ ! -e "$MLUFW" ]] && continue
  . "$MLUFW"
done

# Rejeitando os pacotes udp e tcp para qualquer ip
ufw reject out proto udp to any
ufw reject out proto tcp to any

exit 0
NB3FWEOF
        chmod 755 "$_fwsh"
    else
        log_begin_msg "Configuring the firewall"
    fi

    # os nomes que o nutellaboot pôs: o syncfirewall do agente só remove
    # esses quando saem da lista (os da camada base não são dele)
    : > "${rootmnt?}/etc/nb3-firewall-allowlist"
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
                echo "$_ip" > "${rootmnt?}/usr/share/maratona-firewall/hosts/$_host" &&
                echo "$_host" >> "${rootmnt?}/etc/nb3-firewall-allowlist"
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
