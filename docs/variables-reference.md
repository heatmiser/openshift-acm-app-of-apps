# Variables Reference

All configurable variables across the project, organized by file. Required variables have no default and must be set. Optional variables show their default value.

---

## Table of Contents

1. [Cluster Identity — `group_vars/hub_nodes.yml`](#1-cluster-identity--group_varshub_nodesyml)
2. [Per-Node Details — `host_vars/hub-nodeN.yml`](#2-per-node-details--host_varshub-nodenyml)
3. [Global Ansible Settings — `group_vars/all/all.yml`](#3-global-ansible-settings--group_varsallallyml)
4. [HTTP Staging Server — `group_vars/http_servers.yml`](#4-http-staging-server--group_varshttp_serversyml)
5. [Operational Config — `vars/acm_config.yml`](#5-operational-config--varsacm_configyml)
   - [Live ISO Hardware Discovery](#live-iso-hardware-discovery)
   - [DNS SRV Controller Discovery](#dns-srv-controller-discovery)
6. [Ansible-Vault Secrets — `vars/vault_secrets.yml`](#6-ansible-vault-secrets--varsvault_secretsyml)
7. [GitOps Vault Secrets — `values-secret.yaml`](#7-gitops-vault-secrets--values-secretyaml)
8. [GitOps Values — `groups/all/values.yaml`](#8-gitops-values--groupsallvaluesyaml)
9. [Hub Applications — `clusters/hub/values.yaml`](#9-hub-applications--clustershubvaluesyaml)
10. [Cluster Branch Pinning — `clusters/cluster-versions.yaml`](#10-cluster-branch-pinning--clusterscluster-versionsyaml)
11. [Sync Wave Reference](#11-sync-wave-reference)

---

## 1. Cluster Identity — `group_vars/hub_nodes.yml`

Applied to all hosts in the `hub_nodes` inventory group.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `cluster_name` | Yes | — | Short cluster name. Becomes part of the FQDN: `<cluster_name>.<base_domain>`. Use lowercase, alphanumeric, hyphens only. |
| `base_domain` | Yes | — | DNS base domain. The installer creates `api.<cluster_name>.<base_domain>` and `*.apps.<cluster_name>.<base_domain>`. |
| `rendezvous_ip` | Yes | — | IP address of one hub node (typically node 1) used by the Agent-Based Installer as the bootstrap coordination point. Must match one of the node `ipv4_address` values. |
| `machine_network_cidr` | Yes | — | CIDR of the physical network the nodes are on (e.g., `192.168.1.0/24`). Used by the installer to identify node interfaces. |
| `cluster_network_cidr` | No | `10.128.0.0/14` | Pod CIDR. Internal to the cluster. Must not overlap with machine network or other clusters. |
| `cluster_network_host_prefix` | No | `23` | Subnet size allocated per node from the cluster network. `/23` gives 512 pod IPs per node. |
| `service_network_cidr` | No | `172.30.0.0/16` | ClusterIP service CIDR. Internal to the cluster. Must not overlap with machine network or other clusters. |
| `network_type` | No | `OVNKubernetes` | CNI plugin. `OVNKubernetes` is required for bare metal with MetalLB. |
| `platform_type` | No | `none` | Platform integration. `none` means no cloud provider. Do not change for bare metal. |
| `node_role` | No | `control-plane` | Default role applied to all nodes in the group. For a compact 3-node cluster this is always `control-plane`. Override per-node in `host_vars`. |
| `node_interface` | No | `eno1` | Default NIC name for all nodes. Override per-node in `host_vars` if hardware differs. |
| `ansible_user` | No | `ansiblerunner` | SSH user for post-install Ansible access to nodes. |
| `become` | No | `true` | Whether Ansible uses privilege escalation on nodes. |

---

## 2. Per-Node Details — `host_vars/hub-nodeN.yml`

One file per node. The `node:` dict keys are used in both the `agent-config.yaml.j2` template (ISO generation) and the `bmc_virtual_media.yml` / `bmc_power_control.yml` tasks.

### `node:` dict

| Key | Required | Description |
|-----|----------|-------------|
| `node.hostname` | Yes | Short hostname without domain (e.g., `hub-node1`). The installer creates `<hostname>.<base_domain>`. |
| `node.domain` | No | Defaults to `{{ base_domain }}`. Override if this node is in a different zone. |
| `node.ipv4_address` | Yes | Static IPv4 address. Must be in `machine_network_cidr`. |
| `node.ipv4_prefix` | Yes | Network prefix length (e.g., `24` for /24). Used directly in NMState config — no netmask conversion needed. |
| `node.ipv4_gateway` | Yes | Default gateway for this node. |
| `node.ipv4_dns` | Yes | DNS resolver. Can be the same as the gateway. |
| `node.mac` | Yes | MAC address of the primary NIC. The Agent-Based Installer uses this to match the NMState config to the physical NIC. |
| `node.interface` | No | NIC name (e.g., `eno1`, `eth0`, `bond0`). Defaults to `node_interface` from group_vars. |
| `node.role` | No | `control-plane` or `worker`. Defaults to `control-plane` for compact clusters. |

### BMC variables

| Variable | Required | Description |
|----------|----------|-------------|
| `idrac_ip` | Yes | IP address of the iDRAC/BMC out-of-band management interface. |
| `idrac_user` | Yes | BMC username. Reference a vault variable: `{{ vault_idrac_user_nodeN }}`. |
| `idrac_password` | Yes | BMC password. Reference a vault variable: `{{ vault_idrac_password_nodeN }}`. |

### Example: hub-node2.yml

```yaml
node:
  hostname: "hub-node2"
  domain: "{{ base_domain }}"
  ipv4_address: "192.168.1.11"
  ipv4_prefix: 24
  ipv4_gateway: "192.168.1.1"
  ipv4_dns: "192.168.1.1"
  mac: "aa:bb:cc:dd:ee:02"
  interface: "eno1"
  role: "control-plane"

idrac_ip: "192.168.0.12"
idrac_user: "{{ vault_idrac_user_node2 }}"
idrac_password: "{{ vault_idrac_password_node2 }}"
```

---

## 3. Global Ansible Settings — `group_vars/all/all.yml`

Applied to all hosts regardless of group.

| Variable | Default | Description |
|----------|---------|-------------|
| `openshift_version` | `4.21` | OCP version string. Must match the `openshift-install` binary version and the `ClusterImageSet`. |
| `openshift_install_binary` | `/usr/local/bin/openshift-install` | Full path to the `openshift-install` binary on the control node. |
| `install_base_dir` | `/opt/openshift-install` | Parent directory for cluster install artifacts. Each cluster gets a subdirectory: `{{ install_base_dir }}/{{ cluster_name }}`. |
| `install_dir` | `{{ install_base_dir }}/{{ cluster_name }}` | Derived. Do not override. |
| `agent_iso_filename` | `agent.x86_64.iso` | Fixed by the Agent-Based Installer — do not change. |
| `agent_iso_local_path` | `{{ install_dir }}/{{ agent_iso_filename }}` | Derived. |
| `remote_http_docroot` | `/var/www/html/ocp` | Root of the HTTP document directory on the staging server. |
| `remote_http_iso_dir` | `{{ remote_http_docroot }}/{{ cluster_name }}` | Derived subdirectory per cluster. |

### Derived URL variables

These are built from the above and from `group_vars/http_servers.yml`. Do not set them manually.

| Variable | Derived from |
|----------|-------------|
| `http_server_base_url` | `http://{{ vault_http_server_ip }}` |
| `agent_iso_url` | `{{ http_server_base_url }}/{{ cluster_name }}/{{ agent_iso_filename }}` |

---

## 4. HTTP Staging Server — `group_vars/http_servers.yml`

| Variable | Source | Description |
|----------|--------|-------------|
| `ansible_host` | `{{ vault_http_server_ip }}` | IP address of the HTTP server. Resolved from vault secret at runtime. |
| `ansible_user` | `{{ vault_http_server_user }}` | SSH user for the HTTP server. Resolved from vault secret at runtime. |

The actual IP and user are set in `vault_secrets.yml` (see Section 6) — not here.

---

## 5. Operational Config — `vars/acm_config.yml`

Loaded explicitly via `vars_files:` in playbooks that need it.

### ACM Operator

| Variable | Default | Description |
|----------|---------|-------------|
| `acm_namespace` | `open-cluster-management` | Namespace for ACM operator and MultiClusterHub. |
| `acm_channel` | `release-2.15` | Subscription channel. Must align with OCP version. OCP 4.21 → ACM 2.15. Verify: `oc get packagemanifest advanced-cluster-management -o jsonpath='{.status.defaultChannel}'` |
| `acm_install_plan_approval` | `Automatic` | `Automatic` or `Manual`. |

### MultiClusterHub

| Variable | Default | Description |
|----------|---------|-------------|
| `mch_name` | `multiclusterhub` | Name of the MultiClusterHub CR. |
| `mch_wait_retries` | `30` | Retries when polling MCH for `Running` status. |
| `mch_wait_delay` | `60` | Seconds between retries. Total max wait: `mch_wait_retries × mch_wait_delay` = 30 min. |

### AgentServiceConfig

| Variable | Default | Description |
|----------|---------|-------------|
| `agent_service_config.db_storage_size` | `10Gi` | Storage for the Assisted Installer PostgreSQL database. |
| `agent_service_config.filesystem_storage_size` | `20Gi` | Storage for agent ISOs and artifacts. Increase for many clusters. |
| `agent_service_config.image_storage_size` | `20Gi` | Storage for cached RHCOS images. |

### MultiClusterEngine

| Variable | Default | Description |
|----------|---------|-------------|
| `mce_name` | `multiclusterengine` | Name of the MCE CR (created automatically by ACM). |
| `mce_wait_retries` | `30` | Retries when polling MCE. |
| `mce_wait_delay` | `30` | Seconds between retries. |

### OpenShift GitOps

| Variable | Default | Description |
|----------|---------|-------------|
| `gitops_namespace` | `openshift-gitops` | Namespace where the ArgoCD instance runs. |
| `gitops_channel` | `latest` | Subscription channel for the GitOps operator. |
| `gitops_install_plan_approval` | `Automatic` | `Automatic` or `Manual`. |

### GitOps Repository

| Variable | Required | Description |
|----------|----------|-------------|
| `gitops_repo` | Yes | URL of **your fork** of this repository. ArgoCD root Application and all generated Applications use this as `repoURL`. Must be reachable from the hub cluster. |
| `gitops_revision` | No | Git revision for the root Application. Defaults to `main`. The per-cluster revision is controlled by `cluster-versions.yaml`. |

### Vault

| Variable | Default | Description |
|----------|---------|-------------|
| `vault_namespace` | `vault` | Namespace where HashiCorp Vault is deployed. |
| `vault_kv_mount` | `secret` | Vault KV v2 mount path. |
| `vault_hub_auth_mount` | `hub` | Vault Kubernetes auth method mount path for the hub cluster. |
| `vault_hub_role` | `hub-role` | Vault auth role that ESO uses to authenticate. |

### External Secrets Operator

| Variable | Default | Description |
|----------|---------|-------------|
| `eso_namespace` | `external-secrets` | Namespace where ESO runs. |
| `eso_service_account` | `external-secrets` | ESO controller service account name. |
| `eso_secret_store_name` | `vault-backend` | Name of the ClusterSecretStore pointing at Vault. |

### Live ISO Hardware Discovery

| Variable | Default | Description |
|----------|---------|-------------|
| `cluster_onboard_live_iso_url` | `""` | **Required.** URL of the CentOS Stream Live ISO served from the HTTP staging server. Set before running `bare_metal_prep.yml` or `cluster_onboard.yml`. Example: `http://192.168.1.10/ocp/live-discovery.iso`. See [Live ISO Integration](live-iso-integration.md) for build instructions. |

### DNS SRV Controller Discovery

| Variable | Default | Description |
|----------|---------|-------------|
| `cluster_onboard_dns_srv_mode` | `automated` | `automated` — pipeline creates and removes the SRV record via `nsupdate` against a BIND Podman Quadlet on the controller. `manual` — DNS ops team pre-creates the record; pipeline validates it resolves before booting nodes. |
| `cluster_onboard_dns_srv_domain` | `""` | **Required.** DNS domain under which the SRV record is published. Must match `ACM_DNS_DOMAIN` in the Live ISO `live-image.conf`. Example: `mgmt.example.com`. Record format: `_acm-listener._tcp.<domain> IN SRV 0 0 <port> <controller-fqdn>.` |
| `cluster_onboard_mdns_service_name` | `_acm-listener._tcp` | SRV service name. Must match `ACM_LISTENER_SERVICE` in the Live ISO `live-image.conf`. |
| `cluster_onboard_dns_bind_server` | `127.0.0.1` | IP address of the BIND server for automated mode. Default targets the Podman Quadlet running on the controller's loopback interface. |
| `cluster_onboard_dns_bind_port` | `53` | BIND server port for automated mode. |
| `cluster_onboard_dns_tsig_key_name` | `acm-update-key` | TSIG key name for RFC 2136 dynamic updates (automated mode). Must match the key name configured in the BIND zone. |
| `cluster_onboard_dns_tsig_key_secret` | `{{ vault_dns_tsig_key_secret }}` | TSIG key secret (automated mode). Resolved from `vault_secrets.yml`. Generate with: `tsig-keygen -a hmac-sha256 acm-update-key`. |
| `cluster_onboard_dns_tsig_key_algorithm` | `hmac-sha256` | TSIG HMAC algorithm for dynamic updates. |
| `cluster_onboard_listener_fqdn` | `{{ ansible_fqdn }}` | FQDN of the Ansible controller used as the SRV record target hostname. Defaults to the controller's FQDN as reported by Ansible. Override if the controller has multiple interfaces or a specific management FQDN. |

---

## 6. Ansible-Vault Secrets — `vars/vault_secrets.yml`

This file is **ansible-vault encrypted** and must never be committed in plaintext. See `vars/vault_secrets.yml.example` for the template.

| Variable | Required | Description |
|----------|----------|-------------|
| `vault_pull_secret` | Yes | OpenShift pull secret (single-line JSON) from [console.redhat.com](https://console.redhat.com/openshift/downloads). |
| `vault_ssh_public_key` | Yes | SSH public key embedded in `install-config.yaml`. Enables `core` user access to nodes post-install. |
| `vault_idrac_user_node1` | Yes | iDRAC username for hub-node1. |
| `vault_idrac_password_node1` | Yes | iDRAC password for hub-node1. |
| `vault_idrac_user_node2` | Yes | iDRAC username for hub-node2. |
| `vault_idrac_password_node2` | Yes | iDRAC password for hub-node2. |
| `vault_idrac_user_node3` | Yes | iDRAC username for hub-node3. |
| `vault_idrac_password_node3` | Yes | iDRAC password for hub-node3. |
| `vault_http_server_ip` | Yes | IP address of the HTTP staging server. |
| `vault_http_server_user` | Yes | SSH user for the HTTP staging server. |
| `vault_dns_tsig_key_secret` | Automated DNS mode | Base64 TSIG key secret for RFC 2136 dynamic DNS updates. Required when `cluster_onboard_dns_srv_mode: automated`. Generate with `tsig-keygen -a hmac-sha256 acm-update-key` and use the `secret` field value. |

---

## 7. GitOps Vault Secrets — `values-secret.yaml`

Located at `ansible/values-secret.yaml` (gitignored — never committed). Copy from `ansible/templates/values-secret.yaml.template`.

This file is read by `ansible/tasks/vault_init.yml` and its contents are pushed into HashiCorp Vault under the paths shown.

### Structure

```yaml
<secret-name>:
  vault_path: "secret/<prefix>/<name>"   # KV v2 path in Vault
  fields:
    <key>: "<value>"                      # One or more key-value pairs
```

### Predefined secrets

| Key name | Vault path | Fields | Description |
|----------|-----------|--------|-------------|
| `pull_secret` | `secret/global/pull-secret` | `pullSecret` | OpenShift pull secret JSON |
| `ssh_keys` | `secret/global/ssh-keys` | `publicKey`, `privateKey` | SSH keypair for node access |
| `bmc_credentials` | `secret/hub/bmc-credentials` | `hub_nodeN_user`, `hub_nodeN_password` | iDRAC credentials (Day 2 use) |
| `http_server` | `secret/hub/http-server` | `ip`, `user` | HTTP staging server |
| `gitops_repo` | `secret/hub/gitops-repo` | `username`, `password` | Git credentials (private repos only) |

### Adding child cluster secrets

For each spoke cluster, add a block using the spoke FQDN as the path prefix:

```yaml
spoke1_pull_secret:
  vault_path: "secret/spoke1.example.com/pull-secret"
  fields:
    pullSecret: '<pull secret JSON>'

spoke1_ssh_key:
  vault_path: "secret/spoke1.example.com/ssh-keys"
  fields:
    publicKey: "ssh-rsa AAAA..."
```

### Vault path convention

| Prefix | Purpose |
|--------|---------|
| `secret/global/` | Shared across all clusters (pull secret, SSH keys) |
| `secret/hub/` | Hub cluster only (BMC, HTTP server, observability storage) |
| `secret/<cluster-fqdn>/` | Per-spoke-cluster secrets |

---

## 8. GitOps Values — `groups/all/values.yaml`

Defines the ArgoCD `AppProject` and Applications shared across all clusters. Merged with each cluster's `values.yaml` by the `HelmChartInflationGenerator`.

### `defaults:` block

| Key | Value | Description |
|-----|-------|-------------|
| `defaults.repoURL` | `https://github.com/heatmiser/openshift-acm-app-of-apps` | Source repository. **Update to your fork.** |
| `defaults.targetRevision` | `main` | Fallback revision. Overridden at build time by the Kustomize replacement from `cluster-versions.yaml`. |
| `defaults.namespace` | `openshift-gitops` | Default namespace for Application resources. |
| `defaults.project` | `cluster-config` | Default ArgoCD AppProject. |
| `defaults.destination.server` | `https://kubernetes.default.svc` | Default destination cluster (the local cluster). |

### `projects:` block

Defines one or more ArgoCD `AppProject` resources. The default project `cluster-config` permits:
- All source repositories
- All destination namespaces on the local cluster
- All cluster-scoped resources

### `applications:` block

Each entry generates one ArgoCD `Application`. Keys:

| Key | Required | Description |
|-----|----------|-------------|
| `path` | Yes | Path in the git repo to the Kustomize component or overlay. |
| `syncWave` | No | ArgoCD sync-wave annotation value (string). Controls ordering within a sync. |
| `destination.namespace` | No | Target namespace on the destination cluster. Defaults to `defaults.namespace`. |
| `destination.server` | No | Target cluster API URL. Defaults to `defaults.destination.server` (local). |
| `repoURL` | No | Override the source repository for this Application only. |
| `targetRevision` | No | Override the git revision for this Application only. Usually left unset — the Kustomize replacement from `cluster-versions.yaml` sets this. |
| `helm` | No | Helm source configuration block (passed through to the Application spec). |
| `kustomize` | No | Kustomize source configuration block. |
| `syncPolicy` | No | Override the default sync policy for this Application. |
| `annotations` | No | Additional annotations to add to the Application metadata. |

---

## 9. Hub Applications — `clusters/hub/values.yaml`

Extends `groups/all/values.yaml` with hub-specific Applications. Uses the same schema as described in Section 8.

To add a new Application to the hub:

```yaml
applications:
  my-component:
    path: components/my-component
    syncWave: "5"
    destination:
      namespace: my-namespace
```

Commit and push — ArgoCD detects the change on the next reconcile cycle.

---

## 10. Cluster Branch Pinning — `clusters/cluster-versions.yaml`

```yaml
data:
  hub: main         # hub cluster tracks the 'main' branch
  spoke1: main      # spoke1 also tracks 'main'
  spoke2: release-1.0  # spoke2 pinned to a release branch
```

The Kustomize replacement in each `clusters/<name>/kustomization.yaml` reads the value for its cluster name and stamps it as `spec.source.targetRevision` on all generated Applications.

**To promote a cluster to a new branch:** change the branch name here, commit, and push. ArgoCD will begin tracking the new branch immediately on the next sync.

---

## 11. Sync Wave Reference

ArgoCD sync waves control the order in which resources are applied within a single sync operation. Resources in lower waves are applied and reconciled before higher waves begin.

| Wave | Purpose | Components |
|------|---------|-----------|
| `5` | Operator Subscriptions | `acm-operator`, `vault`, `metallb-operator`, `nmstate-operator`, `cert-manager-operator` |
| `6` | Operator Configuration | `eso` (Helm + ClusterSecretStore), `metallb-configuration`, `nmstate-configuration` |
| `15` | Operator Instances / CRs | `acm-instance` (MultiClusterHub), `gitops-bootstrap-policy` |
| `25` | Complex / Dependent Config | `acm-configuration` (AgentServiceConfig, ClusterImageSet), `acm-observability` |

### Wave dependencies

```
Wave 5 (subscriptions installed)
  └─► Wave 6 (CSVs running, CRDs present — safe to create config)
        └─► Wave 15 (operator fully ready — safe to create instances)
              └─► Wave 25 (MCH Running, storage available — safe for observability)
```

ESO (`wave 6`) will report `NotReady` until Vault is initialized by `acm_hub_configure.yml`. This is expected — ArgoCD shows the ClusterSecretStore as `Degraded` until the Ansible Vault init task completes.
