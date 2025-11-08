SHELL := /bin/zsh


.PHONY: help create-vpc add-subnet delete-vpc list cleanup

help:
	@echo "Makefile for vpcctl project"
	@echo "Targets: create-vpc, add-subnet, delete-vpc, list, cleanup"

create-vpc:
	@echo "Create a VPC: make create-vpc NAME=myvpc CIDR=10.0.0.0/16"
	@sudo python3 src/vpcctl.py create-vpc --name $(NAME) --cidr $(CIDR)

add-subnet:
	@echo "Add subnet: make add-subnet VPC=myvpc NAME=public1 CIDR=10.0.1.0/24 PUBLIC=1"
	@if [ "$(PUBLIC)" = "1" ]; then \
		sudo python3 src/vpcctl.py add-subnet --vpc $(VPC) --name $(NAME) --cidr $(CIDR) --public; \
	else \
		sudo python3 src/vpcctl.py add-subnet --vpc $(VPC) --name $(NAME) --cidr $(CIDR); \
	fi

delete-vpc:
	@echo "Delete a VPC: make delete-vpc NAME=myvpc"
	@sudo python3 src/vpcctl.py delete-vpc --name $(NAME)

list:
	@echo "List VPCs"
	@python3 src/vpcctl.py list

cleanup:
	@echo "Cleanup helper - manually delete VPCs by name using delete-vpc target"
	@echo "Example: make delete-vpc NAME=myvpc"
