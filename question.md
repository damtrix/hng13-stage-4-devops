# DevOps Intern Stage 4 Task – Build Your Own Virtual Private Cloud (VPC) on Linux

## Linux Networking, Isolation, and Routing from First Principles

### 👋 Hey Cool Keeds!

## 🔍 Overview

In this stage, you will recreate core VPC networking primitives **entirely on Linux**. Using tools such as **network namespaces**, **veth pairs**, **Linux bridges**, **routing tables**, and **iptables**, you will design and automate a mini-VPC environment that mirrors how cloud VPCs (AWS, GCP, Azure) operate internally.

You will deploy simple web servers (e.g., Nginx, Python HTTP server) inside your simulated subnets to demonstrate:

- Isolation
- Routing
- NAT
- Peering
- Security groups

---

## 🎯 Objectives

By the end of this task, you should be able to:

- Create and manage fully virtualized VPCs using Linux primitives.
- Provision multiple subnets (network namespaces) with unique CIDRs.
- Connect subnets using a Linux bridge acting as a VPC router.
- Enable inter-subnet routing.
- Implement NAT gateway functionality.
- Enforce subnet-level firewall rules.
- Support optional VPC peering.
- Automate everything with a custom **CLI tool `vpcctl`**.

---

## 🛠️ Task Breakdown

### **Part 1: Core VPC Creation**

Your `vpcctl` CLI should support:

- Create a VPC with a unique CIDR range.
- Add subnets (public/private) with unique CIDRs.
- Create namespaces per subnet.
- Connect namespaces via veth pairs to a Linux bridge (router).
- Auto-assign IP ranges.
- Auto-configure routing tables.
- Delete VPC and all associated resources.

### **Part 2: Routing and NAT Gateway**

Configure routing such that:

- Subnets communicate via the central bridge.
- Public subnet gets outbound internet via NAT.
- Private subnet has **no internet** unless routed via public subnet.

You must validate:

- Inter-subnet communication works.
- NAT works for public subnet.
- Private subnet stays isolated.

### **Part 3: VPC Isolation & Peering**

Support **multiple VPCs**, each with:

- Unique base CIDR
- Isolation by default

Add optional **VPC Peering**, implemented via:

- veth connection between VPC bridges
- Static routes pointing to peer CIDRs

Validation:

- Cross‑VPC communication should fail by default
- Should work when peering is explicitly configured

### **Part 4: Firewall & Security Groups**

Use **iptables** inside namespaces to enforce subnet-level firewall rules.

Provide a JSON policy format such as:

```json
{
  "subnet": "10.0.1.0/24",
  "ingress": [
    { "port": 80, "protocol": "tcp", "action": "allow" },
    { "port": 22, "protocol": "tcp", "action": "deny" }
  ]
}
```

Test cases should prove that policies correctly block or allow traffic.

### **Part 5: Cleanup & Automation**

Your CLI must:

- Fully delete all resources: namespaces, veth, bridges, iptables rules.
- Guarantee idempotency.
- Log all actions clearly.

---

## 📋 Requirements

| Variable             | Description                    |
| -------------------- | ------------------------------ |
| `VPC_NAME`           | Unique name for the VPC        |
| `CIDR_BLOCK`         | e.g., `10.0.0.0/16`            |
| `PUBLIC_SUBNET`      | Subnet with NAT access         |
| `PRIVATE_SUBNET`     | Subnet with no internet access |
| `INTERNET_INTERFACE` | Host outbound interface        |

**CLI must be in Bash or Python.**
**No virtualization libraries allowed.**

---

## ✅ Acceptance Criteria

| Test          | Expected Result                                           |
| ------------- | --------------------------------------------------------- |
| Create a VPC  | Bridge + namespaces + routing created                     |
| Add Subnets   | Correct CIDR allocation and communication internal to VPC |
| Public App    | Reachable externally or from host                         |
| Private App   | Not externally reachable                                  |
| Multiple VPCs | Fully isolated                                            |
| Peering       | Works only after explicit setup                           |
| NAT           | Public has internet; private does not                     |
| Firewall      | Traffic obeys rules                                       |
| Teardown      | All resources removed cleanly                             |

---

## 🧠 Demonstration Tests (Video)

Your video should show:

- Subnet‑to‑subnet communication
- Public subnet internet access
- Private subnet blocked from internet
- VPC isolation
- VPC peering allowing controlled communication
- Firewall rules blocking specific ports
- Logging of all operations

---

## 📂 Submission Requirements

### 1. GitHub Repository containing:

- `vpcctl` CLI (Python or Bash)
- Optional `Makefile`
- Cleanup script

### 2. Blog Post including:

- Overview and explanation
- CLI usage examples
- Architecture diagrams
- Testing steps
- Cleanup steps

### 3. Screen Recording (max 5 mins)

- Full walkthrough
- Clear timestamps
- Full terminal context

---

## ✅ Minimum for a Valid Submission

- Fully working VPC CLI
- At least one deployed app reachable internally
- VPC isolation demonstrated
- NAT behavior verified
- Clean teardown
- Logs for all actions
- Complete repo & screenshots submitted

---

## ⏰ Deadline & Attempts

- **Deadline:** 11:59 PM GMT, **12th November 2025**
- **Attempts Allowed:** 1
- **Late Submissions:** Not accepted
- **Submission Form:** Provided separately
