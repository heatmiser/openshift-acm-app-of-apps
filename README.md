# OpenShift ACM App of Apps

Automated deployment of a compact, three-node OpenShift Hub cluster on bare metal, with GitOps-driven provisioning of additional managed child clusters via Red Hat Advanced Cluster Management (ACM). The project scales the ArgoCD "app of apps" pattern across multiple OpenShift clusters.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  Phase 1 — Ansible-driven Hub Installation                      │
│                                                                 │
│  Ansible Control Node                                           │
│       │                                                         │
│       ├─ Generate Agent-Based Installer ISO                     │
│       ├─ Stage ISO on HTTP server                               │
│       ├─ Mount ISO via iDRAC virtual media (BMC/Redfish)        │
│       ├─ Power cycle nodes → OpenShift installs from ISO        │
│       ├─ Bootstrap OpenShift GitOps (ArgoCD)                    │
│       ├─ Initialize HashiCorp Vault                             │
│       └─ Configure External Secrets Operator                    │
│                                                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ ArgoCD app-of-apps cascade
┌──────────────────────────▼──────────────────────────────────────┐
│  Phase 2 — GitOps-driven Operator & Child Cluster Management    │
│                                                                 │
│  ACM Hub (ArgoCD)                                               │
│       │                                                         │
│       ├─ Wave  5: Operators    (ACM, Vault, MetalLB, NMState,   │
│       │                         cert-manager)                   │
│       ├─ Wave  6: Config       (ESO + Vault store, MetalLB IP   │
│       │                         pool, NMState handler)          │
│       ├─ Wave 15: Instances    (MultiClusterHub, GitOps          │
│       │                         bootstrap policy)               │
│       └─ Wave 25: Dependent   (ACM configuration, observability │
│                                child cluster provisioning)      │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Agent-Based Installer** — self-contained ISO embeds `install-config.yaml` and `agent-config.yaml`; no kickstart, no DHCP boot server required
- **BMC/Redfish** — ISO mounted as virtual DVD via iDRAC; one-time UEFI boot override, graceful restart with power-on fallback
- **Secrets — two layers**: Ansible Vault for pre-cluster BMC/staging credentials; HashiCorp Vault + External Secrets Operator for all post-cluster GitOps secrets
- **App of apps** — single ArgoCD root Application points at `clusters/hub`; Helm chart generates all child Applications from merged values files
- **Branch-pinned deployments** — `clusters/cluster-versions.yaml` maps each cluster name to a git branch; Kustomize replacement stamps `targetRevision` on every generated Application at build time

---

## Prerequisites

### Control Node

