#!/usr/bin/env python3
"""Acceptance tests that validate the VPC implementation against the assignment requirements."""

import unittest
import subprocess
import time
import json
import os
import logging
from src.vpc_manager import VPCManager

def run_cmd(cmd, check=True):
    """Run a shell command and return output."""
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {result.stderr}")
    return result.stdout.strip()

class TestVPCAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize test environment."""
        if os.geteuid() != 0:
            raise RuntimeError("Tests must be run as root (sudo)")
        cls.manager = VPCManager()
        cls.vpc_name = "testvpc"
        cls.vpc_cidr = "10.0.0.0/16"
        cls.public_cidr = "10.0.1.0/24"
        cls.private_cidr = "10.0.2.0/24"
        cls.peer_vpc_name = "testvpc2"
        cls.peer_vpc_cidr = "172.16.0.0/16"

    def setUp(self):
        """Create a fresh VPC for each test."""
        self.cleanup()  # Ensure clean state
        self.manager.create_vpc(self.vpc_name, self.vpc_cidr)

    def tearDown(self):
        """Clean up after each test."""
        self.cleanup()

    def cleanup(self):
        """Remove test VPCs and verify cleanup."""
        try:
            self.manager.delete_vpc(self.vpc_name)
        except Exception:
            pass
        try:
            self.manager.delete_vpc(self.peer_vpc_name)
        except Exception:
            pass
        # Verify no leftover resources
        self.assertFalse(self._resource_exists('bridge', f'br-{self.vpc_name}'))
        self.assertFalse(self._namespace_exists(f'{self.vpc_name}-public1'))

    def _resource_exists(self, type_name, name):
        """Check if a network resource exists."""
        if type_name == 'bridge':
            return os.system(f'ip link show {name} type bridge >/dev/null 2>&1') == 0
        elif type_name == 'veth':
            return os.system(f'ip link show {name} type veth >/dev/null 2>&1') == 0
        return False

    def _namespace_exists(self, ns):
        """Check if a network namespace exists."""
        return os.system(f'ip netns list | grep -q "^{ns}"') == 0

    def _deploy_test_server(self, namespace, port):
        """Deploy a test web server in a namespace."""
        websrv = os.path.join(os.path.dirname(__file__), '..', 'src', 'web_server.py')
        cmd = f'ip netns exec {namespace} python3 {websrv} {port} & echo $! > /tmp/test-server-{port}.pid'
        run_cmd(cmd)
        time.sleep(1)  # Let server start

    def _kill_test_server(self, port):
        """Stop test web server."""
        try:
            with open(f'/tmp/test-server-{port}.pid') as f:
                pid = f.read().strip()
            run_cmd(f'kill {pid}', check=False)
            os.unlink(f'/tmp/test-server-{port}.pid')
        except Exception:
            pass

    def _can_curl(self, namespace, url):
        """Test if a namespace can reach a URL."""
        cmd = f'ip netns exec {namespace} curl -s --connect-timeout 2 {url}'
        try:
            return run_cmd(cmd, check=False) != ''
        except Exception:
            return False

    def test_vpc_creation(self):
        """Test 1: Create a VPC - Bridge + namespaces + routing created."""
        # Bridge should exist
        self.assertTrue(self._resource_exists('bridge', f'br-{self.vpc_name}'))
        
        # Add a subnet and verify namespace
        self.manager.add_subnet(self.vpc_name, "public1", self.public_cidr, True)
        self.assertTrue(self._namespace_exists(f'{self.vpc_name}-public1'))

    def test_subnet_communication(self):
        """Test 2: Add Subnets - Correct CIDR allocation and internal VPC communication."""
        # Create public and private subnets
        self.manager.add_subnet(self.vpc_name, "public1", self.public_cidr, True)
        self.manager.add_subnet(self.vpc_name, "private1", self.private_cidr, False)

        # Deploy test servers in both subnets
        self._deploy_test_server(f'{self.vpc_name}-public1', 8080)
        self._deploy_test_server(f'{self.vpc_name}-private1', 8081)

        try:
            # Verify subnets can communicate
            self.assertTrue(
                self._can_curl(f'{self.vpc_name}-public1', 'http://10.0.2.2:8081'),
                "Public subnet cannot reach private subnet"
            )
            self.assertTrue(
                self._can_curl(f'{self.vpc_name}-private1', 'http://10.0.1.2:8080'),
                "Private subnet cannot reach public subnet"
            )
        finally:
            self._kill_test_server(8080)
            self._kill_test_server(8081)

    def test_public_private_internet(self):
        """Test 3/4: Public app reachable + Private app isolated from internet."""
        self.manager.add_subnet(self.vpc_name, "public1", self.public_cidr, True)
        self.manager.add_subnet(self.vpc_name, "private1", self.private_cidr, False)

        # Test internet connectivity
        ping_cmd = "ping -c 1 8.8.8.8"
        
        # Public subnet should reach internet
        public_result = run_cmd(
            f'ip netns exec {self.vpc_name}-public1 {ping_cmd}',
            check=False
        )
        self.assertEqual(0, os.WEXITSTATUS(os.system(
            f'ip netns exec {self.vpc_name}-public1 {ping_cmd} >/dev/null 2>&1'
        )), "Public subnet cannot reach internet")

        # Private subnet should NOT reach internet
        private_result = os.system(
            f'ip netns exec {self.vpc_name}-private1 {ping_cmd} >/dev/null 2>&1'
        )
        self.assertNotEqual(0, os.WEXITSTATUS(private_result),
                          "Private subnet should not reach internet")

    def test_vpc_isolation_and_peering(self):
        """Test 5/6: Multiple VPCs isolated + Peering works after setup."""
        # Create second VPC
        self.manager.create_vpc(self.peer_vpc_name, self.peer_vpc_cidr)
        
        # Add subnets to both VPCs
        self.manager.add_subnet(self.vpc_name, "public1", self.public_cidr, True)
        self.manager.add_subnet(self.peer_vpc_name, "public1", "172.16.1.0/24", True)

        # Deploy test servers
        self._deploy_test_server(f'{self.vpc_name}-public1', 8082)
        self._deploy_test_server(f'{self.peer_vpc_name}-public1', 8083)

        try:
            # VPCs should be isolated by default
            self.assertFalse(
                self._can_curl(f'{self.vpc_name}-public1', 'http://172.16.1.2:8083'),
                "VPCs should be isolated by default"
            )

            # Set up peering
            self.manager.peer_vpcs(self.vpc_name, self.peer_vpc_name)

            # Now they should communicate
            self.assertTrue(
                self._can_curl(f'{self.vpc_name}-public1', 'http://172.16.1.2:8083'),
                "VPCs should communicate after peering"
            )
        finally:
            self._kill_test_server(8082)
            self._kill_test_server(8083)

    def test_firewall_rules(self):
        """Test 7: Firewall - Traffic obeys rules."""
        self.manager.add_subnet(self.vpc_name, "public1", self.public_cidr, True)
        
        # Deploy test server
        self._deploy_test_server(f'{self.vpc_name}-public1', 8084)

        try:
            # Add firewall rules allowing 8084 but blocking 8085
            policy = {
                "subnet": self.public_cidr,
                "ingress": [
                    {"port": 8084, "protocol": "tcp", "action": "allow"},
                    {"port": 8085, "protocol": "tcp", "action": "deny"}
                ]
            }
            self.manager.add_firewall_rules(self.vpc_name, self.public_cidr, policy)

            # Port 8084 should work
            self.assertTrue(
                self._can_curl(f'{self.vpc_name}-public1', 'http://10.0.1.2:8084'),
                "Allowed port should work"
            )

            # Port 8085 should fail
            self.assertFalse(
                self._can_curl(f'{self.vpc_name}-public1', 'http://10.0.1.2:8085'),
                "Denied port should fail"
            )
        finally:
            self._kill_test_server(8084)

    def test_cleanup(self):
        """Test 8: Teardown - All resources removed cleanly."""
        # Create complex setup
        self.manager.add_subnet(self.vpc_name, "public1", self.public_cidr, True)
        self.manager.add_subnet(self.vpc_name, "private1", self.private_cidr, False)
        
        # Add some firewall rules
        policy = {
            "subnet": self.public_cidr,
            "ingress": [
                {"port": 80, "protocol": "tcp", "action": "allow"}
            ]
        }
        self.manager.add_firewall_rules(self.vpc_name, self.public_cidr, policy)

        # Delete VPC
        self.manager.delete_vpc(self.vpc_name)

        # Verify all resources are gone
        self.assertFalse(self._resource_exists('bridge', f'br-{self.vpc_name}'))
        self.assertFalse(self._namespace_exists(f'{self.vpc_name}-public1'))
        self.assertFalse(self._namespace_exists(f'{self.vpc_name}-private1'))

        # Verify no dangling iptables rules (check for our bridge name)
        iptables = run_cmd('iptables-save', check=False)
        self.assertNotIn(f'br-{self.vpc_name}', iptables,
                        "Cleanup left dangling iptables rules")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    unittest.main(verbosity=2)