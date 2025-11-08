from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class FirewallRule:
    port: int
    protocol: str
    action: str

@dataclass
class Subnet:
    name: str
    cidr: str
    is_public: bool
    namespace: str
    bridge_ip: str
    firewall_rules: List[FirewallRule] = field(default_factory=list)

@dataclass
class VPC:
    name: str
    cidr: str
    bridge_name: str
    subnets: List[Subnet] = field(default_factory=list)