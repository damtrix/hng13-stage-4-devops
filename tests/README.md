# Testing the VPC Implementation

This document describes how to run the acceptance tests and manually verify the VPC functionality.

## Running Acceptance Tests

The acceptance tests in `tests/test_acceptance.py` validate all requirements from the assignment:

```bash
# Run all tests (requires root/sudo)
sudo python3 -m unittest tests/test_acceptance.py -v

# Run a specific test
sudo python3 -m unittest tests.test_acceptance.TestVPCAcceptance.test_vpc_creation -v
```

## Manual Testing Steps

### 1. Basic VPC Creation & Subnet Communication

```bash
# Create a VPC
sudo vpcctl create-vpc --name myvpc --cidr 10.0.0.0/16

# Add public and private subnets
sudo vpcctl add-subnet --vpc myvpc --name public1 --cidr 10.0.1.0/24 --public
sudo vpcctl add-subnet --vpc myvpc --name private1 --cidr 10.0.2.0/24

# Deploy test servers
sudo vpcctl deploy-app --vpc myvpc --subnet 10.0.1.0/24 --port 8080
sudo vpcctl deploy-app --vpc myvpc --subnet 10.0.2.0/24 --port 8081

# Test internal communication
sudo ip netns exec myvpc-public1 curl http://10.0.2.2:8081
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:8080
```

### 2. NAT & Internet Access

```bash
# Test internet access from public subnet
sudo ip netns exec myvpc-public1 ping -c1 8.8.8.8

# Verify private subnet cannot reach internet
sudo ip netns exec myvpc-private1 ping -c1 8.8.8.8  # Should fail
```

### 3. VPC Isolation & Peering

```bash
# Create two VPCs
sudo vpcctl create-vpc --name vpc1 --cidr 10.0.0.0/16
sudo vpcctl create-vpc --name vpc2 --cidr 172.16.0.0/16

# Add subnets to both
sudo vpcctl add-subnet --vpc vpc1 --name public1 --cidr 10.0.1.0/24 --public
sudo vpcctl add-subnet --vpc vpc2 --name public1 --cidr 172.16.1.0/24 --public

# Deploy test servers
sudo vpcctl deploy-app --vpc vpc1 --subnet 10.0.1.0/24 --port 8082
sudo vpcctl deploy-app --vpc vpc2 --subnet 172.16.1.0/24 --port 8083

# Test isolation (should fail)
sudo ip netns exec vpc1-public1 curl http://172.16.1.2:8083

# Create peering
sudo vpcctl peer-vpc --vpc1 vpc1 --vpc2 vpc2

# Test communication (should work)
sudo ip netns exec vpc1-public1 curl http://172.16.1.2:8083
```

### 4. Firewall Rules

Create a policy file `policy.json`:

```json
{
  "subnet": "10.0.1.0/24",
  "ingress": [
    { "port": 80, "protocol": "tcp", "action": "allow" },
    { "port": 22, "protocol": "tcp", "action": "deny" }
  ]
}
```

Apply and test:

```bash
# Apply firewall rules
sudo vpcctl add-rule --vpc myvpc --subnet 10.0.1.0/24 --policy policy.json

# Test allowed port
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:80

# Test denied port (should fail)
sudo ip netns exec myvpc-private1 nc -zv 10.0.1.2 22
```

### 5. Clean Teardown

```bash
# Delete VPCs
sudo vpcctl delete-vpc --name vpc1
sudo vpcctl delete-vpc --name vpc2

# Verify resources are gone
ip link show type bridge  # Should not show our bridges
ip netns list  # Should not show our namespaces
sudo iptables-save | grep -i vpc1  # Should show no rules
```

## Debugging Tips

1. List network namespaces:

```bash
sudo ip netns list
```

2. Inspect namespace networking:

```bash
sudo ip netns exec <namespace> ip addr
sudo ip netns exec <namespace> ip route
```

3. Check bridge interfaces:

```bash
bridge link show
```

4. View iptables rules:

```bash
sudo iptables-save
```

5. Check logs:

```bash
sudo journalctl -f  # Watch logs in real-time
```

6. Common issues:

- Permission denied: Ensure running with sudo
- RTNETLINK exists: Resource already exists, use delete-vpc first
- Connection timeout: Check routing and firewall rules
- No route to host: Verify subnet CIDR and routes

## Test Coverage

The acceptance tests verify:

1. VPC Creation (bridges, namespaces)
2. Subnet Communication (internal routing)
3. Public/Private Internet Access (NAT)
4. VPC Isolation & Peering
5. Firewall Rules
6. Resource Cleanup

Each test exercises the actual network stack and verifies connectivity.