| Tool | Minimum version | Notes |
|------|----------------|-------|
| Python | 3.10+ | |
| Ansible | 2.16+ | via venv recommended |
| `openshift-install` | 4.21 | [mirror.openshift.com](https://mirror.openshift.com/pub/openshift-v4/clients/ocp/) |
| `oc` / `kubectl` | 4.21 | |
| `kustomize` | 5.x | for local validation |
| `helm` | 3.x | for local validation |

### Ansible Collections

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml
pip install -r requirements.txt
```

See `ansible/requirements.yml` for the full list (`kubernetes.core`, `community.general`, `ansible.posix`, `dellemc.openmanage`, `community.crypto`).

### Infrastructure

- **3 bare metal nodes** (control plane) — Dell iDRAC or compatible Redfish BMC
- **1 HTTP server** — serves the agent ISO via plain HTTP (can be the control node)
- **DNS** — `api.<cluster_name>.<base_domain>` and `*.apps.<cluster_name>.<base_domain>` must resolve to the hub VIP or node IPs
- **Network** — nodes on a routable L2 segment; MetalLB requires a reserved IP range for LoadBalancer services
- **Red Hat account** — pull secret from [console.redhat.com](https://console.redhat.com/openshift/downloads)

---

## Quick Start

1. **Fork and clone** this repository, then set `gitops_repo` in `ansible/vars/acm_config.yml` to your fork URL.

2. **Configure inventory** — edit cluster identity and node details:
   - `ansible/inventory/group_vars/hub_nodes.yml` — cluster name, base domain, network CIDRs
   - `ansible/inventory/host_vars/hub-node{1,2,3}.yml` — per-node IP, MAC, interface, iDRAC IP

3. **Create secrets** — two files, neither committed to git:

   ```bash
   # Ansible-side credentials (BMC, pull secret, SSH key)
   ansible-vault create ansible/vars/vault_secrets.yml
   # use vault_secrets.yml.example as your template

   # GitOps-side secrets pushed to Vault at bootstrap
   cp ansible/templates/values-secret.yaml.template ansible/values-secret.yaml
   # populate all CHANGEME fields
   ```

4. **Install the hub cluster**:

   ```bash
   cd ansible
   ansible-playbook playbooks/site.yml --ask-vault-pass
   ```

   Or run phases individually — see [Hub Installation Guide](docs/hub-installation.md).

5. **Add managed child clusters** — see [Child Cluster Onboarding](docs/child-cluster-onboarding.md).

---

## Repository Layout

```
openshift-acm-app-of-apps/
│
├── ansible/                        # Phase 1: bare metal → hub cluster
│   ├── ansible.cfg
│   ├── requirements.yml            # Ansible collection dependencies
│   ├── requirements.txt            # Python dependencies
│   ├── inventory/
│   │   ├── hosts.yml               # Groups: local, hub_nodes, http_servers
│   │   ├── group_vars/
│   │   │   ├── all/all.yml         # ISO paths, HTTP config, install dirs
│   │   │   ├── hub_nodes.yml       # Cluster identity, network CIDRs, node defaults
│   │   │   └── http_servers.yml    # HTTP staging server config
│   │   └── host_vars/
│   │       ├── hub-node1.yml       # Per-node: hostname, IP, MAC, interface, iDRAC
│   │       ├── hub-node2.yml
│   │       └── hub-node3.yml
│   ├── vars/
│   │   ├── acm_config.yml          # ACM, GitOps, Vault, ESO config variables
│   │   ├── vault_secrets.yml       # ansible-vault encrypted (NEVER plaintext)
│   │   └── vault_secrets.yml.example
│   ├── playbooks/
│   │   ├── site.yml                # Master orchestration — runs all phases
│   │   ├── bare_metal_prep.yml     # ISO generation + staging + virtual media
│   │   ├── bare_metal_install.yml  # Power cycle + wait for install-complete
│   │   ├── acm_hub_bootstrap.yml   # GitOps operator + ArgoCD + root application
│   │   └── acm_hub_configure.yml   # ACM wait + Vault init + ESO verify
│   ├── tasks/                      # Reusable task files included by playbooks
│   └── templates/                  # Jinja2: install-config, agent-config, secrets
│
├── .bootstrap/                     # Applied by acm_hub_bootstrap.yml
│   ├── subscription.yaml           # OpenShift GitOps operator subscription
│   ├── cluster-rolebinding.yaml    # ArgoCD cluster-admin binding
│   ├── setenv-plugin-configmap.yaml # envsubst CMP plugin configuration
│   ├── argocd.yaml                 # ArgoCD instance CR
│   └── root-application.yaml       # Root Application → clusters/hub
│
├── .helm-charts/
│   └── argocd-app-of-app/          # Helm chart: generates Applications from values
│
├── clusters/
│   ├── cluster-versions.yaml       # ConfigMap: cluster name → git branch
│   └── hub/
│       ├── kustomization.yaml      # HelmChartInflationGenerator + replacements
│       └── values.yaml             # Hub-specific ArgoCD applications (waves 5–25)
│
├── components/                     # Self-contained Kustomize components
│   ├── acm-operator/               # Wave 5
│   ├── vault/                      # Wave 5 (helmCharts: HashiCorp Vault)
│   ├── metallb-operator/           # Wave 5
│   ├── nmstate-operator/           # Wave 5
│   ├── cert-manager-operator/      # Wave 5
│   ├── eso/                        # Wave 6 (helmCharts: ESO + ClusterSecretStore)
│   ├── metallb-configuration/      # Wave 6
│   ├── nmstate-configuration/      # Wave 6
│   ├── acm-instance/               # Wave 15 (MultiClusterHub)
│   ├── gitops-bootstrap-policy/    # Wave 15 (ACM policy → GitOps on spokes)
│   ├── acm-configuration/          # Wave 25 (AgentServiceConfig, ClusterImageSet)
│   └── acm-observability/          # Wave 25 (Thanos + Grafana)
│
└── groups/
    └── all/
        └── values.yaml             # Shared AppProject + wave-5 operators (all clusters)
```

---

## Documentation

| Document | Contents |
|----------|----------|
| [Hub Installation Guide](docs/hub-installation.md) | Full walkthrough: hardware, network, variables, playbook execution, troubleshooting |
| [Child Cluster Onboarding](docs/child-cluster-onboarding.md) | Adding ACM-managed bare metal spoke clusters |
| [Variables Reference](docs/variables-reference.md) | All configurable variables, defaults, and descriptions |

---

## Operator Version Matrix

| Operator | Channel | OCP Version |
|----------|---------|-------------|
| ACM | `release-2.15` | 4.21 |
| MCE | `stable-2.9` | 4.21 |
| OpenShift GitOps | `latest` | 4.21 |
| cert-manager | `stable-v1` | 4.21 |
| MetalLB | `stable` | 4.21 |
| NMState | `stable` | 4.21 |
| Vault (Helm) | `0.29.1` | — |
| ESO (Helm) | `0.14.4` | — |

To verify current channels for your OCP version:
```bash
oc get packagemanifest <name> -o jsonpath='{.status.defaultChannel}'
```
