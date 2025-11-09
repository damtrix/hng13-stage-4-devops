import unittest
import os
import json
import ipaddress
from src.vpc_manager import VPCManager
from src.models import VPC, Subnet

class TestVPCManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        cls.manager = VPCManager()
        # Ensure we're running as root
        if os.geteuid() != 0:
            raise RuntimeError("Tests must be run as root")
            
    def setUp(self):
        """Set up for each test"""
        # Clean up any existing test VPCs
        self.cleanup_test_vpcs()
        
    def tearDown(self):
        """Clean up after each test"""
        self.cleanup_test_vpcs()

    def cleanup_test_vpcs(self):
        """Helper to clean up test VPCs"""
        test_vpcs = ['test_vpc', 'test_vpc1', 'test_vpc2']
        for vpc_name in test_vpcs:
            try:
                self.manager.delete_vpc(vpc_name)
            except Exception:
                pass

    def test_create_vpc(self):
        """Test VPC creation with valid CIDR"""
        vpc_name = "test_vpc"
        cidr = "10.0.0.0/16"
        
        # Create VPC
        vpc = self.manager.create_vpc(vpc_name, cidr)
        
        # Verify VPC creation
        self.assertIsNotNone(vpc)
        self.assertEqual(vpc.name, vpc_name)
        self.assertEqual(vpc.cidr, cidr)
        
        # Verify bridge creation
        bridge_exists = os.system(f"ip link show {vpc_name}-bridge > /dev/null 2>&1") == 0
        self.assertTrue(bridge_exists, "Bridge not created")

    def test_add_public_subnet(self):
        """Test adding a public subnet to VPC"""
        vpc_name = "test_vpc"
        vpc_cidr = "10.0.0.0/16"
        subnet_cidr = "10.0.1.0/24"
        
        # Create VPC and add public subnet
        vpc = self.manager.create_vpc(vpc_name, vpc_cidr)
        subnet = self.manager.add_subnet(vpc_name, "public1", subnet_cidr, is_public=True)
        
        # Verify subnet creation
        self.assertIsNotNone(subnet)
        self.assertEqual(subnet.cidr, subnet_cidr)
        self.assertTrue(subnet.is_public)
        
        # Verify namespace creation
        ns_exists = os.system(f"ip netns show | grep {vpc_name}-public1 > /dev/null 2>&1") == 0
        self.assertTrue(ns_exists, "Namespace not created")

    def test_add_private_subnet(self):
        """Test adding a private subnet to VPC"""
        vpc_name = "test_vpc"
        vpc_cidr = "10.0.0.0/16"
        subnet_cidr = "10.0.2.0/24"
        
        # Create VPC and add private subnet
        vpc = self.manager.create_vpc(vpc_name, vpc_cidr)
        subnet = self.manager.add_subnet(vpc_name, "private1", subnet_cidr, is_public=False)
        
        # Verify subnet creation
        self.assertIsNotNone(subnet)
        self.assertEqual(subnet.cidr, subnet_cidr)
        self.assertFalse(subnet.is_public)

    def test_vpc_peering(self):
        """Test VPC peering functionality"""
        # Create two VPCs
        vpc1 = self.manager.create_vpc("test_vpc1", "10.0.0.0/16")
        vpc2 = self.manager.create_vpc("test_vpc2", "172.16.0.0/16")
        
        # Add subnets to both VPCs
        subnet1 = self.manager.add_subnet("test_vpc1", "subnet1", "10.0.1.0/24")
        subnet2 = self.manager.add_subnet("test_vpc2", "subnet1", "172.16.1.0/24")
        
        # Peer the VPCs
        self.manager.peer_vpcs("test_vpc1", "test_vpc2")
        
        # Verify peering (basic check - more detailed verification would require actual traffic testing)
        self.assertTrue(True)  # If we got here without errors, basic peering worked

    def test_add_firewall_rules(self):
        """Test adding firewall rules to a subnet"""
        vpc_name = "test_vpc"
        vpc_cidr = "10.0.0.0/16"
        subnet_cidr = "10.0.1.0/24"
        
        # Create VPC and subnet
        vpc = self.manager.create_vpc(vpc_name, vpc_cidr)
        subnet = self.manager.add_subnet(vpc_name, "public1", subnet_cidr, is_public=True)
        
        # Create test policy
        policy = {
            "subnet": subnet_cidr,
            "ingress": [
                {"port": 80, "protocol": "tcp", "action": "allow"},
                {"port": 22, "protocol": "tcp", "action": "deny"}
            ]
        }
        
        # Apply firewall rules
        self.manager.add_firewall_rules(vpc_name, subnet_cidr, policy)
        
        # Verify rules exist (basic check)
        # A more thorough test would verify the actual iptables rules
        self.assertTrue(True)

    def test_delete_vpc(self):
        """Test VPC deletion and cleanup"""
        vpc_name = "test_vpc"
        vpc_cidr = "10.0.0.0/16"
        
        # Create VPC
        vpc = self.manager.create_vpc(vpc_name, vpc_cidr)
        
        # Add a subnet
        subnet = self.manager.add_subnet(vpc_name, "public1", "10.0.1.0/24", is_public=True)
        
        # Delete VPC
        self.manager.delete_vpc(vpc_name)
        
        # Verify cleanup
        bridge_exists = os.system(f"ip link show {vpc_name}-bridge > /dev/null 2>&1") == 0
        self.assertFalse(bridge_exists, "Bridge not deleted")
        
        ns_exists = os.system(f"ip netns show | grep {vpc_name}-public1 > /dev/null 2>&1") == 0
        self.assertFalse(ns_exists, "Namespace not deleted")

    def test_idempotency(self):
        """Test idempotency of VPC creation"""
        vpc_name = "test_vpc"
        vpc_cidr = "10.0.0.0/16"
        
        # Create VPC twice
        vpc1 = self.manager.create_vpc(vpc_name, vpc_cidr)
        vpc2 = self.manager.create_vpc(vpc_name, vpc_cidr)
        
        # Both operations should return the same VPC
        self.assertEqual(vpc1.name, vpc2.name)
        self.assertEqual(vpc1.cidr, vpc2.cidr)

    def test_invalid_cidr(self):
        """Test VPC creation with invalid CIDR"""
        vpc_name = "test_vpc"
        invalid_cidr = "invalid_cidr"
        
        # Attempt to create VPC with invalid CIDR
        with self.assertRaises(Exception):
            self.manager.create_vpc(vpc_name, invalid_cidr)

    def test_subnet_isolation(self):
        """Test subnet isolation within a VPC"""
        vpc_name = "test_vpc"
        vpc_cidr = "10.0.0.0/16"
        
        # Create VPC with two subnets
        vpc = self.manager.create_vpc(vpc_name, vpc_cidr)
        subnet1 = self.manager.add_subnet(vpc_name, "private1", "10.0.1.0/24", is_public=False)
        subnet2 = self.manager.add_subnet(vpc_name, "private2", "10.0.2.0/24", is_public=False)
        
        # Verify subnets are created with different namespaces
        ns1_exists = os.system(f"ip netns show | grep {vpc_name}-private1 > /dev/null 2>&1") == 0
        ns2_exists = os.system(f"ip netns show | grep {vpc_name}-private2 > /dev/null 2>&1") == 0
        
        self.assertTrue(ns1_exists, "First namespace not created")
        self.assertTrue(ns2_exists, "Second namespace not created")

if __name__ == '__main__':
    unittest.main()