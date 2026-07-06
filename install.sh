#!/usr/bin/env bash
set -e
clear
banner() {
    cat <<'EOF'
__  ___                               
\ \/ / |_ _ __ ___  ___ ___  ___ _ __ 
 \  /| __| '__/ _ \/ __/ __|/ _ \ '__|
 /  \| |_| | |  __/\__ \__ \  __/ |   
/_/\_\\__|_|  \___||___/___/\___|_|
EOF
}

banner
sleep 3
echo ""

echo "==> Atualizando pacotes..."
sudo apt-get update

echo "==> Instalando Ferramentas..."
sudo apt-get install -y stress-ng fio sysstat python3-pip python3-venv

echo "==> Instalando dependências Python (psutil, pyyaml)..."
sudo pip3 install --break-system-packages psutil pyyaml

sleep 3
echo ""
echo "Instalação concluída."
echo "Edite o arquivo config.yaml e rode: sudo python3 benchmark.py config.yaml"