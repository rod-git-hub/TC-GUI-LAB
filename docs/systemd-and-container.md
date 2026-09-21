# Switching between systemd and the container

TC Lab runs two ways: as a **systemd service** installed to `/opt/tc_lab`, or as a
**container** that shares the host network namespace. Both manage the same real
interfaces on the same host.

This guide covers moving between them without losing your lab.

> **Which one should you run?**
> systemd is the simpler, more established path. The container is more confined —
> it drops every capability except `NET_ADMIN` and `NET_RAW`, sets
> `no-new-privileges`, and runs on a read-only root filesystem — but it needs the
> host prerequisites below and is the less-travelled route.

---

## Two rules before you start

### 1. Only one of them may run at a time

Both bind port 5000, and — far more important — **both adopt and re-apply `tc` rules
to the host's live interfaces on start.** Two instances will fight over your
impairments, and a crash-looping container will re-apply them in a loop.

Always shut one down completely before starting the other:

```bash
sudo systemctl disable --now tc_lab
```

`disable` matters as much as `stop`. Without it the service comes back at the next
reboot and quietly starts fighting the container.

### 2. The container's volume starts empty

The container keeps its state in a Docker volume named `tc-lab-state`, which has
**no connection to `/opt/tc_lab`**. On a fresh start it is empty, and the app
behaves exactly as it would on a brand-new install.

That means that unless you copy state across:

| | If you don't migrate it |
|---|---|
| `config.json` | Bind address, port and idle timeout revert to defaults |
| `network_config.json` | **Your bridges and VLANs are not recreated at the next reboot** |
| `state.json` | Saved impairments are not re-applied |
| `labels.json` | Interface labels are gone |
| `profiles/` | Your custom presets are gone (shipped ones are re-seeded) |
| `users.json` | Fresh `admin` / `tclab123` |
| `cert.pem`, `key.pem` | A new self-signed cert, so a new browser warning |
| `secret_key.txt` | Everyone is signed out |

The first five are the ones that matter. **`network_config.json` is the dangerous
one** — your live bridges and VLANs stay up when you switch, so everything *looks*
fine. You only discover the loss at the next reboot, when nothing comes back.

Accounts and certificates are usually fine to let regenerate. Decide deliberately.

---

## Host prerequisites (container only)

Under host networking the container cannot load kernel modules itself — it has no
`CAP_SYS_MODULE`, by design. Load them on the host:

```bash
sudo cp modules-load.d/tc-lab.conf /etc/modules-load.d/
sudo modprobe 8021q sch_netem
```

The first line makes it survive a reboot. Skip this and VLAN creation fails with a
confusing "not supported" error.

For bridged or routed labs you also want:

```bash
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward
```

---

## Installing Docker changes host networking — read this first

If Docker is not yet installed, installing it does two things that can stop lab
traffic dead:

1. It loads **`br_netfilter`**, whose sysctls default to `1`, so *bridged* frames
   start traversing iptables.
2. It sets the iptables **`FORWARD` policy to `DROP`**.

Together those mean frames bridged between two lab interfaces go through the
`FORWARD` chain and get dropped. The bridge still shows as up, members still show as
`forwarding`, `tc` still shows your impairments — and no traffic crosses. It is a
genuinely confusing failure because everything you would normally check looks right.

Apply the supplied drop-in as part of installing Docker:

```bash
sudo cp sysctl.d/tc-lab.conf /etc/sysctl.d/ && sudo sysctl --system
```

Then confirm:

```bash
sysctl net.bridge.bridge-nf-call-iptables && sudo iptables -S FORWARD | head -1
```

`bridge-nf-call-iptables = 0` means bridged frames bypass iptables regardless of what
the `FORWARD` policy says. If the key does not exist at all, `br_netfilter` is not
loaded and you have nothing to worry about yet.

> This is also why `br_netfilter` is **not** in `modules-load.d/tc-lab.conf`. TC Lab
> never needs it — it exists to expose bridged traffic to iptables, which is the
> opposite of what an L2 impairment path wants.

---

## systemd → container

### 1. Stop the service

```bash
sudo systemctl disable --now tc_lab
```

Your bridges, VLANs and current impairments stay up — they live in the kernel, not
in the app.

### 2. Build the image

```bash
docker compose build
```

On **Debian 13** this fails with a buildx version error (Debian ships buildx 0.13;
the compose plugin wants 0.17 or newer). Build it in two steps instead:

```bash
sudo DOCKER_BUILDKIT=0 docker build -t tc-lab:latest .
```

### 3. Seed the volume

Create the volume and copy your state into it **before the first start**:

```bash
docker volume create tc-lab-state
```

