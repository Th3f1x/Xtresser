#!/usr/bin/env python3

#XTresser-server / Benchmark
#==================================

#Simula carga de CPU, memória e I/O de disco (leitura/escrita) em uma máquina
#Ubuntu Server, respeitando horários de pico configuráveis, e registra
#métricas do sistema ao longo do tempo para avaliar se a máquina aguenta
#operar como servidor multitarefas.

#Uso:
#    sudo python3 benchmark.py config.yaml

#Requisitos:
#    - stress-ng
#    - fio
#    - python3 packages: psutil, pyyaml
#    (rode install.sh para instalar tudo)

#Saída:
#    - bench_report_<timestamp>.csv  -> série temporal de métricas
#    - bench_summary_<timestamp>.txt -> resumo final (min/max/médio por perfil)


import argparse
import csv
import datetime as dt
import os
import shutil
import subprocess
import sys
import time

try:
    import psutil
    import yaml
except ImportError:
    print("Dependências faltando. Rode: sudo pip3 install --break-system-packages psutil pyyaml")
    sys.exit(1)


def check_binaries():
    missing = [b for b in ("stress-ng", "fio") if shutil.which(b) is None]
    if missing:
        print(f"Faltando binários: {', '.join(missing)}. Rode ./install.sh primeiro.")
        sys.exit(1)


def parse_hhmm(s):
    h, m = map(int, s.split(":"))
    return dt.time(hour=h, minute=m)


def time_in_window(now_t, start_t, end_t):
    #for tasks that span midnight, e.g. 22:00-02:00.
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    else:
        return now_t >= start_t or now_t <= end_t


def active_profile(cfg, now_dt):
    now_t = now_dt.time()
    for peak in cfg.get("peaks", []):
        if time_in_window(now_t, parse_hhmm(peak["start"]), parse_hhmm(peak["end"])):
            return peak
    return cfg["default"]


