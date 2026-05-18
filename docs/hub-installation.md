# Hub Cluster Installation Guide

This guide walks through deploying a compact three-node OpenShift Hub cluster on bare metal using the Agent-Based Installer, then bootstrapping ACM and ArgoCD to establish the GitOps foundation.

---

## Table of Contents

1. [Hardware Requirements](#1-hardware-requirements)
2. [Network Planning](#2-network-planning)
3. [Control Node Setup](#3-control-node-setup)
4. [Fork and Configure the Repository](#4-fork-and-configure-the-repository)
5. [Configure Inventory — Cluster Identity](#5-configure-inventory--cluster-identity)
6. [Configure Inventory — Node Details](#6-configure-inventory--node-details)
7. [Configure Secrets](#7-configure-secrets)
8. [Configure Operational Variables](#8-configure-operational-variables)
9. [Run the Installation](#9-run-the-installation)
10. [Verify the Hub Cluster](#10-verify-the-hub-cluster)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Hardware Requirements

The hub cluster runs as a three-node compact cluster — all nodes are control plane (master) nodes that also schedule workloads (no dedicated workers required).

### Per Node (minimum)

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 16 cores | 32+ cores |
| RAM | 64 GB | 128 GB |
| Boot disk | 120 GB SSD | 240 GB NVMe |
| Data disks | — | 2× SSD for ODF (if using local storage) |
| Network | 1 GbE | 10 GbE |

### BMC (Baseboard Management Controller)

Each node must have an out-of-band BMC reachable from the Ansible control node:

- **Dell iDRAC 8/9** — uses the `dellemc.openmanage` collection for virtual media and the `community.general.redfish_command` module for power control
- **Other vendors** — generic Redfish support is available; you may need to adjust `ansible/tasks/bmc_virtual_media.yml` for your BMC's virtual media endpoint

### HTTP Staging Server

A dedicated host (or the control node itself) that can serve files over plain HTTP. The agent ISO (~1 GB) is transferred here so each node's BMC can mount it as a virtual DVD.

---

## 2. Network Planning

Before starting, document the following for your environment. All values must be consistent across inventory files, DNS, and DHCP/static assignments.

### Required Address Assignments

| Purpose | Example | Notes |
|---------|---------|-------|
| Node 1 IP | `192.168.1.10` | Static, routable |
| Node 2 IP | `192.168.1.11` | Static, routable |
| Node 3 IP | `192.168.1.12` | Static, routable |
| API VIP | `192.168.1.10` | Can be node 1 IP for compact clusters; set in DNS as `api.<cluster>.<domain>` |
| Ingress VIP | `192.168.1.10` | Often same node for compact; set in DNS as `*.apps.<cluster>.<domain>` |
| MetalLB pool | `192.168.1.200–220` | Reserved range; must not overlap with node IPs |
| BMC node 1 | `192.168.0.11` | Out-of-band management network |
| BMC node 2 | `192.168.0.12` | |
| BMC node 3 | `192.168.0.13` | |
| HTTP server | `192.168.1.5` | Serves the agent ISO |

### Required DNS Records

```
api.hub.example.com.        A  192.168.1.10
*.apps.hub.example.com.     A  192.168.1.10
```

For production, use a floating VIP managed by keepalived/HAProxy and point both records at the VIP. For a single-site compact cluster the API VIP and the ingress VIP are commonly the same address.

### Network CIDRs

These are internal to the cluster and must not overlap with your infrastructure network:

| Network | Default | Purpose |
|---------|---------|---------|
| Machine network | `192.168.1.0/24` | Your physical node subnet |
| Cluster network | `10.128.0.0/14` | Pod CIDR (internal) |
| Service network | `172.30.0.0/16` | ClusterIP CIDR (internal) |

---

## 3. Control Node Setup

### Install the OpenShift CLI tools

```bash
# Download for your OCP version (4.20 shown)
OCP_VERSION=4.20.0
curl -LO "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OCP_VERSION}/openshift-install-linux.tar.gz"
curl -LO "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OCP_VERSION}/openshift-client-linux.tar.gz"
tar xzf openshift-install-linux.tar.gz -C /usr/local/bin
tar xzf openshift-client-linux.tar.gz -C /usr/local/bin
```

### Create an Ansible virtual environment

```bash
python3 -m venv ~/ansible-venv
source ~/ansible-venv/bin/activate
pip install ansible-core==2.16.* kubernetes openshift jmespath
```

### Install Ansible collections

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml
pip install -r requirements.txt
```

---

## 4. Fork and Configure the Repository

**Fork this repository** before making any changes — your fork becomes the GitOps source of truth that ArgoCD tracks.

```bash
# After forking on GitHub:
git clone https://github.com/<your-org>/openshift-acm-app-of-apps
cd openshift-acm-app-of-apps
```

Update `gitops_repo` in `ansible/vars/acm_config.yml` to point at your fork:

```yaml
gitops_repo: "https://github.com/<your-org>/openshift-acm-app-of-apps"
```

If the repository is private, add credentials to `ansible/values-secret.yaml` under the `gitops_repo` key (see [Section 7](#7-configure-secrets)).

---

## 5. Configure Inventory — Cluster Identity

Edit `ansible/inventory/group_vars/hub_nodes.yml`:

```yaml
# Cluster identity — must match DNS records
cluster_name: "hub"           # becomes <cluster_name>.<base_domain>
base_domain: "example.com"

# Rendezvous IP: one hub node IP used by the Agent-Based Installer
# as the bootstrap coordination point. Usually node 1.
rendezvous_ip: "192.168.1.10"

# Machine network = the physical subnet the nodes live on
machine_network_cidr: "192.168.1.0/24"

# Internal cluster CIDRs — change only if they conflict with your infrastructure
cluster_network_cidr: "10.128.0.0/14"
cluster_network_host_prefix: 23
service_network_cidr: "172.30.0.0/16"
network_type: "OVNKubernetes"   # recommended for bare metal

# platform: none — no cloud provider integration
platform_type: "none"

# Default network interface name (override per node in host_vars if different)
node_interface: "eno1"
```

---

## 6. Configure Inventory — Node Details

Each hub node gets its own file under `ansible/inventory/host_vars/`. Create or edit `hub-node1.yml`, `hub-node2.yml`, and `hub-node3.yml`.

### Template: `ansible/inventory/host_vars/hub-nodeN.yml`

```yaml
node:
  hostname: "hub-node1"           # short hostname, not FQDN
  domain: "{{ base_domain }}"     # inherits from group_vars/hub_nodes.yml
  ipv4_address: "192.168.1.10"    # static IP on the machine network
  ipv4_prefix: 24                 # prefix length (not netmask)
  ipv4_gateway: "192.168.1.1"
  ipv4_dns: "192.168.1.1"         # resolver — can be the same as gateway
  mac: "aa:bb:cc:dd:ee:01"        # MAC of the primary network interface
  interface: "eno1"               # NIC name (override if different from group default)
  role: "control-plane"           # always "control-plane" for compact 3-node cluster

# BMC (iDRAC) — IP is on the out-of-band management network
idrac_ip: "192.168.0.11"
idrac_user: "{{ vault_idrac_user_node1 }}"      # from ansible-vault
idrac_password: "{{ vault_idrac_password_node1 }}"
```

### Finding the MAC address

If you don't know a node's MAC address yet, boot it to the BIOS/iDRAC UI or check the iDRAC inventory:

```bash
# Query iDRAC for NIC MAC via Redfish
curl -sk -u admin:password \
  https://<idrac_ip>/redfish/v1/Systems/System.Embedded.1/EthernetInterfaces \
  | python3 -m json.tool
```

### Node roles

For a standard compact hub cluster all three nodes are `control-plane`. If you add dedicated worker nodes later (not typical for a compact hub), set `role: "worker"` and add them to a `worker_nodes` group.

---

## 7. Configure Secrets

Two separate secret files are required. Neither is committed to git (both are gitignored).

### 7a. Ansible Vault — `ansible/vars/vault_secrets.yml`

Holds credentials needed by Ansible before the cluster exists: BMC passwords, pull secret, SSH key, HTTP server access.

```bash
# Create and encrypt in one step:
ansible-vault create ansible/vars/vault_secrets.yml
```

Use `ansible/vars/vault_secrets.yml.example` as your template. Paste the content, replace all `CHANGEME` values, then save and exit the editor.

```yaml
# Minimum required fields:
vault_pull_secret: '<paste full JSON pull secret from console.redhat.com>'
vault_ssh_public_key: "ssh-rsa AAAA..."

vault_idrac_user_node1: "root"
vault_idrac_password_node1: "your-idrac-password"
vault_idrac_user_node2: "root"
vault_idrac_password_node2: "your-idrac-password"
vault_idrac_user_node3: "root"
vault_idrac_password_node3: "your-idrac-password"

vault_http_server_ip: "192.168.1.5"
vault_http_server_user: "ansiblerunner"
```

To edit later:
```bash
ansible-vault edit ansible/vars/vault_secrets.yml
```

To use a password file instead of interactive prompt:
```bash
echo "your-vault-password" > .vault_pass
chmod 600 .vault_pass
# then use --vault-password-file .vault_pass on playbook runs
```

### 7b. Values Secret — `ansible/values-secret.yaml`

Holds secrets that are pushed into HashiCorp Vault during bootstrap. These become available to GitOps workloads via External Secrets Operator.

```bash
cp ansible/templates/values-secret.yaml.template ansible/values-secret.yaml
# Edit ansible/values-secret.yaml — replace all CHANGEME values
```

Key fields:

```yaml
pull_secret:
  vault_path: "secret/global/pull-secret"
  fields:
    pullSecret: '<full pull secret JSON>'

ssh_keys:
  vault_path: "secret/global/ssh-keys"
  fields:
    publicKey: "ssh-rsa AAAA..."
    privateKey: |
      -----BEGIN OPENSSH PRIVATE KEY-----
      ...
      -----END OPENSSH PRIVATE KEY-----
```

---

## 8. Configure Operational Variables

### `ansible/inventory/group_vars/all/all.yml`

Usually requires no changes. Verify the `openshift_version` and `openshift_install_binary` path match your installation:

```yaml
openshift_version: "4.20"
openshift_install_binary: "/usr/local/bin/openshift-install"
install_base_dir: "/opt/openshift-install"
```

### `ansible/vars/acm_config.yml`

Review and adjust:

```yaml
# ACM channel must align with OCP version (OCP 4.20 → ACM 2.14)
acm_channel: "release-2.14"

# Your fork of this repository
gitops_repo: "https://github.com/<your-org>/openshift-acm-app-of-apps"

# Storage sizes for the Assisted Installer service
agent_service_config:
  db_storage_size: "10Gi"
  filesystem_storage_size: "100Gi"   # increase for many clusters / large images
  image_storage_size: "50Gi"
```

### `components/metallb-configuration/ipaddresspool.yaml`

Update the address range to match your reserved IP pool:

```yaml
spec:
  addresses:
    - 192.168.1.200-192.168.1.220   # change to your reserved range
```

### `clusters/cluster-versions.yaml`

Maps the hub cluster to the git branch ArgoCD should track. The default is `main`:

```yaml
data:
  hub: main   # change to a release branch when promoting (e.g., release-1.0)
```

---

## 9. Run the Installation

### All phases in sequence (recommended for first run)

```bash
cd ansible
source ~/ansible-venv/bin/activate
ansible-playbook playbooks/site.yml --ask-vault-pass
```

Total elapsed time is typically 90–150 minutes depending on hardware and network speed.

### Run phases individually

```bash
# Phase 1a–1c: Generate ISO, stage on HTTP server, mount via iDRAC
ansible-playbook playbooks/bare_metal_prep.yml --ask-vault-pass

# Phase 1d–1e: Power cycle nodes, wait for OCP install-complete (~60–90 min)
ansible-playbook playbooks/bare_metal_install.yml --ask-vault-pass

# Phase 2a: Bootstrap GitOps operator + ArgoCD + root application
ansible-playbook playbooks/acm_hub_bootstrap.yml --ask-vault-pass

# Phase 2b: Wait for ACM, initialize Vault, verify ESO
ansible-playbook playbooks/acm_hub_configure.yml --ask-vault-pass
```

### What each phase does

| Playbook | Duration | Key actions |
|----------|----------|-------------|
| `bare_metal_prep.yml` | 5–10 min | Templates `install-config.yaml` + `agent-config.yaml`, runs `openshift-install agent create image`, syncs ISO to HTTP server, mounts ISO on each node's BMC |
| `bare_metal_install.yml` | 60–90 min | Sets one-time UEFI boot from virtual CD, graceful restart (power-on fallback), polls `openshift-install agent wait-for install-complete` |
| `acm_hub_bootstrap.yml` | 5–10 min | Applies GitOps Subscription, waits for CSV, applies ArgoCD CR with envsubst sidecar, deploys root Application — see [GitOps Architecture](gitops-architecture.md) |
| `acm_hub_configure.yml` | 30–60 min | Waits for MultiClusterHub Running, initializes Vault (unseal + Kubernetes auth + load secrets), verifies ESO ClusterSecretStore Ready |

### `bare_metal_prep.yml` pipeline detail

The critical design point in `bare_metal_prep.yml` is the two-phase ISO boot sequence:
nodes boot the **Live ISO first** to discover hardware facts (MAC addresses, interface
names), and only then is the **Agent-Based Installer ISO generated** — embedding
the correct hardware configuration. This eliminates manual `host_vars` population.

```mermaid
flowchart TD
    Start([bare_metal_prep.yml]) --> A

    subgraph phase1a [" Phase 1a — Live ISO Hardware Discovery "]
        A["Play 1 — localhost<br/>Create DNS SRV record<br/>Start FastAPI registration listener"] --> B
        B["Play 2 — hub_nodes<br/>Redfish pre-discovery<br/>Harvest BMC serial numbers via URI"] --> C
        C["Play 3 — hub_nodes<br/>Mount Live ISO via iDRAC virtual media"] --> D
        D["Play 4 — hub_nodes<br/>Boot from Live ISO<br/>One-time UEFI CD-ROM boot override"] --> E
        E["Play 5 — localhost<br/>Drain registration callbacks<br/>Correlate serial → node.mac + node.interface<br/>Remove DNS SRV record"]
    end

    subgraph phase1b [" Phase 1b — Agent ISO Generation and Install Boot "]
        F["Play 6 — localhost<br/>Generate Agent-Based Installer ISO<br/>embedding discovered MAC + interface facts"] --> G
        G["Play 7 — http_servers<br/>Stage ISO on HTTP staging server"] --> H
        H["Play 8 — hub_nodes<br/>Mount Agent ISO via iDRAC virtual media<br/>Boot into OpenShift installer"]
    end

    E --> F
    H --> Done([Continue: bare_metal_install.yml])
```

---

## 10. Verify the Hub Cluster

After `site.yml` completes, the kubeconfig and kubeadmin password are at:

```
/opt/openshift-install/hub/auth/kubeconfig
/opt/openshift-install/hub/auth/kubeadmin-password
```

```bash
export KUBECONFIG=/opt/openshift-install/hub/auth/kubeconfig

# Cluster operators
oc get clusteroperators

# Hub nodes (should all be Ready)
oc get nodes

# ArgoCD applications
oc get applications -n openshift-gitops

# MultiClusterHub
oc get multiclusterhub -n open-cluster-management

# Vault
oc get pods -n vault

# ESO ClusterSecretStore
oc get clustersecretstore vault-backend
```

### ArgoCD UI

```bash
# Get the ArgoCD route
oc get route openshift-gitops-server -n openshift-gitops -o jsonpath='{.spec.host}'

# Get the admin password
oc get secret openshift-gitops-cluster -n openshift-gitops \
  -o jsonpath='{.data.admin\.password}' | base64 -d
```

---

## 11. Troubleshooting

### Agent ISO not booting

- Confirm the ISO is reachable: `curl -I http://<http_server_ip>/ocp/hub/agent.x86_64.iso`
- Check iDRAC virtual media status in the iDRAC UI: **Configuration → Virtual Media**
- Verify the boot order override was applied: check **Configuration → BIOS Settings → Boot Settings**

### `openshift-install agent wait-for install-complete` times out

- SSH to the rendezvous node (the node with `rendezvous_ip`) once it is up:
  ```bash
  ssh -i <your_private_key> core@<rendezvous_ip>
  sudo journalctl -u assisted-service -f
  ```
- Common causes: DNS not resolving `api.<cluster>.<domain>`, certificate issues, NTP drift between nodes

### ArgoCD applications stuck in `Unknown` or `OutOfSync`

```bash
# Check ArgoCD application events
oc describe application <name> -n openshift-gitops

# Force a refresh
oc -n openshift-gitops patch application <name> \
  --type merge -p '{"operation":{"sync":{}}}'
```

### Vault not initializing

- Confirm Vault pods are Running: `oc get pods -n vault`
- Check the Ansible task output — the initialization task logs the Vault status and any errors
- Verify the `values-secret.yaml` exists and is fully populated:
  ```bash
  ls -la ansible/values-secret.yaml
  ```

### ESO ClusterSecretStore remains `NotReady`

ESO cannot connect to Vault until Vault is initialized and unsealed. The `acm_hub_configure.yml` playbook handles this sequencing. If the store stays NotReady after the playbook completes:

```bash
oc describe clustersecretstore vault-backend
# Look for connection errors — usually a Vault address or auth mount mismatch
```
