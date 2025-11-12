#!/usr/bin/env python3

import argparse
import json
import logging
import sys
from typing import Dict, List

from vpc_manager import VPCManager
from models import VPC, Subnet, FirewallRule
from utils import setup_logging

def parse_args():
    parser = argparse.ArgumentParser(description='VPC Controller CLI Tool')
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Create VPC command
    create_vpc = subparsers.add_parser('create-vpc', help='Create a new VPC')
    create_vpc.add_argument('--name', required=True, help='VPC name')
    create_vpc.add_argument('--cidr', required=True, help='CIDR block for VPC')
    create_vpc.add_argument('--internet-interface', help='Host interface used for internet/NAT traffic')

    # Add subnet command
    add_subnet = subparsers.add_parser('add-subnet', help='Add a subnet to VPC')
    add_subnet.add_argument('--vpc', required=True, help='VPC name')
    add_subnet.add_argument('--name', required=True, help='Subnet name')
    add_subnet.add_argument('--cidr', required=True, help='CIDR block for subnet')
    add_subnet.add_argument('--public', action='store_true', help='Make subnet public')

    # Delete VPC command
    delete_vpc = subparsers.add_parser('delete-vpc', help='Delete a VPC')
    delete_vpc.add_argument('--name', required=True, help='VPC name')

    # Peer VPC command
    peer_vpc = subparsers.add_parser('peer-vpc', help='Create VPC peering')
    peer_vpc.add_argument('--vpc1', required=True, help='First VPC name')
    peer_vpc.add_argument('--vpc2', required=True, help='Second VPC name')
    peer_vpc.add_argument(
        '--allow-cidr',
        action='append',
        default=[],
        help='CIDR to allow across the peering (can be repeated)'
    )

    # Add firewall rule command
    add_rule = subparsers.add_parser('add-rule', help='Add firewall rule')
    add_rule.add_argument('--vpc', required=True, help='VPC name')
    add_rule.add_argument('--subnet', required=True, help='Subnet CIDR')
    add_rule.add_argument('--policy', required=True, help='Path to policy JSON file')

    # Deploy app command
    deploy = subparsers.add_parser('deploy-app', help='Deploy web server in a subnet')
    deploy.add_argument('--vpc', required=True, help='VPC name')
    deploy.add_argument('--subnet', required=True, help='Subnet CIDR')
    deploy.add_argument('--port', required=True, type=int, help='Port to run web server on')

    # Stop app command
    stop = subparsers.add_parser('stop-app', help='Stop web server in a subnet')
    stop.add_argument('--vpc', required=True, help='VPC name')
    stop.add_argument('--subnet', required=True, help='Subnet CIDR')
    stop.add_argument('--port', required=True, type=int, help='Port the web server is running on')

    # List VPCs command
    subparsers.add_parser('list', help='List all VPCs')

    # Return both parser and parsed args so caller can print help when needed
    return parser, parser.parse_args()

def main():
    setup_logging()
    parser, args = parse_args()
    vpc_manager = VPCManager()

    try:
        if args.command == 'create-vpc':
            vpc_manager.create_vpc(args.name, args.cidr, args.internet_interface)
            logging.info(f"Created VPC: {args.name} with CIDR: {args.cidr}")

        elif args.command == 'add-subnet':
            vpc_manager.add_subnet(args.vpc, args.name, args.cidr, args.public)
            subnet_type = "public" if args.public else "private"
            logging.info(f"Added {subnet_type} subnet: {args.name} to VPC: {args.vpc}")

        elif args.command == 'delete-vpc':
            vpc_manager.delete_vpc(args.name)
            logging.info(f"Deleted VPC: {args.name}")

        elif args.command == 'peer-vpc':
            vpc_manager.peer_vpcs(args.vpc1, args.vpc2, args.allow_cidr)
            logging.info(
                f"Created peering between VPCs: {args.vpc1} and {args.vpc2} "
                f"with allowed CIDRs: {args.allow_cidr or 'ALL'}"
            )

        elif args.command == 'add-rule':
            with open(args.policy) as f:
                policy = json.load(f)
            vpc_manager.add_firewall_rules(args.vpc, args.subnet, policy)
            logging.info(f"Added firewall rules to subnet {args.subnet} in VPC {args.vpc}")

        elif args.command == 'deploy-app':
            vpc_manager.deploy_app(args.vpc, args.subnet, args.port)
            logging.info(f"Deployed app in subnet {args.subnet} (VPC: {args.vpc}) on port {args.port}")

        elif args.command == 'stop-app':
            vpc_manager.stop_app(args.vpc, args.subnet, args.port)
            logging.info(f"Stopped app in subnet {args.subnet} (VPC: {args.vpc}) on port {args.port}")

        elif args.command == 'list':
            vpcs = vpc_manager.list_vpcs()
            for vpc in vpcs:
                print(f"\nVPC: {vpc.name}")
                print(f"CIDR: {vpc.cidr}")
                print("Subnets:")
                for subnet in vpc.subnets:
                    print(f"  - {subnet.name} ({subnet.cidr})")

        else:
            # No command provided; show help
            parser.print_help()
            sys.exit(1)

    except Exception as e:
        logging.error(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()