def run_cpu_stress(profile, duration_s):
    workers = profile.get("cpu_workers", 1)
    load = profile.get("cpu_load_percent", 20)
    cmd = [
        "stress-ng",
        "--cpu", str(workers),
        "--cpu-load", str(load),
        "--timeout", f"{duration_s}s",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_mem_stress(profile, duration_s):
    workers = profile.get("mem_workers", 0)
    if workers <= 0:
        return None
    size_mb = profile.get("mem_size_mb", 256)
    cmd = [
        "stress-ng",
        "--vm", str(workers),
        "--vm-bytes", f"{size_mb}M",
        "--timeout", f"{duration_s}s",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_io_stress(profile, work_dir, duration_s):
    os.makedirs(work_dir, exist_ok=True)
    jobs = profile.get("io_workers", 1)
    read_mb = profile.get("io_read_mb", 50)
    write_mb = profile.get("io_write_mb", 20)

    cmd = [
        "fio",
        "--name=bench",
        f"--directory={work_dir}",
        "--rw=readwrite",
        f"--rwmixread={int(100 * read_mb / max(read_mb + write_mb, 1))}",
        "--bs=64k",
        f"--size={read_mb + write_mb}M",
        f"--numjobs={jobs}",
        "--time_based",
        f"--runtime={duration_s}",
        "--group_reporting",
        "--output-format=normal",
        "--direct=1",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sample_system_metrics():
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk_io = psutil.disk_io_counters()
    load1, load5, load15 = os.getloadavg()
    return {
        "cpu_percent": cpu,
        "mem_percent": mem.percent,
        "mem_used_mb": round(mem.used / 1024 / 1024, 1),
        "disk_read_mb": round(disk_io.read_bytes / 1024 / 1024, 1),
        "disk_write_mb": round(disk_io.write_bytes / 1024 / 1024, 1),
        "load1": load1,
        "load5": load5,
        "load15": load15,
    }


def main():
    parser = argparse.ArgumentParser(description="Server load simulator / benchmark")
    parser.add_argument("config", help="Caminho para config.yaml")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("Aviso: rode com sudo para leituras de I/O mais precisas (direct I/O).")

    check_binaries()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    duration_minutes = cfg.get("duration_minutes", 60)
    interval_s = cfg.get("interval_seconds", 15)
    work_dir = cfg.get("work_dir", "/tmp/bench_io")
    thresholds = cfg.get("thresholds", {})

    end_time = time.time() + duration_minutes * 60
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"bench_report_{ts}.csv"
    summary_path = f"bench_summary_{ts}.txt"

    fieldnames = [
        "timestamp", "profile", "cpu_percent", "mem_percent", "mem_used_mb",
        "disk_read_mb", "disk_write_mb", "load1", "load5", "load15", "alerta",
    ]

    rows = []
    print(f"Iniciando benchmark por {duration_minutes} min. Log: {csv_path}")
    print("Pressione Ctrl+C para interromper antes do fim, se necessário.\n")

    try:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            while time.time() < end_time:
                now_dt = dt.datetime.now()
                profile = active_profile(cfg, now_dt)
                label = profile.get("label", "?")

                procs = []
                procs.append(run_cpu_stress(profile, interval_s))
                p_mem = run_mem_stress(profile, interval_s)
                if p_mem:
                    procs.append(p_mem)
                procs.append(run_io_stress(profile, work_dir, interval_s))

                sub_samples = []
                start_sub = time.time()
                while time.time() - start_sub < interval_s:
                    sub_samples.append(sample_system_metrics())
                    time.sleep(1)

                for p in procs:
                    p.wait()

                avg = {
                    k: round(sum(s[k] for s in sub_samples) / len(sub_samples), 2)
                    for k in ["cpu_percent", "mem_percent", "load1", "load5", "load15"]
                }
                last = sub_samples[-1]

                alerta = []
                if avg["cpu_percent"] >= thresholds.get("cpu_percent_critical", 999):
                    alerta.append("CPU")
                if avg["mem_percent"] >= thresholds.get("mem_percent_critical", 999):
                    alerta.append("MEM")

                row = {
                    "timestamp": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "profile": label,
                    "cpu_percent": avg["cpu_percent"],
                    "mem_percent": avg["mem_percent"],
                    "mem_used_mb": last["mem_used_mb"],
                    "disk_read_mb": last["disk_read_mb"],
                    "disk_write_mb": last["disk_write_mb"],
                    "load1": avg["load1"],
                    "load5": avg["load5"],
                    "load15": avg["load15"],
                    "alerta": ",".join(alerta) if alerta else "",
                }
                writer.writerow(row)
                f.flush()
                rows.append(row)

                status = f" [ALERTA: {row['alerta']}]" if row["alerta"] else ""
                print(
                    f"[{row['timestamp']}] perfil={label:14s} "
                    f"cpu={row['cpu_percent']:5.1f}% mem={row['mem_percent']:5.1f}% "
                    f"load1={row['load1']:.2f}{status}"
                )

    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário. Gerando resumo parcial...")

    finally:
        # Clean temporary I/O files.
        shutil.rmtree(work_dir, ignore_errors=True)
        write_summary(rows, summary_path, thresholds)
        print(f"\nRelatório detalhado: {csv_path}")
        print(f"Resumo: {summary_path}")


def write_summary(rows, path, thresholds):
    if not rows:
        with open(path, "w") as f:
            f.write("Nenhuma amostra coletada.\n")
        return

    by_profile = {}
    for r in rows:
        by_profile.setdefault(r["profile"], []).append(r)

    lines = []
    lines.append("RESUMO DO BENCHMARK")
    lines.append("=" * 50)
    lines.append(f"Total de amostras: {len(rows)}")
    lines.append("")

    total_alertas = [r for r in rows if r["alerta"]]
    lines.append(f"Amostras com alerta: {len(total_alertas)} de {len(rows)}")
    lines.append("")

    for profile, items in by_profile.items():
        cpu_vals = [r["cpu_percent"] for r in items]
        mem_vals = [r["mem_percent"] for r in items]
        load_vals = [r["load1"] for r in items]
        lines.append(f"Perfil: {profile}  ({len(items)} amostras)")
        lines.append(
            f"  CPU%   min={min(cpu_vals):.1f} max={max(cpu_vals):.1f} "
            f"media={sum(cpu_vals)/len(cpu_vals):.1f}"
        )
        lines.append(
            f"  MEM%   min={min(mem_vals):.1f} max={max(mem_vals):.1f} "
            f"media={sum(mem_vals)/len(mem_vals):.1f}"
        )
        lines.append(
            f"  Load1  min={min(load_vals):.2f} max={max(load_vals):.2f} "
            f"media={sum(load_vals)/len(load_vals):.2f}"
        )
        alertas_perfil = [r for r in items if r["alerta"]]
        lines.append(f"  Alertas: {len(alertas_perfil)}")
        lines.append("")

    lines.append("Limites configurados:")
    lines.append(f"  CPU crítico: {thresholds.get('cpu_percent_critical', 'n/a')}%")
    lines.append(f"  MEM crítico: {thresholds.get('mem_percent_critical', 'n/a')}%")
    lines.append("")
    lines.append(
        "Interpretação rápida: se 'Load1' ficou consistentemente acima do número"
        " de núcleos da máquina durante os picos, ou se houve muitos alertas de"
        " CPU/MEM, a máquina provavelmente vai sofrer para rodar múltiplos"
        " serviços simultâneos nesses horários."
    )

    with open(path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
