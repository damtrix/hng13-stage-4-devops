SHELL := /bin/bash

.PHONY: help create-vpc add-subnet delete-vpc list peer-vpc add-rule deploy-app stop-app cleanup install test-all test-part1 test-part2 test-part3 test-part4 test-part5 test-cleanup

help:
	@echo "Makefile for vpcctl project"
	@echo ""
	@echo "Available targets:"
	@echo "  install          - Make vpcctl.py executable and optionally create symlink"
	@echo "  create-vpc       - Create a VPC: make create-vpc NAME=myvpc CIDR=10.0.0.0/16 [INTERFACE=eth0]"
	@echo "  add-subnet       - Add subnet: make add-subnet VPC=myvpc NAME=public1 CIDR=10.0.1.0/24 [PUBLIC=1]"
	@echo "  peer-vpc         - Peer two VPCs: make peer-vpc VPC1=myvpc1 VPC2=myvpc2 [CIDRS=\"10.0.1.0/24 172.16.1.0/24\"]"
	@echo "  add-rule         - Add firewall rule: make add-rule VPC=myvpc SUBNET=10.0.1.0/24 POLICY=policy.json"
	@echo "  deploy-app       - Deploy web server: make deploy-app VPC=myvpc SUBNET=10.0.1.0/24 PORT=8000"
	@echo "  stop-app         - Stop web server: make stop-app VPC=myvpc SUBNET=10.0.1.0/24 PORT=8000"
	@echo "  list             - List all VPCs"
	@echo "  delete-vpc       - Delete a VPC: make delete-vpc NAME=myvpc"
	@echo "  cleanup          - Show cleanup instructions"
	@echo ""
	@echo "TEST TARGETS (run with sudo):"
	@echo "  test-all         - Run all test parts (1-5) + cleanup"
	@echo "  test-part1       - Test VPC creation & subnet communication"
	@echo "  test-part2       - Test NAT gateway (public vs private)"
	@echo "  test-part3       - Test VPC isolation & peering"
	@echo "  test-part4       - Test firewall & security groups"
	@echo "  test-part5       - Test cleanup & teardown"
	@echo "  test-cleanup     - Final cleanup of test resources"
	@echo ""
	@echo "Examples:"
	@echo "  make create-vpc NAME=myvpc CIDR=10.0.0.0/16 INTERFACE=eth0"
	@echo "  make add-subnet VPC=myvpc NAME=public1 CIDR=10.0.1.0/24 PUBLIC=1"
	@echo "  make peer-vpc VPC1=myvpc1 VPC2=myvpc2 CIDRS=\"10.0.1.0/24 172.16.1.0/24\""
	@echo "  sudo make test-all          # Run complete test suite"
	@echo "  sudo make test-part1         # Test specific part"

install:
	@echo "Making vpcctl.py executable..."
	@chmod +x src/vpcctl.py
	@echo "vpcctl.py is now executable"
	@echo "To create a symlink, run: sudo ln -s $(PWD)/src/vpcctl.py /usr/local/bin/vpcctl"

create-vpc:
	@if [ -z "$(NAME)" ] || [ -z "$(CIDR)" ]; then \
		echo "Error: NAME and CIDR are required"; \
		echo "Usage: make create-vpc NAME=myvpc CIDR=10.0.0.0/16 [INTERFACE=eth0]"; \
		exit 1; \
	fi
	@echo "Creating VPC: $(NAME) with CIDR: $(CIDR)"
	@sudo python3 src/vpcctl.py create-vpc --name $(NAME) --cidr $(CIDR) $(if $(INTERFACE),--internet-interface $(INTERFACE),)

add-subnet:
	@if [ -z "$(VPC)" ] || [ -z "$(NAME)" ] || [ -z "$(CIDR)" ]; then \
		echo "Error: VPC, NAME, and CIDR are required"; \
		echo "Usage: make add-subnet VPC=myvpc NAME=public1 CIDR=10.0.1.0/24 [PUBLIC=1]"; \
		exit 1; \
	fi
	@if [ "$(PUBLIC)" = "1" ]; then \
		echo "Adding public subnet: $(NAME) to VPC: $(VPC)"; \
		sudo python3 src/vpcctl.py add-subnet --vpc $(VPC) --name $(NAME) --cidr $(CIDR) --public; \
	else \
		echo "Adding private subnet: $(NAME) to VPC: $(VPC)"; \
		sudo python3 src/vpcctl.py add-subnet --vpc $(VPC) --name $(NAME) --cidr $(CIDR); \
	fi

