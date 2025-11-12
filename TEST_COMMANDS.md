# VPC Testing Commands

This document provides comprehensive test commands using the Makefile to validate all acceptance criteria.

## Quick Start

Run the complete test suite:

```bash
sudo make test-all
```

## Individual Test Parts

### Part 1: VPC Creation & Subnet Communication

Tests:

- ✅ Create VPC with bridge and namespaces
- ✅ Add public and private subnets
- ✅ Verify inter-subnet communication

```bash
sudo make test-part1
```

### Part 2: NAT Gateway (Public vs Private)

Tests:

- ✅ Public subnet has internet access
- ✅ Private subnet is blocked from internet
- ✅ NAT rules are configured

```bash
sudo make test-part2
```

### Part 3: VPC Isolation & Peering

Tests:

- ✅ Multiple VPCs are isolated by default
- ✅ VPC peering enables controlled communication
- ✅ Only specified CIDRs are accessible after peering

```bash
sudo make test-part3
```

### Part 4: Firewall & Security Groups

Tests:

- ✅ Firewall rules allow/deny traffic correctly
- ✅ Port-specific blocking works
- ✅ iptables rules are applied in namespaces

```bash
sudo make test-part4
```

### Part 5: Cleanup & Teardown

Tests:

- ✅ All resources are removed (bridges, namespaces, veth pairs)
- ✅ iptables rules are cleaned up
- ✅ No orphaned resources remain

```bash
sudo make test-part5
```

## Manual Testing Commands

If you prefer to test manually, here are the step-by-step commands:

### 1. Create VPC and Subnets

```bash
# Create VPC
sudo make create-vpc NAME=myvpc CIDR=10.0.0.0/16

# Add public subnet
sudo make add-subnet VPC=myvpc NAME=public1 CIDR=10.0.1.0/24 PUBLIC=1

# Add private subnet
sudo make add-subnet VPC=myvpc NAME=private1 CIDR=10.0.2.0/24
```

### 2. Test Subnet Communication

```bash
# Deploy servers
sudo make deploy-app VPC=myvpc SUBNET=10.0.1.0/24 PORT=8080
sudo make deploy-app VPC=myvpc SUBNET=10.0.2.0/24 PORT=8081

# Test connectivity
sudo ip netns exec myvpc-public1 curl http://10.0.2.2:8081
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:8080
```

### 3. Test NAT (Public vs Private)

```bash
# Public subnet should reach internet
sudo ip netns exec myvpc-public1 ping -c 1 8.8.8.8

# Private subnet should NOT reach internet
sudo ip netns exec myvpc-private1 ping -c 1 8.8.8.8  # Should fail
```

### 4. Test VPC Isolation & Peering

```bash
# Create second VPC
sudo make create-vpc NAME=myvpc2 CIDR=172.16.0.0/16
sudo make add-subnet VPC=myvpc2 NAME=public1 CIDR=172.16.1.0/24 PUBLIC=1

# Deploy server in second VPC
sudo make deploy-app VPC=myvpc2 SUBNET=172.16.1.0/24 PORT=8082

# Test isolation (should fail)
sudo ip netns exec myvpc-public1 curl http://172.16.1.2:8082

# Create peering with specific CIDRs
sudo make peer-vpc VPC1=myvpc VPC2=myvpc2 CIDRS="10.0.1.0/24 172.16.1.0/24"

# Test cross-VPC communication (should work now)
sudo ip netns exec myvpc-public1 curl http://172.16.1.2:8082
```

### 5. Test Firewall Rules

```bash
# Apply firewall policy
sudo make add-rule VPC=myvpc SUBNET=10.0.1.0/24 POLICY=example_policy.json

# Deploy server on allowed port
sudo make deploy-app VPC=myvpc SUBNET=10.0.1.0/24 PORT=80

# Test allowed port (should work)
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:80

# Test denied port (should fail)
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:22
```

### 6. Cleanup

```bash
# Stop applications
sudo make stop-app VPC=myvpc SUBNET=10.0.1.0/24 PORT=8080
sudo make stop-app VPC=myvpc SUBNET=10.0.2.0/24 PORT=8081

# Delete VPCs
sudo make delete-vpc NAME=myvpc
sudo make delete-vpc NAME=myvpc2

# Verify cleanup
sudo ip link show | grep br-
sudo ip netns list
```

## Verification Checklist

After running tests, verify:

- [ ] Bridges are created: `sudo ip link show | grep br-`
- [ ] Namespaces exist: `sudo ip netns list`
- [ ] Subnets can communicate: `curl` tests pass
- [ ] Public subnet has internet: `ping 8.8.8.8` works
- [ ] Private subnet blocked: `ping 8.8.8.8` fails
- [ ] VPCs isolated: cross-VPC curl fails before peering
- [ ] Peering works: cross-VPC curl succeeds after peering
- [ ] Firewall rules applied: `sudo ip netns exec <ns> iptables -L`
- [ ] Cleanup complete: no bridges/namespaces remain

## Troubleshooting

If tests fail:

1. **Check permissions**: All commands require `sudo`
2. **Check interface**: Default interface auto-detected, can override with `INTERFACE=eth0`
3. **Check state**: Use `make list` to see existing VPCs
4. **Clean state**: Use `make test-cleanup` to remove test VPCs
5. **Check logs**: VPC operations are logged with timestamps

## Notes

- Tests use VPC names `testvpc1` and `testvpc2` to avoid conflicts
- Ports used: 8080, 8081, 8082 (adjust if conflicts)
- Default interface is auto-detected from routing table
- All test resources are cleaned up in `test-part5`
