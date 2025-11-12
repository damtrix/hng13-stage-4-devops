from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    host_veth: Optional[str] = None
    ns_veth: Optional[str] = None
    firewall_rules: List[FirewallRule] = field(default_factory=list)

@dataclass
class VPC:
    name: str
    cidr: str
    bridge_name: str
    internet_interface: str
    peers: List[Dict[str, Any]] = field(default_factory=list)
    subnets: List[Subnet] = field(default_factory=list)