```bash
VOL=$(docker volume inspect tc-lab-state -f '{{.Mountpoint}}') && sudo mkdir -p "$VOL/profiles" && sudo cp /opt/tc_lab/config.json /opt/tc_lab/network_config.json /opt/tc_lab/state.json /opt/tc_lab/labels.json "$VOL/" 2>/dev/null; sudo cp /opt/tc_lab/profiles/*.json "$VOL/profiles/" 2>/dev/null; sudo ls -la "$VOL"
```

That copies the five things worth keeping and leaves accounts and certificates to
regenerate. To carry those over as well, add `users.json`, `secret_key.txt`,
`cert.pem` and `key.pem` to the same `cp`.

> If `docker volume inspect` prints nothing, the volume name is wrong. Check with
> `docker volume ls`. The name is pinned in `docker-compose.yml`, so it should be
> exactly `tc-lab-state`.

### 4. Start

```bash
docker compose up -d
```

### 5. Verify

```bash
docker compose logs --tail 40
```

Look for `restore_network.sh` reporting your bridges as *already exists — brought
up* rather than *CREATED*, which confirms it read your migrated topology. Then open
`https://<host-ip>:5000` and check that your interfaces, bridges and impairments are
all present.

Confirm the impairments are real, from the host:

```bash
sudo tc qdisc show dev <your-interface>
```

---

## container → systemd

### 1. Stop the container

```bash
docker compose down
```

`down` removes the container but **keeps the volume**. Use `docker compose down -v`
only when you intend to destroy your state.

### 2. Copy state out of the volume

```bash
VOL=$(docker volume inspect tc-lab-state -f '{{.Mountpoint}}') && sudo mkdir -p /opt/tc_lab/profiles && sudo cp "$VOL"/config.json "$VOL"/network_config.json "$VOL"/state.json "$VOL"/labels.json /opt/tc_lab/ 2>/dev/null; sudo cp "$VOL"/profiles/*.json /opt/tc_lab/profiles/ 2>/dev/null; sudo ls -la /opt/tc_lab
```

Do this **before** running the installer, so the state is in place when the service
first starts.

### 3. Install the service

```bash
sudo bash setup.sh
```

It preserves everything you just copied — it writes `config.json` only when absent,
excludes runtime state from its file copy, and asks before touching accounts.

### 4. Verify

```bash
sudo systemctl status tc_lab
```

```bash
journalctl -u tc_lab -n 40
```

Same check as above: bridges should be reported as already existing, not created.

---

## What is shared, and what is not

| | systemd | Container |
|---|---|---|
| Host interfaces, bridges, VLANs | the same ones | the same ones |
| `tc` rules currently on the kernel | the same ones | the same ones |
| App state (accounts, topology, impairments, profiles) | `/opt/tc_lab` | `tc-lab-state` volume |
| Privileges | unconfined root | root limited to `NET_ADMIN` + `NET_RAW` |
| Root filesystem | read-write | read-only + state volume |
| Python | the host's (3.13 on Debian 13) | `python:3.12-slim` in the image |

The top two rows are why only one may run at a time. The third is why migration is a
manual step.

---

## Troubleshooting

**Everything looks fine, but nothing comes back after a reboot.**
`network_config.json` was not migrated. The live topology survived the switch
because it lives in the kernel; the saved copy did not. Re-create the topology
through the UI once — any successful change rewrites the file — or copy it across
and restart.

**VLAN creation fails with "not supported".**
The host has not loaded `8021q`. See *Host prerequisites*. The container cannot load
it for you.

**Impairments get re-applied repeatedly, or values keep changing.**
Two instances are running. Check both `systemctl is-active tc_lab` and
`docker ps`. Disable the one you are not using.

If you deliberately need a second instance on a host whose interfaces something else
manages, start it with `TC_LAB_SKIP_RESTORE=1` — it then comes up without restoring
topology, re-applying `tc`, or adopting anything already on the host.

**Every action fails with a CSRF token error after switching.**
The page is cached from the other instance. Hard-refresh with `Ctrl-Shift-R`.

**`docker compose build` fails on a buildx version error.**
Debian 13. Use the two-step build in *systemd → container*, step 2.

**Bridges are up and impairments are set, but no traffic crosses.**
Docker's `FORWARD` policy plus `br_netfilter`. See *Installing Docker changes host
networking* above. Quick check:
`sysctl net.bridge.bridge-nf-call-iptables` — if it is `1`, apply the drop-in.

**`docker0` shows up in the interface list.**
Expected — Docker creates it. It is deliberately excluded from saved topology and
from config exports, and restore never touches it, so it cannot end up in a bundle
or be recreated on another host.