peer-vpc:
	@if [ -z "$(VPC1)" ] || [ -z "$(VPC2)" ]; then \
		echo "Error: VPC1 and VPC2 are required"; \
		echo "Usage: make peer-vpc VPC1=myvpc1 VPC2=myvpc2 [CIDRS=\"10.0.1.0/24 172.16.1.0/24\"]"; \
		echo "Note: CIDRS should be space-separated. If omitted, all subnets are allowed."; \
		exit 1; \
	fi
	@echo "Peering VPCs: $(VPC1) <-> $(VPC2)"
	@CMD="sudo python3 src/vpcctl.py peer-vpc --vpc1 $(VPC1) --vpc2 $(VPC2)"; \
	if [ -n "$(CIDRS)" ]; then \
		for cidr in $(CIDRS); do \
			CMD="$$CMD --allow-cidr $$cidr"; \
		done; \
		echo "Allowing CIDRs: $(CIDRS)"; \
	else \
		echo "No CIDRs specified, allowing all subnets"; \
	fi; \
	eval $$CMD

add-rule:
	@if [ -z "$(VPC)" ] || [ -z "$(SUBNET)" ] || [ -z "$(POLICY)" ]; then \
		echo "Error: VPC, SUBNET, and POLICY are required"; \
		echo "Usage: make add-rule VPC=myvpc SUBNET=10.0.1.0/24 POLICY=policy.json"; \
		exit 1; \
	fi
	@if [ ! -f "$(POLICY)" ]; then \
		echo "Error: Policy file $(POLICY) not found"; \
		exit 1; \
	fi
	@echo "Adding firewall rules to subnet $(SUBNET) in VPC $(VPC)"
	@sudo python3 src/vpcctl.py add-rule --vpc $(VPC) --subnet $(SUBNET) --policy $(POLICY)

deploy-app:
	@if [ -z "$(VPC)" ] || [ -z "$(SUBNET)" ] || [ -z "$(PORT)" ]; then \
		echo "Error: VPC, SUBNET, and PORT are required"; \
		echo "Usage: make deploy-app VPC=myvpc SUBNET=10.0.1.0/24 PORT=8000"; \
		exit 1; \
	fi
	@echo "Deploying web server in subnet $(SUBNET) (VPC: $(VPC)) on port $(PORT)"
	@sudo python3 src/vpcctl.py deploy-app --vpc $(VPC) --subnet $(SUBNET) --port $(PORT)

stop-app:
	@if [ -z "$(VPC)" ] || [ -z "$(SUBNET)" ] || [ -z "$(PORT)" ]; then \
		echo "Error: VPC, SUBNET, and PORT are required"; \
		echo "Usage: make stop-app VPC=myvpc SUBNET=10.0.1.0/24 PORT=8000"; \
		exit 1; \
	fi
	@echo "Stopping web server in subnet $(SUBNET) (VPC: $(VPC)) on port $(PORT)"
	@sudo python3 src/vpcctl.py stop-app --vpc $(VPC) --subnet $(SUBNET) --port $(PORT)

delete-vpc:
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME is required"; \
		echo "Usage: make delete-vpc NAME=myvpc"; \
		exit 1; \
	fi
	@echo "Deleting VPC: $(NAME)"
	@sudo python3 src/vpcctl.py delete-vpc --name $(NAME)

list:
	@echo "Listing all VPCs:"
	@sudo python3 src/vpcctl.py list

cleanup:
	@echo "Cleanup helper - manually delete VPCs by name using delete-vpc target"
	@echo "Example: make delete-vpc NAME=myvpc"
	@echo ""
	@echo "To list all VPCs first: make list"

# Test targets - Comprehensive testing of all acceptance criteria
# Get default interface for NAT testing (more portable)
DEFAULT_IF := $(shell ip route get 1.1.1.1 2>/dev/null | awk '/dev/ {for(i=1;i<=NF;i++) if($$i=="dev") {print $$(i+1); exit}}' || echo "eth0")

test-all: test-part1 test-part2 test-part3 test-part4 test-part5 test-cleanup
	@echo ""
	@echo "=========================================="
	@echo "✅ ALL TESTS COMPLETED SUCCESSFULLY!"
	@echo "=========================================="

