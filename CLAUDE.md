# OpenShift ACM App of Apps

## Project Overview

Templateable OpenShift ACM Hub compact cluster installation on three baremetal nodes, with the ability to template deployment of additional managed child clusters. Scales the "app of apps" pattern across multiple OpenShift clusters via ACM.

### Architecture Phases

- **Phase 1 (Ansible-driven):** Bare metal preparation → Agent-Based Installer ISO generation → ISO staging → BMC-controlled boot → OpenShift cluster install → ArgoCD bootstrap → ACM Hub deployment
- **Phase 2 (GitOps-driven):** ACM Hub provisions and manages child clusters via ArgoCD app-of-apps cascade

### GitOps Deployment Model (Pending Decision)

The project should be structured to accommodate either model:

- **Centralized (Push):** Single Argo CD on ACM Hub, uses ACM Placement API + ApplicationSets to push workloads to managed clusters
- **Decentralized (Pull):** Argo CD instance on every managed child cluster; ACM bootstraps GitOps engine and initial parent app, child pulls from Git independently

### Source Lineage

This project synthesizes patterns from two repositories:

1. **heatmiser/openshift-virtualization-gitops** (acm-baremetal branch) — ACM hub install automation via Agent-Based Installer, app-of-apps GitOps pattern, Kustomize components, sync-wave ordering
2. **parmstro/rhis-builder-kvm-lz** — ISO staging workflow mechanics, BMC/Redfish virtual media and power control patterns, wait-for-availability approach, variable layering, FQCN discipline

---

## Ansible Standards

