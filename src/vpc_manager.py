import logging
import subprocess
from typing import List, Dict
import ipaddress
import json

from models import VPC, Subnet, FirewallRule
import os

class VPCManager:
    def __init__(self):
        self.vpcs = {}  # Store VPCs in memory (in production, use persistent storage)

    def _run_command(self, command: List[str]) -> None:
        """Run shell command and handle errors"""
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            logging.debug(f"Command output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Command failed: {e.stderr}")
            raise RuntimeError(f"Command failed: {e.stderr}")

    def create_vpc(self, name: str, cidr: str) -> None:
        """Create a new VPC with a bridge interface"""
        if name in self.vpcs:
            raise ValueError(f"VPC {name} already exists")

        # Validate CIDR
        try:
            ipaddress.ip_network(cidr)
        except ValueError as e:
            raise ValueError(f"Invalid CIDR: {e}")

        bridge_name = f"br-{name}"

        # Create Linux bridge
        self._run_command(['ip', 'link', 'add', bridge_name, 'type', 'bridge'])
        self._run_command(['ip', 'link', 'set', bridge_name, 'up'])

        # Store VPC information
        self.vpcs[name] = VPC(name=name, cidr=cidr, bridge_name=bridge_name)
        logging.info(f"Created VPC {name} with bridge {bridge_name}")

    def add_subnet(self, vpc_name: str, subnet_name: str, cidr: str, is_public: bool) -> None:
        """Add a subnet to a VPC"""
        if vpc_name not in self.vpcs:
            raise ValueError(f"VPC {vpc_name} does not exist")

        vpc = self.vpcs[vpc_name]
        namespace = f"{vpc_name}-{subnet_name}"

        # Create network namespace
        self._run_command(['ip', 'netns', 'add', namespace])

        # Create veth pair
        veth0 = f"veth-{subnet_name}-0"
        veth1 = f"veth-{subnet_name}-1"
        self._run_command(['ip', 'link', 'add', veth0, 'type', 'veth', 'peer', 'name', veth1])

        # Connect one end to bridge
        self._run_command(['ip', 'link', 'set', veth0, 'master', vpc.bridge_name])
        self._run_command(['ip', 'link', 'set', veth0, 'up'])

        # Move other end to namespace and configure it
        self._run_command(['ip', 'link', 'set', veth1, 'netns', namespace])
        self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'link', 'set', 'dev', veth1, 'up'])

        # Calculate host and namespace IPs for this subnet
        network = ipaddress.ip_network(cidr)
        hosts = network.hosts()
        try:
            host_ip = str(next(hosts))
            ns_ip = str(next(hosts))
        except StopIteration:
            raise ValueError(f"CIDR {cidr} is too small to allocate addresses")

        host_addr = f"{host_ip}/{network.prefixlen}"
        ns_addr = f"{ns_ip}/{network.prefixlen}"

        # Assign IP to the bridge (acts as the gateway for the subnet).
        # It's safe to add multiple IPs to the bridge for different subnets.
        try:
            self._run_command(['ip', 'addr', 'add', host_addr, 'dev', vpc.bridge_name])
        except Exception:
            # If address already exists, ignore and continue
            logging.debug(f"Bridge {vpc.bridge_name} may already have address {host_addr}")

        # Configure IP in namespace (namespace side of veth)
        self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'addr', 'add', ns_addr, 'dev', veth1])

        # Add default route in namespace via bridge host IP
        if is_public:
            # For public subnets, enable NAT and default route via bridge
            self._setup_nat(namespace, vpc.bridge_name)
            self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'route', 'add', 'default', 'via', host_ip])
        else:
            # For private subnets, route to other subnets in the VPC via bridge
            self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'route', 'add', vpc.cidr, 'via', host_ip])

        # Add subnet to VPC
        subnet = Subnet(
            name=subnet_name,
            cidr=cidr,
            is_public=is_public,
            namespace=namespace,
            bridge_ip=host_addr
        )
        vpc.subnets.append(subnet)

    def _setup_nat(self, namespace: str, vpc_bridge: str) -> None:
        """Configure NAT for public subnets"""
        # Enable IP forwarding on the host so forwarded packets traverse the host
        self._run_command(['sysctl', '-w', 'net.ipv4.ip_forward=1'])

        # Get host's default interface (root namespace)
        try:
            result = subprocess.run(['ip', 'route', 'get', '1.1.1.1'], 
                                 capture_output=True, text=True, check=True)
            default_if = result.stdout.split()[4]
        except Exception:
            default_if = 'eth0'  # Fallback to eth0

        # Setup masquerading for outbound traffic from the subnet CIDR on the host
        # Use a generic MASQUERADE for traffic leaving via the host's default interface
        self._run_command([
            'iptables',
            '-t', 'nat', '-A', 'POSTROUTING', '-o', default_if,
            '-j', 'MASQUERADE'
        ])

        # Allow forwarding on the host between vpc bridge and external interface
        self._run_command(['iptables', '-A', 'FORWARD', '-i', vpc_bridge, '-o', default_if, '-j', 'ACCEPT'])
        self._run_command(['iptables', '-A', 'FORWARD', '-i', default_if, '-o', vpc_bridge, '-j', 'ACCEPT'])

    def delete_vpc(self, name: str) -> None:
        """Delete a VPC and all its resources"""
        if name not in self.vpcs:
            raise ValueError(f"VPC {name} does not exist")

        vpc = self.vpcs[name]

        # Delete all subnets
        for subnet in vpc.subnets:
            try:
                # Clear firewall rules first
                self._run_command(['ip', 'netns', 'exec', subnet.namespace, 'iptables', '-F'])
                self._run_command(['ip', 'netns', 'exec', subnet.namespace, 'iptables', '-t', 'nat', '-F'])
                
                # Delete namespace (this also removes all associated veth pairs)
                self._run_command(['ip', 'netns', 'del', subnet.namespace])
            except Exception as e:
                logging.warning(f"Error cleaning up subnet {subnet.name}: {str(e)}")

        try:
            # Delete bridge
            self._run_command(['ip', 'link', 'set', vpc.bridge_name, 'down'])
            self._run_command(['ip', 'link', 'delete', vpc.bridge_name])
        except Exception as e:
            logging.warning(f"Error deleting bridge {vpc.bridge_name}: {str(e)}")

        # Remove from memory
        del self.vpcs[name]
        logging.info(f"Successfully deleted VPC {name} and all its resources")

    def peer_vpcs(self, vpc1_name: str, vpc2_name: str) -> None:
        """Create a peering connection between two VPCs"""
        if vpc1_name not in self.vpcs or vpc2_name not in self.vpcs:
            raise ValueError("One or both VPCs do not exist")

        vpc1 = self.vpcs[vpc1_name]
        vpc2 = self.vpcs[vpc2_name]

        # Create veth pair for peering
        veth1 = f"veth-peer-{vpc1_name}"
        veth2 = f"veth-peer-{vpc2_name}"
        self._run_command(['ip', 'link', 'add', veth1, 'type', 'veth', 'peer', 'name', veth2])

        # Connect each end to respective bridges
        self._run_command(['ip', 'link', 'set', veth1, 'master', vpc1.bridge_name])
        self._run_command(['ip', 'link', 'set', veth2, 'master', vpc2.bridge_name])

        # Bring up interfaces
        self._run_command(['ip', 'link', 'set', veth1, 'up'])
        self._run_command(['ip', 'link', 'set', veth2, 'up'])

        # Assign a small point-to-point network for peering (use link-local range)
        # Generate deterministic last octet based on names so it's repeatable
        def _pick_octet(a: str, b: str) -> int:
            s = sum(ord(c) for c in (a + b))
            return 10 + (s % 200)

        octet = _pick_octet(vpc1_name, vpc2_name)
        peer_net_base = f"169.254.{octet}.0"
        ip1 = f"169.254.{octet}.1/30"
        ip2 = f"169.254.{octet}.2/30"

        # Assign addresses to the veth peer interfaces
        self._run_command(['ip', 'addr', 'add', ip1, 'dev', veth1])
        self._run_command(['ip', 'addr', 'add', ip2, 'dev', veth2])

        # Add routes on the host so traffic for each VPC CIDR is routed via the peer veth
        self._run_command(['ip', 'route', 'add', vpc2.cidr, 'via', '169.254.%d.2' % octet, 'dev', veth1])
        self._run_command(['ip', 'route', 'add', vpc1.cidr, 'via', '169.254.%d.1' % octet, 'dev', veth2])

    def deploy_app(self, vpc_name: str, subnet_cidr: str, port: int) -> None:
        """Deploy a simple Python HTTP server inside the subnet namespace.

        The server is started with nohup inside the namespace and a pid file is written to /tmp.
        """
        if vpc_name not in self.vpcs:
            raise ValueError(f"VPC {vpc_name} does not exist")

        vpc = self.vpcs[vpc_name]
        subnet = next((s for s in vpc.subnets if s.cidr == subnet_cidr), None)
        if not subnet:
            raise ValueError(f"Subnet with CIDR {subnet_cidr} not found in VPC {vpc_name}")

        namespace = subnet.namespace
        # Path to bundled web_server.py
        websrv = os.path.join(os.path.dirname(__file__), 'web_server.py')
        pidfile = f"/tmp/vpcctl-{namespace}-{port}.pid"
        logfile = f"/tmp/vpcctl-{namespace}-{port}.log"

        # Start the server in background inside the namespace
        cmd = (
            f"ip netns exec {namespace} bash -lc 'nohup python3 {websrv} {port} >{logfile} 2>&1 & echo $! > {pidfile}'"
        )
        self._run_command(['bash', '-c', cmd])
        logging.info(f"Deployed web server in namespace {namespace} on port {port} (pidfile: {pidfile})")

    def stop_app(self, vpc_name: str, subnet_cidr: str, port: int) -> None:
        """Stop the web server previously started in the namespace."""
        if vpc_name not in self.vpcs:
            raise ValueError(f"VPC {vpc_name} does not exist")

        vpc = self.vpcs[vpc_name]
        subnet = next((s for s in vpc.subnets if s.cidr == subnet_cidr), None)
        if not subnet:
            raise ValueError(f"Subnet with CIDR {subnet_cidr} not found in VPC {vpc_name}")

        namespace = subnet.namespace
        pidfile = f"/tmp/vpcctl-{namespace}-{port}.pid"
        if not os.path.exists(pidfile):
            raise RuntimeError(f"PID file {pidfile} not found; server may not be running")

        with open(pidfile) as f:
            pid = f.read().strip()

        # Kill the process if running
        try:
            self._run_command(['kill', pid])
        except Exception:
            logging.warning(f"Failed to kill pid {pid} directly; continuing cleanup")

        # Remove pid and logfile
        try:
            os.remove(pidfile)
        except OSError:
            pass

        logpath = f"/tmp/vpcctl-{namespace}-{port}.log"
        logging.info(f"Stopped web server in namespace {namespace}; log: {logpath}")

    def add_firewall_rules(self, vpc_name: str, subnet_cidr: str, policy: Dict) -> None:
        """Add firewall rules to a subnet"""
        if vpc_name not in self.vpcs:
            raise ValueError(f"VPC {vpc_name} does not exist")

        vpc = self.vpcs[vpc_name]
        subnet = next((s for s in vpc.subnets if s.cidr == subnet_cidr), None)
        if not subnet:
            raise ValueError(f"Subnet with CIDR {subnet_cidr} not found in VPC {vpc_name}")

        # Clear existing rules
        self._run_command(['ip', 'netns', 'exec', subnet.namespace, 'iptables', '-F'])

        # Add new rules
        for rule in policy.get('ingress', []):
            action = 'ACCEPT' if rule['action'] == 'allow' else 'DROP'
            self._run_command([
                'ip', 'netns', 'exec', subnet.namespace, 'iptables',
                '-A', 'INPUT',
                '-p', rule['protocol'],
                '--dport', str(rule['port']),
                '-j', action
            ])

        # Store rules in subnet object
        subnet.firewall_rules = [
            FirewallRule(
                port=rule['port'],
                protocol=rule['protocol'],
                action=rule['action']
            ) for rule in policy.get('ingress', [])
        ]

    def list_vpcs(self) -> List[VPC]:
        """List all VPCs"""
        return list(self.vpcs.values())