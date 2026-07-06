# XTresser / Benchmark

Ferramenta para testar se uma máquina aguenta operar como
servidor multitarefas (VPS, containers, múltiplos serviços), simulando
carga de **CPU**, **memória** e **I/O de disco (leitura/escrita)** com
horários de pico de tráfego configuráveis.

## Como funciona

O script lê um `config.yaml` com:

- Um perfil **default** (carga "normal", fora de pico).
- Uma lista de **peaks**: janelas de horário (ex: 08:00–09:30) com
  intensidade de carga própria (mais threads de CPU, mais MB de I/O, etc).

A cada `interval_seconds`, o script detecta se o horário atual está dentro
de alguma janela de pico e dispara, em paralelo:

- `stress-ng` para CPU e memória
- `fio` para leitura/escrita real em disco

Enquanto isso, coleta métricas do sistema (`psutil` + `os.getloadavg()`) a
cada segundo: uso de CPU, uso de memória, throughput de disco e load average.

Ao final, gera:

- `bench_report_<timestamp>.csv` — série temporal completa
- `bench_summary_<timestamp>.txt` — resumo (min/max/média por perfil + alertas)

## Instalação

```bash
git clone https://github.com/Th3f1x/Xtresser.git
cd Xtresser
sudo chmod +x install.sh
./install.sh
```

Isso instala `stress-ng`, `fio`, `sysstat` e as libs Python `psutil`/`pyyaml`.

## Configuração

Edite `config.yaml`:

```yaml
work_dir: "/tmp/bench_io"       # onde o fio vai escrever os arquivos de teste
duration_minutes: 60            # duração total do teste
interval_seconds: 15            # granularidade da amostragem

default:
  cpu_load_percent: 20
  cpu_workers: 2
  io_read_mb: 50
  io_write_mb: 20
  io_workers: 2
  mem_workers: 1
  mem_size_mb: 256

peaks:
  - label: "pico_manha"
    start: "08:00"
    end: "09:30"
    cpu_load_percent: 85
    cpu_workers: 8
    io_read_mb: 400
    io_write_mb: 150
    io_workers: 6
    mem_workers: 4
    mem_size_mb: 512
```

Você pode adicionar quantas janelas de pico quiser (manhã, almoço, noite,
fim de semana, backup noturno, etc). Se quiser simular um "dia inteiro"
rapidamente, ajuste `duration_minutes` e os horários para caberem num teste
curto (ex: rodar o teste às 14:00 mas configurar o pico pra começar às 14:01).

**Importante:** use `work_dir` apontando para o mesmo disco/partição onde
o servidor real vai gravar dados (ex: `/var/lib/docker` se for testar
volumes de containers), para o teste de I/O ser representativo.

## Rodando

```bash
sudo python3 benchmark.py config.yaml
```

`sudo` é recomendado para permitir `--direct=1` no fio (I/O sem cache,
mais realista para medir o disco de verdade em vez do cache de RAM).

O script imprime uma linha por ciclo, por exemplo:

```bash
[2026-07-04 08:15:03] perfil=pico_manha    cpu= 84.2% mem= 61.3% load1=6.10
```

Pressione `Ctrl+C` a qualquer momento para interromper e ainda assim gerar
um resumo parcial.

## Interpretando o resultado

No `bench_summary_*.txt`, observe por perfil (pico vs normal):

- **CPU% médio/máx**: se ficar perto de 100% durante os picos, a CPU é
  gargalo nesses horários.
- **Load1 (load average de 1 min)**: compare com o número de núcleos da
  máquina (`nproc`). Se `load1` ficar consistentemente acima do número de
  núcleos durante o pico, há mais trabalho do que a CPU consegue processar
  em tempo real — sinal de que a máquina vai "engasgar" com múltiplos
  serviços simultâneos.
- **MEM%**: próximo de 90-100% indica risco de swap/OOM killer sob carga
  real.
- **Alertas**: contagem de amostras que passaram dos limites definidos em
  `thresholds` no config.

Se os números ficarem confortáveis mesmo nos picos configurados (com
margem para os serviços reais que você vai hospedar), a máquina tende a
aguentar o cenário multitarefas. Se não, considere reduzir o número de
serviços por máquina, aumentar recursos (CPU/RAM/disco NVMe), ou usar
containers com limites (`docker run --cpus`, `--memory`) para isolar
picos de um serviço não afetarem os demais.

## Limpeza

Os arquivos temporários de teste de I/O (`work_dir`) são removidos
automaticamente ao final da execução (ou ao interromper com Ctrl+C).

>### Disclaimer
>
>Ferramenta foi desenvolvida para testar servidores linux headless
>para hospedagem de serviços Docker, VMs, DBs e automações.
>Podendo ser utilizado como benchmark para outras finalidades.
>
>Este é um projeto Open Source sob a licença `Apache License 2.0`
>Encorajando a utilização, modificação e a distribuição deste software.
>
>"Close the world / Open the next"
>By: @Th3f1x
