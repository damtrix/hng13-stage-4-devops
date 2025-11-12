SHELL := /bin/bash

.PHONY: help create-vpc add-subnet delete-vpc list peer-vpc add-rule deploy-app stop-app cleanup install

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
	@echo "Examples:"
	@echo "  make create-vpc NAME=myvpc CIDR=10.0.0.0/16 INTERFACE=eth0"
	@echo "  make add-subnet VPC=myvpc NAME=public1 CIDR=10.0.1.0/24 PUBLIC=1"
	@echo "  make peer-vpc VPC1=myvpc1 VPC2=myvpc2 CIDRS=\"10.0.1.0/24 172.16.1.0/24\""

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
