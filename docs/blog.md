# Building a Mini VPC on Linux — A Beginner's Guide

This project implements a lightweight Virtual Private Cloud (VPC) controller on Linux using only kernel primitives: network namespaces, veth pairs, Linux bridges and iptables. The CLI tool is called `vpcctl` and it's written in Python. This post explains the ideas, walks through the code, and shows how to get started.

If you like learning by doing, you'll find this a nice hands-on introduction to Linux networking fundamentals used by cloud providers.

---

## Table of contents

- What is a VPC and why build one on Linux?
- Project overview and goals
- Architecture (high level)
- Key files and what they do
- Quickstart (commands you can run)
- Walkthrough: create VPC, add subnet, deploy test app
- Peering, NAT and firewall overview
- Common issues & troubleshooting (including the "bridge missing" fix)
- Tests and how to run them
- Next steps and ideas for improvement

---

## What is a VPC and why build one on Linux?

A Virtual Private Cloud (VPC) is a logically isolated network that you can control and configure. Cloud providers (AWS, GCP, Azure) give you VPCs so you can run workloads in isolated networks with routing, NAT, and security rules.

This project recreates the key VPC primitives on a single Linux host for learning and experimentation. It helps you understand how namespaces, veths, bridges and iptables work together to provide isolation, routing, NAT and basic firewalling.

---

## Project overview and goals

- Provide a small CLI (`vpcctl`) to create/delete VPCs and add subnets.
- Use network namespaces for subnet isolation.
- Use a Linux bridge per VPC as the central router for that VPC.
- Implement NAT for "public" subnets so they can reach the internet.
- Apply simple firewall rules inside namespaces (security groups).
- Support optional VPC peering by connecting VPC bridges with a veth pair.

Everything is implemented with standard Linux tools — no virtualization libraries.

---

## Architecture (high level)

Each VPC is represented by:

- A Linux bridge (e.g. `br-myvpc`) that acts like the VPC router.
- One or more subnets. Each subnet is implemented as a network namespace (e.g. `myvpc-public1`).
- A veth pair connecting the namespace to the bridge. One end is in the namespace, the other is a peer on the host and added to the bridge.
- For public subnets, iptables rules on the host perform MASQUERADE (NAT) so namespaced hosts can reach the internet.

ASCII sketch:

```
[ host ] --- eth0 (internet)
   |
   +--- br-myvpc (bridge)
         |
         +-- veth-host-public1 (attached to bridge)
         |    peer -> veth-ns-public1 (in namespace myvpc-public1)
         |
         +-- veth-host-private1 (attached to bridge)
              peer -> veth-ns-private1 (in namespace myvpc-private1)
```

Routing: the bridge holds the gateway IP for each subnet and namespaces set their default route via that gateway.

---

## Key files and a simple explanation

- `src/vpcctl.py` — CLI wrapper. Parses command line arguments and calls the manager functions.

  - Commands: `create-vpc`, `add-subnet`, `peer-vpc`, `add-rule`, `deploy-app`, `stop-app`, `delete-vpc`, `list`.
  - `create-vpc` optionally takes `--internet-interface` so NAT is wired to the correct uplink.
  - `peer-vpc` accepts repeated `--allow-cidr` flags to constrain which subnets are reachable across the peering.

- `src/vpc_manager.py` — Core logic. Main responsibilities:

  - Create/delete bridges (VPCs).
  - Create network namespaces and veth pairs for subnets.
  - Assign IP addresses and configure routes.
  - Configure NAT (iptables MASQUERADE) for public subnets.
  - Create peering between VPC bridges (via a veth pair and host routes).
  - Manage simple firewall rules inside namespaces.
  - Persist VPC state to disk under `/var/lib/vpcctl/state.json` (fallback `/tmp` when needed).

  Important design choices to understand:

  - State vs kernel resources: the manager stores metadata on disk. Kernel objects (bridges/namespaces) can be removed outside the tool (reboot, manual delete). The manager attempts to be idempotent and will try to repair missing bridges when the state says a VPC exists but the bridge device is gone. This avoids "device does not exist" errors when adding subnets.

- `src/models.py` — Dataclasses for `VPC`, `Subnet`, and `FirewallRule`. These are the simple in-memory structures persisted to JSON.

- `src/web_server.py` — Tiny Python HTTP server used by `deploy-app` to test connectivity.

- `tests/test_acceptance.py` — Acceptance tests that exercise the real network stack created by the tool (namespaces, bridges, NAT, firewall and peering). These tests run commands like `ip netns exec <ns> curl ...` to verify connectivity.

- `tests/README.md` — Manual testing and debugging guidance.

---

## Quickstart (run these commands)

Prerequisites:

- Linux host (this tool uses `ip`, `iptables`, `bridge-utils`)
- Root privileges (run with `sudo`)
- Python 3.6+

Install the CLI (from repo root):

```bash
chmod +x src/vpcctl.py
sudo ln -s $(pwd)/src/vpcctl.py /usr/local/bin/vpcctl   # optional but convenient
```

**Option 1: Using the CLI directly**

Create a VPC and add subnets:

```bash
# create VPC
sudo vpcctl create-vpc --name myvpc --cidr 10.0.0.0/16 --internet-interface eth0

# add a public subnet
sudo vpcctl add-subnet --vpc myvpc --name public1 --cidr 10.0.1.0/24 --public

# add a private subnet
sudo vpcctl add-subnet --vpc myvpc --name private1 --cidr 10.0.2.0/24
```

