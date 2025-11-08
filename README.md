# Linux VPC Controller (vpcctl)

A tool for creating and managing Virtual Private Cloud (VPC) environments on Linux using network namespaces, bridges, and iptables.

## Features

- Create isolated VPCs with custom CIDR ranges
- Add public and private subnets to VPCs
- Implement VPC peering
- Configure NAT gateway for public subnets
- Manage security groups using iptables
- Full lifecycle management (create, inspect, delete)

## Requirements

- Linux operating system
- Python 3.6 or higher
- Root/sudo privileges
- Linux networking tools (ip, iptables, bridge-utils)

## Installation

1. Clone this repository
2. Make the CLI tool executable:
   ```bash
   chmod +x src/vpcctl.py
   ```
3. Create a symlink (optional):
   ```bash
   sudo ln -s $(pwd)/src/vpcctl.py /usr/local/bin/vpcctl
   ```

## Usage

### Creating a VPC

```bash
sudo vpcctl create-vpc --name myvpc --cidr 10.0.0.0/16
```

### Adding Subnets

```bash
# Add public subnet
sudo vpcctl add-subnet --vpc myvpc --name public1 --cidr 10.0.1.0/24 --public

# Add private subnet
sudo vpcctl add-subnet --vpc myvpc --name private1 --cidr 10.0.2.0/24
```

### VPC Peering

```bash
sudo vpcctl peer-vpc --vpc1 myvpc1 --vpc2 myvpc2
```

### Managing Security Groups

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

Apply the policy:

```bash
sudo vpcctl add-rule --vpc myvpc --subnet 10.0.1.0/24 --policy policy.json
```

### Listing VPCs

```bash
sudo vpcctl list
```

### Deleting a VPC

```bash
sudo vpcctl delete-vpc --name myvpc
```

### Deploying test web servers inside subnets

You can deploy a simple Python HTTP server inside a subnet namespace using the CLI. The server runs in background (nohup) and stores a pid file under /tmp.

```bash
# Deploy server into public subnet on port 8000
sudo vpcctl deploy-app --vpc myvpc --subnet 10.0.1.0/24 --port 8000

# Stop the server
sudo vpcctl stop-app --vpc myvpc --subnet 10.0.1.0/24 --port 8000
```

After deploying, you can curl the server from another namespace or from the host (if public):

```bash
# From private subnet namespace
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:8000

# From host (public subnet may be reachable depending on NAT/bridge setup)
curl http://10.0.1.2:8000
```

## Testing Connectivity

1. Deploy test web server in public subnet:

```bash
# Inside the public subnet namespace
sudo ip netns exec myvpc-public1 python src/web_server.py 80
```

2. Test connectivity from different subnets:

```bash
# From another namespace
sudo ip netns exec myvpc-private1 curl http://10.0.1.2:80
```

## Architecture

The tool creates:

- Linux bridges for VPC routing
- Network namespaces for subnet isolation
- veth pairs for connectivity
- iptables rules for security groups
- NAT rules for internet access

## License

MIT

## Contributing

Feel free to open issues and pull requests!