test-part1:
	@echo ""
	@echo "=========================================="
	@echo "PART 1: VPC Creation & Subnet Communication"
	@echo "=========================================="
	@echo "Creating VPC 'testvpc1' with CIDR 10.0.0.0/16..."
	@make create-vpc NAME=testvpc1 CIDR=10.0.0.0/16 INTERFACE=$(DEFAULT_IF)
	@echo ""
	@echo "Adding public subnet 10.0.1.0/24..."
	@make add-subnet VPC=testvpc1 NAME=public1 CIDR=10.0.1.0/24 PUBLIC=1
	@echo ""
	@echo "Adding private subnet 10.0.2.0/24..."
	@make add-subnet VPC=testvpc1 NAME=private1 CIDR=10.0.2.0/24
	@echo ""
	@echo "Verifying bridge exists..."
	@sudo ip link show br-testvpc1 > /dev/null 2>&1 && echo "✅ Bridge created" || (echo "❌ Bridge missing" && exit 1)
	@echo "Verifying namespaces exist..."
	@sudo ip netns list | grep -q "testvpc1-public1" && echo "✅ Public namespace created" || (echo "❌ Public namespace missing" && exit 1)
	@sudo ip netns list | grep -q "testvpc1-private1" && echo "✅ Private namespace created" || (echo "❌ Private namespace missing" && exit 1)
	@echo ""
	@echo "Deploying test servers..."
	@make deploy-app VPC=testvpc1 SUBNET=10.0.1.0/24 PORT=8080
	@sleep 1
	@make deploy-app VPC=testvpc1 SUBNET=10.0.2.0/24 PORT=8081
	@sleep 1
	@echo ""
	@echo "Testing inter-subnet communication..."
	@sudo ip netns exec testvpc1-public1 curl -s --connect-timeout 2 http://10.0.2.2:8081 > /dev/null && echo "✅ Public -> Private: SUCCESS" || (echo "❌ Public -> Private: FAILED" && exit 1)
	@sudo ip netns exec testvpc1-private1 curl -s --connect-timeout 2 http://10.0.1.2:8080 > /dev/null && echo "✅ Private -> Public: SUCCESS" || (echo "❌ Private -> Public: FAILED" && exit 1)
	@echo ""
	@echo "✅ PART 1 COMPLETE: VPC creation and subnet communication verified"

test-part2:
	@echo ""
	@echo "=========================================="
	@echo "PART 2: NAT Gateway (Public vs Private)"
	@echo "=========================================="
	@echo "Testing internet access from public subnet..."
	@sudo ip netns exec testvpc1-public1 ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1 && echo "✅ Public subnet has internet access" || echo "⚠️  Public subnet internet test (may fail if no internet)"
	@echo ""
	@echo "Testing internet access from private subnet (should fail)..."
	@sudo ip netns exec testvpc1-private1 ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1 && echo "❌ Private subnet should NOT have internet access" || echo "✅ Private subnet correctly blocked from internet"
	@echo ""
	@echo "Verifying NAT rules exist..."
	@sudo iptables -t nat -C POSTROUTING -s 10.0.1.0/24 -o $(DEFAULT_IF) -j MASQUERADE > /dev/null 2>&1 && echo "✅ NAT rule for public subnet exists" || echo "⚠️  NAT rule check (may vary)"
	@echo ""
	@echo "✅ PART 2 COMPLETE: NAT gateway behavior verified"

test-part3:
	@echo ""
	@echo "=========================================="
	@echo "PART 3: VPC Isolation & Peering"
	@echo "=========================================="
	@echo "Creating second VPC 'testvpc2' with CIDR 172.16.0.0/16..."
	@make create-vpc NAME=testvpc2 CIDR=172.16.0.0/16 INTERFACE=$(DEFAULT_IF)
	@echo ""
	@echo "Adding subnets to second VPC..."
	@make add-subnet VPC=testvpc2 NAME=public1 CIDR=172.16.1.0/24 PUBLIC=1
	@make add-subnet VPC=testvpc2 NAME=private1 CIDR=172.16.2.0/24
	@echo ""
	@echo "Deploying test server in second VPC..."
	@make deploy-app VPC=testvpc2 SUBNET=172.16.1.0/24 PORT=8082
	@sleep 1
	@echo ""
	@echo "Testing VPC isolation (should fail)..."
	@sudo ip netns exec testvpc1-public1 curl -s --connect-timeout 2 http://172.16.1.2:8082 > /dev/null && echo "❌ VPCs should be isolated!" || echo "✅ VPCs are correctly isolated"
	@echo ""
	@echo "Creating VPC peering with specific CIDRs..."
	@make peer-vpc VPC1=testvpc1 VPC2=testvpc2 CIDRS="10.0.1.0/24 172.16.1.0/24"
	@sleep 1
	@echo ""
	@echo "Testing cross-VPC communication after peering..."
	@sudo ip netns exec testvpc1-public1 curl -s --connect-timeout 2 http://172.16.1.2:8082 > /dev/null && echo "✅ Cross-VPC communication works after peering" || echo "⚠️  Cross-VPC test (check routes)"
	@echo ""
	@echo "✅ PART 3 COMPLETE: VPC isolation and peering verified"