**Option 2: Using the Makefile (convenience shortcuts)**

The repo includes a `Makefile` with helper targets that wrap the CLI calls:

```bash
# create VPC
make create-vpc NAME=myvpc CIDR=10.0.0.0/16 INTERFACE=eth0

# add a public subnet
make add-subnet VPC=myvpc NAME=public1 CIDR=10.0.1.0/24 PUBLIC=1

# add a private subnet
make add-subnet VPC=myvpc NAME=private1 CIDR=10.0.2.0/24

# list VPCs
make list

# delete VPC
make delete-vpc NAME=myvpc
```

Deploy a tiny server inside the public subnet and test connectivity from the private subnet:

```bash
# start server in public subnet on port 8000
sudo vpcctl deploy-app --vpc myvpc --subnet 10.0.1.0/24 --port 8000

# from the private namespace, curl the public server
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:8000
```

When done, delete the VPC (this attempts to clean up all namespaces, bridges and host iptables rules):

```bash
# Using CLI directly
sudo vpcctl delete-vpc --name myvpc

# Or using Makefile
make delete-vpc NAME=myvpc
```

---

## Walkthrough: what happens under the hood for `add-subnet`

1. The manager creates a namespace `myvpc-public1`.
2. It creates a veth pair, e.g. `veth-public1-0` (host side) and `veth-public1-1` (ns side).
3. The host end is attached to the VPC bridge `br-myvpc` and brought up.
4. The namespace side gets an IP (e.g. `10.0.1.2/24`) and `ip link set ... up` runs inside the namespace.
5. The bridge is assigned a gateway IP for the subnet (e.g. `10.0.1.1/24`).
6. If the subnet is `--public`, the manager adds an iptables MASQUERADE rule on the host to allow outbound internet, and adds FORWARD rules between the bridge and the host's default interface.

That yields a working internal network where namespaces can reach each other (via the bridge) and public subnets can reach the outside world.

---

## NAT, Peering and Firewall

- NAT (public subnet): implemented by adding an iptables rule like:

```text
iptables -t nat -A POSTROUTING -s 10.0.1.0/24 -o <host_if> -j MASQUERADE
```

Plus FORWARD rules to allow traffic to flow between the bridge and the external interface.

- Peering: `peer-vpc` creates a veth pair that connects the two VPC bridges together and adds per-namespace routes for the peer CIDRs you explicitly allow with `--allow-cidr`. Only those CIDR blocks become reachable across the peering.

- Firewall: The manager adds `iptables` rules inside a namespace (so they're namespace-scoped) to allow or drop traffic on specific ports according to a small JSON policy format.

---

## Common issues & troubleshooting

1. "VPC myvpc already exists" when creating a VPC

   - Cause: There is an entry for the VPC in the persistent state (e.g. `/var/lib/vpcctl/state.json`) but the kernel bridge device might be missing (manually deleted or lost after a partial cleanup).
   - Fix: Two options:
            - Let the tool repair the bridge: the manager now attempts to recreate a missing bridge when it sees a VPC in state. Re-run `sudo vpcctl create-vpc --name myvpc --cidr ... --internet-interface <uplink>` and it will repair the bridge.
     - Manually remove the state entry (not recommended unless you know what you are doing): backup `/var/lib/vpcctl/state.json` and delete the `myvpc` key from the JSON.

2. "Device does not exist" when adding subnets

   - Cause: Tool tried to attach veth to `br-myvpc` but the device wasn't present in the kernel.
   - Fix: Recreate the bridge manually (low-risk):

```bash
sudo ip link add br-myvpc type bridge
sudo ip link set br-myvpc up
```

- Then retry `vpcctl add-subnet ...`.

3. Permission / sudo problems

   - The tool performs privileged networking actions. Run commands with `sudo` or as root.

4. Leftover iptables rules

   - If the process crashes and `delete-vpc` wasn't run, some host iptables rules (MASQUERADE and FORWARD) may remain. The tool tries to remove them when deleting a VPC, but you can inspect with:

```bash
sudo iptables-save | grep -i myvpc
```

To remove MASQUERADE rules manually, adjust the exact rule and use `iptables -t nat -D POSTROUTING ...`.

---

## Running the test suite

The repository contains `tests/test_acceptance.py` which performs end-to-end checks. These tests exercise the real network stack and require root.

Run the acceptance test:

```bash
sudo python3 -m unittest tests/test_acceptance.py -v
```

Be careful: the tests create and delete network namespaces and iptables rules on your host. Run them on a throwaway VM or a test environment.

---

## Contribution and next steps

If you'd like to extend the project, here are some ideas:

- Add a `repair-vpc` explicit CLI command that shows what the tool will recreate.
- Add better reconciliation: on startup, scan kernel resources and reconcile with state (detect drift).
- Add IPv6 support.
- Improve tests to run in CI using privileged Docker containers (or GitHub Actions runners with networking privileges).
- Add an option to use a `--dry-run` mode where commands are printed but not executed (useful for learning).

---

## Final notes

This project is an excellent hands-on way to learn Linux networking primitives used in real cloud networking. It's intentionally small and educational — perfect for tinkering, demoing, or using as a base for more advanced network experiments.

If you want, I can also:

- Create a short video script that demonstrates each requirement, or
- Add diagrams (SVG/PNG) next to the blog, or
- Convert this blog into a README section and commit it for your repo homepage.

Which would you like next?