Follow [Red Hat COP Automation Good Practices](https://redhat-cop.github.io/automation-good-practices/).

### Module Usage

- **Always use FQCN** — `ansible.builtin.template`, `kubernetes.core.k8s`, `community.general.redfish_command`, never bare module names
- Prefer `ansible.builtin.*` prefix over short names in all cases

### Variables

- **Always use `vars_files`** over inline `vars:` blocks in playbooks
- Use structured variable hierarchy: `group_vars/all/`, `group_vars/{group}.yml`, `host_vars/{host}.yml`, `vars/{purpose}.yml`
- Prefix role variables with role name: `rolename_variable`
- Use `snake_case` for all variable, file, and directory names
- Never embed credentials in plaintext — use Ansible Vault or reference vault variables

### Playbook Organization

- Name all tasks in imperative form (e.g., "Ensure ACM operator subscription exists")
- Keep playbooks simple — delegate to task includes or roles
- Use `ansible.builtin.include_tasks` for dynamic inclusion
- Use section comment headers for readability in task files (e.g., `# === ISO STAGING ===`)
- Use `.yml` extension, not `.yaml`

### YAML Style

- 2-space indentation
- YAML native syntax for task arguments, not `key=value`
- Double quotes for YAML strings, single quotes for Jinja2 expressions within YAML
- Add single spaces around Jinja2 markers: `{{ variable_name }}`
- Use `>-` for line folding (avoids trailing newlines)
- Comments in YAML are OK — explain the why, not the what

### Idempotency and Safety

- Use `creates:` parameter on command tasks
- Use `changed_when:` / `failed_when:` appropriately on shell/command tasks
- Use `until/retries/delay` for polling operator readiness
- Guard destructive operations with `stat` or existence checks
- Use `backup: true` for file modifications where appropriate

### Linting and Validation

- All code must pass `ansible-lint` before commit
- Run via: `source /home/claude/workspace/ansible2.16.17/bin/activate && ansible-lint`
- Default line length: 82 characters

### Collections and Dependencies

- Declare all collection dependencies in `requirements.yml`
- Declare Python dependencies in `requirements.txt`
- Key collections: `kubernetes.core`, `community.general`, `ansible.posix`, `dellemc.openmanage` (or `community.general` for generic Redfish)

---

## GitOps Standards

Follow [OpenShift GitOps Recommended Practices](https://developers.redhat.com/blog/2025/03/05/openshift-gitops-recommended-practices#).

### ArgoCD App of Apps Pattern

- Root Application points at `clusters/${cluster_name}`
- Helm chart generates ArgoCD Application and AppProject resources from values
- Values hierarchy: `groups/all` (shared base) → `clusters/{name}` (cluster-specific)

### Sync Wave Ordering

| Wave | Purpose | Examples |
|------|---------|---------|
| 5 | Operator subscriptions | acm-operator, metallb-operator, cert-manager-operator |
| 6 | Operator configuration | metallb-config, nmstate-config |
| 15 | Operator instances / CRs | acm-instance (MultiClusterHub), gitops-bootstrap-policy |
| 25 | Complex / dependent configs | acm-configuration, acm-observability, managed clusters |

### Kustomize Components

- Self-contained components in `components/` directory
- Each component has its own `kustomization.yaml` and manifests
- Cluster-specific customization in `clusters/{name}/overlays/`
- Max 2-3 overlay nesting levels

### ArgoCD Configuration

- Use annotation tracking (not label tracking) — labels are limited to 63 chars
- Create custom AppProjects — never rely on the default AppProject
- Define tenant RBAC within individual AppProjects
- Implement custom health checks for CRDs not covered by built-in checks
- Enable automated sync with prune and self-heal on root application
- Deploy versioned manifests, never from HEAD

### Environment Variable Substitution

ArgoCD uses an envsubst sidecar plugin for runtime variable injection:
- `${CLUSTER_NAME}` — cluster name
- `${CLUSTER_BASE_DOMAIN}` — cluster base domain
- `${PLATFORM_BASE_DOMAIN}` — platform base domain
- `${INFRA_GITOPS_REPO}` — GitOps repository URL

### Secrets

- Never store secrets in Git — `values-secret.yaml` and `*.kubeconfig` are gitignored
- **Ansible-side** (pre-cluster): BMC credentials use `ansible-vault` in `host_vars/`
- **GitOps-side** (post-cluster): External Secrets Operator + HashiCorp Vault (KV v2)
  - Vault runs on the hub cluster (external to managed/spoke clusters), deployed via Helm
  - `ClusterSecretStore` named `vault-backend`, Kubernetes auth method
  - Path convention: `secret/global/`, `secret/hub/`, `secret/{spoke-fqdn}/`
  - `ExternalSecret` CRs use `dataFrom.extract` for bulk KV fetch
  - Spoke clusters receive secrets via ACM Policy propagation (not per-spoke ESO)
- Bootstrap trust anchor: populate `ansible/templates/values-secret.yaml.template` → copy to `values-secret.yaml` → Ansible vault_init playbook pushes to Vault

---

## Bare Metal Deployment Patterns

### Overview

The bare metal workflow uses the OpenShift Agent-Based Installer to produce a self-contained ISO (embedding install-config and agent-config), then applies the operational staging, virtual media, and power control patterns proven in rhis-builder-kvm-lz to boot and install the cluster.

### Phase 1a: Agent-Based Installer ISO Generation

1. Template `install-config.yaml` and `agent-config.yaml` from Jinja2 templates using per-cluster and per-host variables
2. Run `openshift-install agent create image` to generate the agent ISO
3. The resulting ISO is self-contained — no separate kickstart or OEMDRV image is needed

### Phase 1b: ISO Staging on HTTP Server

Adapted from rhis-builder-kvm-lz patterns:

1. Create HTTP docroot directory structure for serving the agent ISO
2. Transfer the agent ISO to the HTTP server (via `ansible.posix.synchronize` or `ansible.builtin.copy`)
3. Optionally stage ISO in tmpfs (`/dev/shm`) for performance, symlinked from docroot
4. Set SELinux file contexts (`httpd_sys_content_t`) and run `restorecon`

### Phase 1c: BMC Virtual Media Mount

Mount the agent ISO as virtual media on each node's BMC:

- Mount agent ISO as virtual DVD via BMC/Redfish (single media mount — no OEMDRV needed)
- Use `force: true` to eject any previously mounted media
- Use `delegate_to: localhost` for all BMC communication
- Support both Dell iDRAC (`dellemc.openmanage.idrac_virtual_media`) and generic Redfish (`community.general.redfish_command` with `VirtualMediaInsert`)

### Phase 1d: Power Control and Boot

Adapted from rhis-builder-kvm-lz two-step pattern:

1. **Set boot override:** One-time UEFI boot from virtual CD-ROM (`boot_source_override_enabled: once`) so subsequent reboots fall back to normal boot order
2. **Graceful restart:** Attempt `GracefulRestart`; register result with `ignore_errors: true`
3. **Power-on fallback:** If server was already powered off, send `On` command instead

### Phase 1e: Wait for Installation

Two-stage wait:

1. **Agent-Based Installer completion:** Poll `openshift-install agent wait-for install-complete` using `until/retries/delay` (e.g., 120 retries × 60s = up to 2 hours)
2. **API availability:** Verify the cluster API is reachable before proceeding to bootstrap

### Phase 2: GitOps Bootstrap

After the OpenShift cluster is installed:

1. Deploy OpenShift GitOps operator (Subscription)
2. Configure ArgoCD instance with envsubst sidecar plugin
3. Deploy root application pointing at `clusters/${cluster_name}` — triggers app-of-apps cascade
4. ArgoCD handles all subsequent operator and configuration deployment via sync waves

---

## Project Directory Structure (Target)

```
openshift-acm-app-of-apps/
├── CLAUDE.md
├── .gitignore
├── .ansible-lint
├── ansible/
│   ├── ansible.cfg
│   ├── requirements.yml                    # Ansible collection dependencies
│   ├── requirements.txt                    # Python dependencies
│   ├── inventory/
│   │   ├── hosts.yml                       # Groups: local, hub_nodes, http_servers
│   │   ├── group_vars/
│   │   │   ├── all/
│   │   │   │   └── all.yml                 # ISO paths, HTTP config, install dirs
│   │   │   ├── hub_nodes.yml               # Cluster identity, network, node defaults
│   │   │   └── http_servers.yml            # HTTP staging server config
│   │   └── host_vars/
│   │       ├── hub-node1.yml               # Per-node: hostname, MAC, IPs, BMC (vault ref)
│   │       ├── hub-node2.yml
│   │       └── hub-node3.yml
│   ├── vars/
│   │   ├── acm_config.yml                  # ACM, MCE, GitOps, Vault, ESO config vars
│   │   ├── vault_secrets.yml               # ansible-vault encrypted (safe to commit)
│   │   └── vault_secrets.yml.example       # Plaintext structure reference
│   ├── playbooks/
│   │   ├── site.yml                        # Master orchestration playbook
│   │   ├── bare_metal_prep.yml             # ISO generation + HTTP staging + virtual media
│   │   ├── bare_metal_install.yml          # Power cycle + wait for install-complete
│   │   ├── acm_hub_bootstrap.yml           # GitOps operator + ArgoCD + root app
│   │   └── acm_hub_configure.yml           # ACM/MCE + Vault init + ESO + post-install
│   ├── tasks/
│   │   ├── generate_agent_iso.yml          # Template install-config + agent-config, run installer
│   │   ├── iso_staging.yml                 # Transfer ISO to HTTP server, SELinux contexts
│   │   ├── bmc_virtual_media.yml           # Mount agent ISO via iDRAC virtual media
│   │   ├── bmc_power_control.yml           # Boot override + graceful restart/power-on fallback
│   │   ├── wait_for_install.yml            # Poll openshift-install agent wait-for install-complete
│   │   ├── gitops_bootstrap.yml            # GitOps operator + ArgoCD instance + root application
│   │   └── vault_init.yml                  # Vault init/unseal + Kubernetes auth + load secrets
│   └── templates/
│       ├── install-config.yaml.j2          # Agent-based installer cluster config
│       ├── agent-config.yaml.j2            # Per-node BMC + network config for agent ISO
│       └── values-secret.yaml.template     # Local secrets template (never committed)
├── .bootstrap/                             # Applied by acm_hub_bootstrap.yml
│   ├── subscription.yaml                   # OpenShift GitOps operator subscription
│   ├── cluster-rolebinding.yaml            # ArgoCD cluster-admin binding
│   ├── setenv-plugin-configmap.yaml        # envsubst CMP plugin configuration
│   ├── argocd.yaml                         # ArgoCD instance CR
│   └── root-application.yaml              # Root ArgoCD Application → clusters/${CLUSTER_NAME}
├── .helm-charts/
│   └── argocd-app-of-app/                  # Helm chart: generates Applications from values
├── clusters/
│   ├── hub/
│   │   ├── kustomization.yaml              # HelmChartInflationGenerator + targetRevision replacement
│   │   └── values.yaml                     # Hub-specific ArgoCD applications
│   └── cluster-versions.yaml              # ConfigMap: cluster name → git branch
├── components/                             # Self-contained Kustomize components (sync-wave ordered)
│   ├── acm-operator/                       # Wave 5: ACM subscription + OperatorGroup
│   ├── acm-instance/                       # Wave 15: MultiClusterHub CR
│   ├── acm-configuration/                  # Wave 25: AgentServiceConfig, ClusterImageSet, Hive
│   ├── acm-observability/                  # Wave 25: ACM observability stack
│   ├── gitops-bootstrap-policy/            # Wave 15: ACM policy to propagate GitOps to spokes
│   ├── vault/                              # Wave 5: Vault Helm release (hub-local)
│   ├── eso/                               # Wave 6: ESO Helm release + ClusterSecretStore
│   ├── metallb-operator/                   # Wave 5
│   ├── metallb-configuration/              # Wave 6
│   ├── nmstate-operator/                   # Wave 5
│   ├── nmstate-configuration/              # Wave 6
│   └── cert-manager-operator/              # Wave 5
└── groups/
    └── all/
        └── values.yaml                     # Shared base ArgoCD applications (all clusters)
```

---

## Development Environment

- Claude Code runs in a podman container
- Ansible venv: `source /home/claude/workspace/ansible2.16.17/bin/activate`
- Working directory is bind-mounted at the host path

## Pre-Commit Checklist

### Ansible
- [ ] All modules use FQCN (`ansible.builtin.*`, `kubernetes.core.*`, etc.)
- [ ] Variables in `vars_files`, not inline `vars:`
- [ ] No plaintext credentials
- [ ] `ansible-lint` passes clean
- [ ] Tasks named in imperative form
- [ ] `changed_when`/`failed_when` on command/shell tasks

### GitOps
- [ ] `kustomize build` succeeds for all components
- [ ] Sync wave annotations present and correctly ordered
- [ ] Custom health checks for non-standard CRDs
- [ ] Environment variable syntax correct (`${VAR_NAME}`)
- [ ] No secrets in Git
