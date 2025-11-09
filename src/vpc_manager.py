import logging
import subprocess
from typing import List, Dict, Any
import ipaddress
import json
from dataclasses import asdict

from models import VPC, Subnet, FirewallRule
import os

class VPCManager:
    def __init__(self):
        self.vpcs = {}  # Store VPCs in memory
        # Persistent state file (prefer /var/lib but fall back to /tmp)
        self._state_path = self._determine_state_path()
        # Load persisted state if available
        self._load_state()

    def _determine_state_path(self) -> str:
        """Determine a writable path for persistent state."""
        primary_dir = '/var/lib/vpcctl'
        try:
            os.makedirs(primary_dir, exist_ok=True)
            test_path = os.path.join(primary_dir, 'state.json')
            # test write permissions by opening for append
            open(test_path, 'a').close()
            return test_path
        except Exception:
            # fallback to /tmp
            return os.path.join('/tmp', 'vpcctl_state.json')

    def _load_state(self) -> None:
        """Load VPC state from disk into memory."""
        try:
            if os.path.exists(self._state_path):
                with open(self._state_path, 'r') as f:
                    data = json.load(f)
                for name, v in data.items():
                    subnets = []
                    for s in v.get('subnets', []):
                        # Recreate FirewallRule objects if present
                        rules = [FirewallRule(**r) for r in s.get('firewall_rules', [])]
                        subnet = Subnet(
                            name=s['name'], cidr=s['cidr'], is_public=s['is_public'],
                            namespace=s['namespace'], bridge_ip=s['bridge_ip'], firewall_rules=rules
                        )
                        subnets.append(subnet)
                    self.vpcs[name] = VPC(name=v['name'], cidr=v['cidr'], bridge_name=v['bridge_name'], subnets=subnets)
                logging.info(f"Loaded VPC state from {self._state_path}")
        except Exception as e:
            logging.warning(f"Failed to load state from {self._state_path}: {e}")

    def _save_state(self) -> None:
        """Persist current VPC state to disk."""
        try:
            out = {}
            for name, vpc in self.vpcs.items():
                # Use asdict for dataclasses but convert FirewallRule objects
                v = {
                    'name': vpc.name,
                    'cidr': vpc.cidr,
                    'bridge_name': vpc.bridge_name,
                    'subnets': []
                }
                for s in vpc.subnets:
                    v['subnets'].append({
                        'name': s.name,
                        'cidr': s.cidr,
                        'is_public': s.is_public,
                        'namespace': s.namespace,
                        'bridge_ip': s.bridge_ip,
                        'firewall_rules': [asdict(r) for r in s.firewall_rules]
                    })
                out[name] = v
            with open(self._state_path, 'w') as f:
                json.dump(out, f, indent=2)
            logging.info(f"Saved VPC state to {self._state_path}")
        except Exception as e:
            logging.warning(f"Failed to save state to {self._state_path}: {e}")

    def _run_command(self, command: List[str]) -> None:
        """Run shell command and handle errors"""
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            logging.debug(f"Command output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Command failed: {e.stderr}")
            raise RuntimeError(f"Command failed: {e.stderr}")

    def _bridge_exists(self, bridge_name: str) -> bool:
        """Return True if a link with the given name exists in the kernel."""
        try:
            result = subprocess.run(['ip', 'link', 'show', bridge_name], check=False, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False

    def _get_default_if(self) -> str:
        """Detect host default outbound interface."""
        try:
            result = subprocess.run(['ip', 'route', 'get', '1.1.1.1'], capture_output=True, text=True, check=True)
            parts = result.stdout.split()
            # typical output: '1.1.1.1 via <gw> dev <if> src <ip> ...'
            if 'dev' in parts:
                idx = parts.index('dev')
                return parts[idx + 1]
        except Exception:
            pass
        return 'eth0'

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

        # If a bridge with the same name already exists in the kernel, reuse it (idempotent)
        if self._bridge_exists(bridge_name):
            logging.info(f"Bridge {bridge_name} already exists in kernel — reusing")
            # Ensure it's up
            self._run_command(['ip', 'link', 'set', bridge_name, 'up'])
        else:
            # Create Linux bridge
            self._run_command(['ip', 'link', 'add', bridge_name, 'type', 'bridge'])
            self._run_command(['ip', 'link', 'set', bridge_name, 'up'])

        # Store VPC information
        self.vpcs[name] = VPC(name=name, cidr=cidr, bridge_name=bridge_name)
        # Persist state
        self._save_state()
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
            # For public subnets, enable NAT (scoped to this subnet) and default route via bridge
            self._setup_nat(namespace, vpc.bridge_name, cidr)
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
        # Persist state after adding subnet
        self._save_state()

    def _setup_nat(self, namespace: str, vpc_bridge: str, subnet_cidr: str) -> None:
        """Configure NAT for a public subnet.

        The MASQUERADE rule is scoped to the subnet CIDR and we add forwarding
        rules between the VPC bridge and the host default interface. These
        rules will be removed when the VPC is deleted.
        """
        # Enable IP forwarding on the host so forwarded packets traverse the host
        self._run_command(['sysctl', '-w', 'net.ipv4.ip_forward=1'])

        default_if = self._get_default_if()

        # Setup masquerading scoped to the public subnet
        try:
            self._run_command([
                'iptables',
                '-t', 'nat', '-A', 'POSTROUTING', '-s', subnet_cidr, '-o', default_if,
                '-j', 'MASQUERADE'
            ])
        except Exception:
            logging.warning(f"Failed to add MASQUERADE rule for {subnet_cidr} -> {default_if}")

        # Allow forwarding on the host between vpc bridge and external interface
        try:
            self._run_command(['iptables', '-A', 'FORWARD', '-i', vpc_bridge, '-o', default_if, '-j', 'ACCEPT'])
            self._run_command(['iptables', '-A', 'FORWARD', '-i', default_if, '-o', vpc_bridge, '-j', 'ACCEPT'])
        except Exception:
            logging.warning(f"Failed to add FORWARD rules between {vpc_bridge} and {default_if}")

    def delete_vpc(self, name: str) -> None:
        """Delete a VPC and all its resources"""
        if name not in self.vpcs:
            raise ValueError(f"VPC {name} does not exist")

        vpc = self.vpcs[name]

        # Attempt to remove any host-level NAT/forwarding rules associated with
        # this VPC (for public subnets). Use best-effort deletion.
        try:
            self._cleanup_nat_for_vpc(vpc)
        except Exception as e:
            logging.warning(f"Failed to cleanup host-level NAT rules: {e}")

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
        # Persist state after deletion
        self._save_state()
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
        # Persist state for peering info
        self._save_state()

    def _cleanup_nat_for_vpc(self, vpc: VPC) -> None:
        """Remove host-level NAT and FORWARD rules that were added for the VPC's public subnets.

        This is best-effort: iptables -D may fail if rules changed externally.
        """
        default_if = self._get_default_if()
        for subnet in vpc.subnets:
            if not subnet.is_public:
                continue
            cidr = subnet.cidr
            # Delete MASQUERADE for this subnet
            try:
                self._run_command([
                    'iptables', '-t', 'nat', '-D', 'POSTROUTING', '-s', cidr, '-o', default_if, '-j', 'MASQUERADE'
                ])
            except Exception:
                logging.debug(f"MASQUERADE rule for {cidr} may not exist or already removed")

        # Delete FORWARD rules between this vpc bridge and default interface
        try:
            self._run_command(['iptables', '-D', 'FORWARD', '-i', vpc.bridge_name, '-o', default_if, '-j', 'ACCEPT'])
        except Exception:
            logging.debug(f"FORWARD rule ({vpc.bridge_name} -> {default_if}) may not exist")
        try:
            self._run_command(['iptables', '-D', 'FORWARD', '-i', default_if, '-o', vpc.bridge_name, '-j', 'ACCEPT'])
        except Exception:
            logging.debug(f"FORWARD rule ({default_if} -> {vpc.bridge_name}) may not exist")

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
        # Persist firewall rules
        self._save_state()

    def list_vpcs(self) -> List[VPC]:
        """List all VPCs"""
        return list(self.vpcs.values())