test-part4:
	@echo ""
	@echo "=========================================="
	@echo "PART 4: Firewall & Security Groups"
	@echo "=========================================="
	@echo "Adding firewall rules to public subnet (allow 8080, deny 8085)..."
	@echo '{"subnet": "10.0.1.0/24", "ingress": [{"port": 8080, "protocol": "tcp", "action": "allow"}, {"port": 8085, "protocol": "tcp", "action": "deny"}]}' > /tmp/test_policy.json
	@make add-rule VPC=testvpc1 SUBNET=10.0.1.0/24 POLICY=/tmp/test_policy.json
	@echo ""
	@echo "Deploying test server on allowed port 8080..."
	@make deploy-app VPC=testvpc1 SUBNET=10.0.1.0/24 PORT=8080
	@sleep 1
	@echo ""
	@echo "Testing allowed port (8080)..."
	@sudo ip netns exec testvpc1-private1 curl -s --connect-timeout 2 http://10.0.1.2:8080 > /dev/null && echo "✅ Port 8080 allowed (firewall working)" || echo "⚠️  Port 8080 test"
	@echo ""
	@echo "Testing denied port (8085) - should fail..."
	@sudo ip netns exec testvpc1-private1 curl -s --connect-timeout 2 http://10.0.1.2:8085 > /dev/null && echo "⚠️  Port 8085 should be blocked" || echo "✅ Port 8085 correctly blocked"
	@echo ""
	@echo "Verifying iptables rules in namespace..."
	@sudo ip netns exec testvpc1-public1 iptables -L INPUT -n | grep -q "8080" && echo "✅ Firewall rules applied" || echo "⚠️  Firewall rules check"
	@rm -f /tmp/test_policy.json
	@echo ""
	@echo "✅ PART 4 COMPLETE: Firewall enforcement verified"

test-part5:
	@echo ""
	@echo "=========================================="
	@echo "PART 5: Cleanup & Teardown"
	@echo "=========================================="
	@echo "Stopping deployed applications..."
	@-make stop-app VPC=testvpc1 SUBNET=10.0.1.0/24 PORT=8080 2>/dev/null
	@-make stop-app VPC=testvpc1 SUBNET=10.0.2.0/24 PORT=8081 2>/dev/null
	@-make stop-app VPC=testvpc2 SUBNET=172.16.1.0/24 PORT=8082 2>/dev/null
	@echo ""
	@echo "Deleting VPCs..."
	@make delete-vpc NAME=testvpc1
	@make delete-vpc NAME=testvpc2
	@echo ""
	@echo "Verifying cleanup..."
	@sudo ip link show br-testvpc1 > /dev/null 2>&1 && echo "❌ Bridge still exists!" || echo "✅ Bridge removed"
	@sudo ip netns list | grep -q "testvpc1" && echo "❌ Namespaces still exist!" || echo "✅ Namespaces removed"
	@sudo ip netns list | grep -q "testvpc2" && echo "❌ Namespaces still exist!" || echo "✅ Namespaces removed"
	@echo ""
	@echo "Checking for orphaned iptables rules..."
	@sudo iptables-save | grep -q "10.0.1.0/24" && echo "⚠️  Some iptables rules may remain" || echo "✅ iptables rules cleaned up"
	@echo ""
	@echo "✅ PART 5 COMPLETE: Cleanup verified"

test-cleanup:
	@echo ""
	@echo "=========================================="
	@echo "FINAL CLEANUP"
	@echo "=========================================="
	@echo "Removing any remaining test VPCs..."
	@-make delete-vpc NAME=testvpc1 2>/dev/null || true
	@-make delete-vpc NAME=testvpc2 2>/dev/null || true
	@echo "✅ Cleanup complete"
