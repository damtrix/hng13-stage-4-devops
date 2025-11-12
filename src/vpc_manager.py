import logging
import subprocess
from typing import Any, Dict, List, Optional, Tuple
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
        if not os.path.exists(self._state_path):
            return

        try:
            with open(self._state_path, 'r') as f:
                raw = json.load(f)
        except Exception as exc:
            logging.warning(f"Failed to read state file {self._state_path}: {exc}")
            return

        # Support both legacy (flat dict) and new (with top-level 'vpcs')
        data = raw.get('vpcs') if isinstance(raw, dict) and 'vpcs' in raw else raw
        if not isinstance(data, dict):
            logging.warning(f"State file {self._state_path} is malformed; ignoring")
            return

        for name, v in data.items():
            try:
                subnets: List[Subnet] = []
                for s in v.get('subnets', []):
                    rules = [FirewallRule(**r) for r in s.get('firewall_rules', [])]
                    subnet = Subnet(
                        name=s['name'],
                        cidr=s['cidr'],
                        is_public=s['is_public'],
                        namespace=s.get('namespace', f"{name}-{s['name']}"),
                        bridge_ip=s['bridge_ip'],
                        host_veth=s.get('host_veth'),
                        ns_veth=s.get('ns_veth'),
                        firewall_rules=rules
                    )
                    subnets.append(subnet)

                internet_interface = v.get('internet_interface') or self._get_default_if()
                bridge_name = v.get('bridge_name') or f"br-{self._sanitize_token(name, 10)}"
                peers = v.get('peers', [])

                self.vpcs[name] = VPC(
                    name=v.get('name', name),
                    cidr=v['cidr'],
                    bridge_name=bridge_name,
                    internet_interface=internet_interface,
                    peers=peers,
                    subnets=subnets
                )
            except Exception as exc:
                logging.warning(f"Failed to load VPC {name} from state: {exc}")

        logging.info(f"Loaded VPC state from {self._state_path}")

    def _save_state(self) -> None:
        """Persist current VPC state to disk."""
        snapshot: Dict[str, Any] = {}
        for name, vpc in self.vpcs.items():
            v = {
                'name': vpc.name,
                'cidr': vpc.cidr,
                'bridge_name': vpc.bridge_name,
                'internet_interface': vpc.internet_interface,
                'peers': vpc.peers,
                'subnets': []
            }
            for s in vpc.subnets:
                v['subnets'].append({
                    'name': s.name,
                    'cidr': s.cidr,
                    'is_public': s.is_public,
                    'namespace': s.namespace,
                    'bridge_ip': s.bridge_ip,
                    'host_veth': s.host_veth,
                    'ns_veth': s.ns_veth,
                    'firewall_rules': [asdict(r) for r in s.firewall_rules]
                })
            snapshot[name] = v

        try:
            with open(self._state_path, 'w') as f:
                json.dump({'vpcs': snapshot}, f, indent=2)
            logging.info(f"Saved VPC state to {self._state_path}")
        except Exception as exc:
            logging.warning(f"Failed to save state to {self._state_path}: {exc}")

    def _run_command(self, command: List[str]) -> None:
        """Run shell command and handle errors"""
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            logging.debug(f"Command output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Command failed: {e.stderr}")
            raise RuntimeError(f"Command failed: {e.stderr}")

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

    def _link_exists(self, name: str) -> bool:
        """Return True if a network link exists."""
        return subprocess.run(['ip', 'link', 'show', name], capture_output=True, text=True).returncode == 0

    def _namespace_exists(self, namespace: str) -> bool:
        """Return True if a network namespace exists."""
        result = subprocess.run(['ip', 'netns', 'list'], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return False
        namespaces = [line.split()[0] for line in result.stdout.strip().splitlines() if line]
        return namespace in namespaces

    def _sanitize_token(self, token: str, maxlen: int = 8) -> str:
        """Sanitize a name fragment for interface usage (max 15 chars once combined)."""
        safe = ''.join(ch for ch in token if ch.isalnum())
        if not safe:
            safe = 'ns'
        return safe[:maxlen].lower()

    def _veth_names(self, vpc_name: str, subnet_name: str) -> Tuple[str, str]:
        base_vpc = self._sanitize_token(vpc_name, 6)
        base_subnet = self._sanitize_token(subnet_name, 6)
        host = f"v{base_vpc}{base_subnet}h"
        ns = f"v{base_vpc}{base_subnet}n"
        return host[:15], ns[:15]

    def _peer_interface_names(self, vpc1_name: str, vpc2_name: str) -> Tuple[str, str]:
        base1 = self._sanitize_token(vpc1_name, 6)
        base2 = self._sanitize_token(vpc2_name, 6)
        link_a = f"p{base1}{base2}a"[:15]
        link_b = f"p{base2}{base1}b"[:15]
        return link_a, link_b

    def _ensure_bridge(self, bridge_name: str) -> None:
        """Ensure bridge exists and is up."""
        if self._link_exists(bridge_name):
            self._run_command(['ip', 'link', 'set', bridge_name, 'up'])
        else:
            self._run_command(['ip', 'link', 'add', bridge_name, 'type', 'bridge'])
            self._run_command(['ip', 'link', 'set', bridge_name, 'up'])

    def _allocate_subnet_ips(self, cidr: str) -> (str, str, int):
        network = ipaddress.ip_network(cidr)
        hosts = network.hosts()
        try:
            host_ip = str(next(hosts))
            ns_ip = str(next(hosts))
        except StopIteration:
            raise ValueError(f"CIDR {cidr} is too small to allocate addresses")
        return host_ip, ns_ip, network.prefixlen

    def _iptables_append_once(self, table: str, chain: str, rule: List[str]) -> None:
        check_cmd = ['iptables', '-t', table, '-C', chain] + rule
        add_cmd = ['iptables', '-t', table, '-A', chain] + rule
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self._run_command(add_cmd)

    def _iptables_delete_if_exists(self, table: str, chain: str, rule: List[str]) -> None:
        delete_cmd = ['iptables', '-t', table, '-D', chain] + rule
        subprocess.run(delete_cmd, capture_output=True, text=True)

    def create_vpc(self, name: str, cidr: str, internet_interface: Optional[str] = None) -> VPC:
        """Create or reconcile a VPC with a bridge interface."""
        try:
            requested_network = ipaddress.ip_network(cidr, strict=False)
        except ValueError as e:
            raise ValueError(f"Invalid CIDR: {e}")

        if name in self.vpcs:
            vpc = self.vpcs[name]
            if ipaddress.ip_network(vpc.cidr, strict=False) != requested_network:
                raise ValueError(f"VPC {name} already exists with CIDR {vpc.cidr}")
            if internet_interface:
                vpc.internet_interface = internet_interface
            self._ensure_bridge(vpc.bridge_name)
            self._save_state()
            logging.info(f"Reconciled VPC {name}")
            return vpc

        # Ensure we do not overlap with existing VPCs
        for existing in self.vpcs.values():
            existing_net = ipaddress.ip_network(existing.cidr, strict=False)
            if existing_net.overlaps(requested_network):
                raise ValueError(
                    f"CIDR {cidr} overlaps with existing VPC {existing.name} ({existing.cidr})"
                )

        uplink = internet_interface or self._get_default_if()
        bridge_name = f"br-{self._sanitize_token(name, 10)}"
        self._ensure_bridge(bridge_name)
        vpc = VPC(name=name, cidr=str(requested_network), bridge_name=bridge_name, internet_interface=uplink)
        self.vpcs[name] = vpc
        self._save_state()
        logging.info(f"Created VPC {name} with bridge {bridge_name} using uplink {uplink}")
        return vpc

    def add_subnet(self, vpc_name: str, subnet_name: str, cidr: str, is_public: bool) -> Subnet:
        """Add or reconcile a subnet within a VPC."""
        if vpc_name not in self.vpcs:
            raise ValueError(f"VPC {vpc_name} does not exist")

        vpc = self.vpcs[vpc_name]
        network = ipaddress.ip_network(cidr, strict=False)

        # Ensure no overlapping subnets (besides same subnet)
        for existing in vpc.subnets:
            existing_net = ipaddress.ip_network(existing.cidr, strict=False)
            if existing_net.overlaps(network) and existing.cidr != str(network):
                raise ValueError(f"CIDR {cidr} overlaps with existing subnet {existing.cidr} in VPC {vpc_name}")

        namespace = f"{vpc_name}-{subnet_name}"
        host_veth, ns_veth = self._veth_names(vpc_name, subnet_name)

        existing = next((s for s in vpc.subnets if s.name == subnet_name or s.cidr == str(network)), None)
        if existing:
            if existing.cidr != str(network) or existing.is_public != is_public:
                raise ValueError(f"Subnet {subnet_name} already exists with different attributes")
            existing.namespace = existing.namespace or namespace
            existing.host_veth = existing.host_veth or host_veth
            existing.ns_veth = existing.ns_veth or ns_veth
            self._reconcile_subnet(vpc, existing)
            self._save_state()
            return existing

        if not self._namespace_exists(namespace):
            self._run_command(['ip', 'netns', 'add', namespace])

        # Clean up stray link names if present
        if self._link_exists(host_veth):
            self._run_command(['ip', 'link', 'delete', host_veth])
        if self._link_exists(ns_veth):
            self._run_command(['ip', 'link', 'delete', ns_veth])

        # Create veth pair
        self._run_command(['ip', 'link', 'add', host_veth, 'type', 'veth', 'peer', 'name', ns_veth])

        # Connect host end to bridge
        self._run_command(['ip', 'link', 'set', host_veth, 'master', vpc.bridge_name])
        self._run_command(['ip', 'link', 'set', host_veth, 'up'])

        # Move other end to namespace
        self._run_command(['ip', 'link', 'set', ns_veth, 'netns', namespace])
        self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'link', 'set', 'dev', ns_veth, 'up'])

        # Allocate IPs
        host_ip, ns_ip, prefix = self._allocate_subnet_ips(str(network))
        host_addr = f"{host_ip}/{prefix}"
        ns_addr = f"{ns_ip}/{prefix}"

        # Configure bridge IP (gateway) and namespace IP
        self._run_command(['ip', 'addr', 'replace', host_addr, 'dev', vpc.bridge_name])
        self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'addr', 'replace', ns_addr, 'dev', ns_veth])

        # Configure routing
        if is_public:
            self._setup_nat(namespace, vpc.bridge_name, str(network), vpc.internet_interface)
            self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'route', 'replace', 'default', 'via', host_ip])
        else:
            # Remove default route if present and ensure route to VPC CIDR via gateway
            subprocess.run(['ip', 'netns', 'exec', namespace, 'ip', 'route', 'del', 'default'],
                           capture_output=True, text=True)
            self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'route', 'replace', vpc.cidr, 'via', host_ip])

        subnet = Subnet(
            name=subnet_name,
            cidr=str(network),
            is_public=is_public,
            namespace=namespace,
            bridge_ip=host_addr,
            host_veth=host_veth,
            ns_veth=ns_veth
        )
        vpc.subnets.append(subnet)
        self._save_state()
        return subnet

    def _reconcile_subnet(self, vpc: VPC, subnet: Subnet) -> None:
        """Ensure subnet resources exist and are configured as expected."""
        namespace = subnet.namespace or f"{vpc.name}-{subnet.name}"
        subnet.namespace = namespace
        host_veth, ns_veth = self._veth_names(vpc.name, subnet.name)
        subnet.host_veth = subnet.host_veth or host_veth
        subnet.ns_veth = subnet.ns_veth or ns_veth

        if not self._namespace_exists(namespace):
            self._run_command(['ip', 'netns', 'add', namespace])

        if not self._link_exists(subnet.host_veth or host_veth):
            # Recreate veth pair if missing
            if self._link_exists(host_veth):
                self._run_command(['ip', 'link', 'delete', host_veth])
            self._run_command(['ip', 'link', 'add', host_veth, 'type', 'veth', 'peer', 'name', ns_veth])
            subnet.host_veth = host_veth
            subnet.ns_veth = ns_veth

        self._run_command(['ip', 'link', 'set', host_veth, 'master', vpc.bridge_name])
        self._run_command(['ip', 'link', 'set', host_veth, 'up'])
        self._run_command(['ip', 'link', 'set', ns_veth, 'netns', namespace])
        self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'link', 'set', 'dev', ns_veth, 'up'])

        iface = ipaddress.ip_interface(subnet.bridge_ip)
        host_ip = str(iface.ip)
        prefix = iface.network.prefixlen
        subnet_cidr = subnet.cidr
        _, ns_ip, _ = self._allocate_subnet_ips(subnet_cidr)
        ns_addr = f"{ns_ip}/{prefix}"

        # Ensure bridge has gateway IP
        try:
            self._run_command(['ip', 'addr', 'add', subnet.bridge_ip, 'dev', vpc.bridge_name])
        except Exception:
            pass

        self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'addr', 'replace', ns_addr, 'dev', ns_veth])

        if subnet.is_public:
            self._setup_nat(namespace, vpc.bridge_name, subnet.cidr, vpc.internet_interface)
            self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'route', 'replace', 'default', 'via', host_ip])
        else:
            subprocess.run(
                ['ip', 'netns', 'exec', namespace, 'ip', 'route', 'del', 'default'],
                capture_output=True,
                text=True
            )
            self._run_command(['ip', 'netns', 'exec', namespace, 'ip', 'route', 'replace', vpc.cidr, 'via', host_ip])

    def _determine_allowed_cidrs(self, requested: List[str], target_vpc: VPC) -> List[str]:
        """Return CIDRs from requested that belong to target_vpc, or all subnets if none requested."""
        if not requested:
            return sorted({subnet.cidr for subnet in target_vpc.subnets})

        allowed = []
        target_networks = [ipaddress.ip_network(subnet.cidr) for subnet in target_vpc.subnets]
        for cidr in requested:
            network = ipaddress.ip_network(cidr, strict=False)
            if any(network.subnet_of(t) or network == t for t in target_networks):
                allowed.append(str(network))
        return sorted(set(allowed))

    def _update_peer_state(
        self,
        vpc: VPC,
        peer_name: str,
        local_link: str,
        remote_link: str,
        new_allowed: List[str]
    ) -> List[str]:
        """Update peer metadata for a VPC and return previous allowed CIDRs (for cleanup)."""
        previous = []
        entry = next((p for p in vpc.peers if p['peer'] == peer_name), None)
        if entry:
            previous = entry.get('allowed_remote_cidrs', [])
            entry.update({
                'local_link': local_link,
                'remote_link': remote_link,
                'allowed_remote_cidrs': new_allowed
            })
        else:
            vpc.peers.append({
                'peer': peer_name,
                'local_link': local_link,
                'remote_link': remote_link,
                'allowed_remote_cidrs': new_allowed
            })
        return previous

    def _configure_peer_routes(self, vpc: VPC, allowed: List[str], previous: List[str]) -> None:
        """Update namespace routes for peering."""
        allowed_set = set(allowed)
        previous_set = set(previous)
        remove = previous_set - allowed_set
        if not allowed_set and not remove:
            return

        for subnet in vpc.subnets:
            namespace = subnet.namespace
            gateway = str(ipaddress.ip_interface(subnet.bridge_ip).ip)
            for cidr in allowed_set:
                self._run_command([
                    'ip', 'netns', 'exec', namespace, 'ip', 'route', 'replace', cidr, 'via', gateway
                ])
            for cidr in remove:
                subprocess.run(
                    ['ip', 'netns', 'exec', namespace, 'ip', 'route', 'del', cidr],
                    capture_output=True,
                    text=True
                )

    def _remove_peer_routes(self, vpc: VPC, cidrs: List[str]) -> None:
        if not cidrs:
            return
        for subnet in vpc.subnets:
            namespace = subnet.namespace
            for cidr in cidrs:
                subprocess.run(
                    ['ip', 'netns', 'exec', namespace, 'ip', 'route', 'del', cidr],
                    capture_output=True,
                    text=True
                )

    def _teardown_peers(self, vpc: VPC) -> None:
        if not vpc.peers:
            return

        for peer_entry in list(vpc.peers):
            peer_name = peer_entry['peer']
            self._remove_peer_routes(vpc, peer_entry.get('allowed_remote_cidrs', []))
            local_link = peer_entry.get('local_link')
            if local_link and self._link_exists(local_link):
                try:
                    self._run_command(['ip', 'link', 'delete', local_link])
                except Exception:
                    logging.debug(f"Failed to delete peering link {local_link}")

            # Remove reciprocal data on peer VPC
            peer_vpc = self.vpcs.get(peer_name)
            if peer_vpc:
                reciprocal = next((p for p in peer_vpc.peers if p['peer'] == vpc.name), None)
                if reciprocal:
                    self._remove_peer_routes(peer_vpc, reciprocal.get('allowed_remote_cidrs', []))
                    peer_vpc.peers.remove(reciprocal)
            vpc.peers.remove(peer_entry)

    def _setup_nat(self, namespace: str, vpc_bridge: str, subnet_cidr: str, internet_interface: str) -> None:
        """Configure NAT for a public subnet.

        The MASQUERADE rule is scoped to the subnet CIDR and we add forwarding
        rules between the VPC bridge and the host default interface. These
        rules will be removed when the VPC is deleted.
        """
        # Enable IP forwarding on the host so forwarded packets traverse the host
        self._run_command(['sysctl', '-w', 'net.ipv4.ip_forward=1'])

        # Setup masquerading scoped to the public subnet
        self._iptables_append_once(
            'nat',
            'POSTROUTING',
            ['-s', subnet_cidr, '-o', internet_interface, '-j', 'MASQUERADE']
        )

        # Allow forwarding on the host between vpc bridge and external interface
        self._iptables_append_once('filter', 'FORWARD', ['-i', vpc_bridge, '-o', internet_interface, '-j', 'ACCEPT'])
        self._iptables_append_once('filter', 'FORWARD', ['-i', internet_interface, '-o', vpc_bridge, '-j', 'ACCEPT'])

    def delete_vpc(self, name: str) -> None:
        """Delete a VPC and all its resources"""
        if name not in self.vpcs:
            raise ValueError(f"VPC {name} does not exist")

        vpc = self.vpcs[name]

        # Teardown peering connections first
        self._teardown_peers(vpc)

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

                # Remove namespace routes
                try:
                    self._run_command(['ip', 'netns', 'exec', subnet.namespace, 'ip', 'route', 'flush', 'table', 'main'])
                except Exception:
                    pass

                # Delete namespace (this also removes all associated veth pairs)
                self._run_command(['ip', 'netns', 'del', subnet.namespace])
            except Exception as e:
                logging.warning(f"Error cleaning up subnet {subnet.name}: {str(e)}")

            # Remove host side veth if it still exists
            if subnet.host_veth and self._link_exists(subnet.host_veth):
                try:
                    self._run_command(['ip', 'link', 'delete', subnet.host_veth])
                except Exception:
                    logging.debug(f"Failed to delete host veth {subnet.host_veth}")

            # Remove bridge IP
            try:
                self._run_command(['ip', 'addr', 'del', subnet.bridge_ip, 'dev', vpc.bridge_name])
            except Exception:
                pass

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

    def peer_vpcs(self, vpc1_name: str, vpc2_name: str, allowed_cidrs: Optional[List[str]] = None) -> None:
        """Create or reconcile a peering connection between two VPCs.

        allowed_cidrs is a list of CIDRs that should be reachable across the peering.
        CIDRs belonging to vpc2 become reachable from vpc1, and vice versa.
        If empty/None, we expose all subnets from each VPC.
        """
        if vpc1_name not in self.vpcs or vpc2_name not in self.vpcs:
            raise ValueError("One or both VPCs do not exist")

        vpc1 = self.vpcs[vpc1_name]
        vpc2 = self.vpcs[vpc2_name]

        link_a, link_b = self._peer_interface_names(vpc1_name, vpc2_name)
        link_a_exists = self._link_exists(link_a)
        link_b_exists = self._link_exists(link_b)
        if link_a_exists != link_b_exists:
            # Partial leftover, delete and recreate
            if link_a_exists:
                self._run_command(['ip', 'link', 'delete', link_a])
            if link_b_exists:
                self._run_command(['ip', 'link', 'delete', link_b])
            link_a_exists = link_b_exists = False

        if not link_a_exists and not link_b_exists:
            self._run_command(['ip', 'link', 'add', link_a, 'type', 'veth', 'peer', 'name', link_b])
        else:
            self._run_command(['ip', 'link', 'set', link_a, 'down'])
            self._run_command(['ip', 'link', 'set', link_b, 'down'])

        self._run_command(['ip', 'link', 'set', link_a, 'master', vpc1.bridge_name])
        self._run_command(['ip', 'link', 'set', link_b, 'master', vpc2.bridge_name])
        self._run_command(['ip', 'link', 'set', link_a, 'up'])
        self._run_command(['ip', 'link', 'set', link_b, 'up'])

        requested = allowed_cidrs or []
        allow_for_vpc1 = self._determine_allowed_cidrs(requested, vpc2)
        allow_for_vpc2 = self._determine_allowed_cidrs(requested, vpc1)

        prev1 = self._update_peer_state(vpc1, vpc2_name, link_a, link_b, allow_for_vpc1)
        prev2 = self._update_peer_state(vpc2, vpc1_name, link_b, link_a, allow_for_vpc2)

        self._configure_peer_routes(vpc1, allow_for_vpc1, prev1)
        self._configure_peer_routes(vpc2, allow_for_vpc2, prev2)

        self._save_state()

    def _cleanup_nat_for_vpc(self, vpc: VPC) -> None:
        """Remove host-level NAT and FORWARD rules that were added for the VPC's public subnets.

        This is best-effort: iptables -D may fail if rules changed externally.
        """
        if not hasattr(vpc, 'internet_interface') or not vpc.internet_interface:
            vpc.internet_interface = self._get_default_if()
        default_if = vpc.internet_interface
        for subnet in vpc.subnets:
            if not subnet.is_public:
                continue
            cidr = subnet.cidr
            # Delete MASQUERADE for this subnet
            self._iptables_delete_if_exists('nat', 'POSTROUTING', ['-s', cidr, '-o', default_if, '-j', 'MASQUERADE'])

        # Delete FORWARD rules between this vpc bridge and default interface
        self._iptables_delete_if_exists('filter', 'FORWARD', ['-i', vpc.bridge_name, '-o', default_if, '-j', 'ACCEPT'])
        self._iptables_delete_if_exists('filter', 'FORWARD', ['-i', default_if, '-o', vpc.bridge_name, '-j', 'ACCEPT'])

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
        self._run_command(['ip', 'netns', 'exec', subnet.namespace, 'iptables', '-P', 'INPUT', 'DROP'])
        self._run_command(['ip', 'netns', 'exec', subnet.namespace, 'iptables', '-P', 'FORWARD', 'DROP'])
        self._run_command(['ip', 'netns', 'exec', subnet.namespace, 'iptables', '-P', 'OUTPUT', 'ACCEPT'])
        self._run_command([
            'ip', 'netns', 'exec', subnet.namespace, 'iptables', '-A', 'INPUT',
            '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'ACCEPT'
        ])
        self._run_command([
            'ip', 'netns', 'exec', subnet.namespace, 'iptables', '-A', 'INPUT',
            '-i', 'lo', '-j', 'ACCEPT'
        ])
        # Allow traffic from within the VPC CIDR (for inter-subnet communication)
        self._run_command([
            'ip', 'netns', 'exec', subnet.namespace, 'iptables', '-A', 'INPUT',
            '-s', vpc.cidr, '-j', 'ACCEPT'
        ])

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