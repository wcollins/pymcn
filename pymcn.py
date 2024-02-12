import sys
import os
import boto3
import pandas as pd
from netaddr import IPNetwork
import uuid
from azure.identity import DefaultAzureCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import VirtualNetwork, Subnet
from google.cloud import compute_v1
from google.auth import exceptions
from google.api_core import exceptions as google_exceptions

class CloudManager:
    def __init__(self, df, filename):
        print("Initializing CloudManager...")
        self.df = df
        self.filename = filename
        if 'route_table_id' not in df.columns:
            self.df['route_table_id'] = pd.NA
            print("Added 'route_table_id' column to DataFrame.")

    def create_aws_vpcs(self):
        print("Starting AWS VPC creation...")
        for index, row in self.df.iterrows():
            if row['cloud'] == 'aws' and pd.isnull(row['network_id']):
                print(f"Creating AWS VPC in region {row['region']} with CIDR {row['cidr']}")
                session = boto3.Session(region_name=row['region'])
                ec2_resource = session.resource('ec2')
                vpc = ec2_resource.create_vpc(CidrBlock=row['cidr'])
                vpc.create_tags(Tags=[{"Key": "Name", "Value": row['name']}])
                vpc.wait_until_available()
                self.df.at[index, 'network_id'] = vpc.id
                print(f"Created VPC {vpc.id}")

                main_route_table = list(vpc.route_tables.all())[0]
                self.df.at[index, 'route_table_id'] = main_route_table.id

                networks = list(IPNetwork(row['cidr']).subnet(24))

                for i in range(int(row['num_subnets'])):
                    subnet_name = f"subnet-{uuid.uuid4()}"
                    print(f"Creating subnet {i+1}/{int(row['num_subnets'])}: {subnet_name}")
                    subnet = ec2_resource.create_subnet(VpcId=vpc.id, CidrBlock=str(networks[i]), TagSpecifications=[{'ResourceType': 'subnet', 'Tags': [{'Key': 'Name', 'Value': subnet_name}]}])

    def delete_aws_vpcs(self):
        print("Starting AWS VPC deletion...")
        for index, row in self.df.iterrows():
            if row['cloud'] == 'aws' and not pd.isnull(row['network_id']):
                print(f"Deleting AWS VPC {row['network_id']}")
                session = boto3.Session(region_name=row['region'])
                ec2_resource = session.resource('ec2')
                vpc = ec2_resource.Vpc(row['network_id'])

                for subnet in vpc.subnets.all():
                    print(f"Deleting subnet {subnet.id}")
                    subnet.delete()

                for route_table in vpc.route_tables.all():
                    if not route_table.associations_attribute:
                        print(f"Deleting route table {route_table.id}")
                        route_table.delete()

                for network_acl in vpc.network_acls.all():
                    if not network_acl.is_default:
                        print(f"Deleting network ACL {network_acl.id}")
                        network_acl.delete()

                for security_group in vpc.security_groups.all():
                    if security_group.group_name != 'default':
                        print(f"Deleting security group {security_group.id}")
                        security_group.delete()

                print(f"Deleting VPC {vpc.id}")
                vpc.delete()
                self.df.at[index, 'network_id'] = pd.NA
                self.df.at[index, 'route_table_id'] = pd.NA

    def create_azure_vnets(self):
        print("Starting Azure VNet creation...")
        credential = DefaultAzureCredential()
        subscription_id = os.getenv('SUBSCRIPTION_ID')

        for index, row in self.df.iterrows():
            if row['cloud'] == 'azure' and pd.isnull(row['network_id']):
                print(f"Creating Azure VNet in resource group {row['resource_group']} with CIDR {row['cidr']}")
                network_client = NetworkManagementClient(credential, subscription_id)

                vnet_params = VirtualNetwork(location=row['region'], address_space={'address_prefixes': [row['cidr']]})
                async_vnet_creation = network_client.virtual_networks.begin_create_or_update(row['resource_group'], row['name'], vnet_params)
                vnet = async_vnet_creation.result()

                self.df.at[index, 'network_id'] = vnet.id
                print(f"Created VNet {vnet.id}")

                networks = list(IPNetwork(row['cidr']).subnet(24))

                for i in range(int(row['num_subnets'])):
                    subnet_name = f"subnet-{uuid.uuid4()}"
                    print(f"Creating subnet {i+1}/{int(row['num_subnets'])}: {subnet_name}")
                    subnet_params = Subnet(address_prefix=str(networks[i]), name=subnet_name)
                    network_client.subnets.begin_create_or_update(row['resource_group'], vnet.name, subnet_name, subnet_params)

    def delete_azure_vnets(self):
        print("Starting Azure VNet deletion...")
        credential = DefaultAzureCredential()
        subscription_id = os.getenv('SUBSCRIPTION_ID')

        for index, row in self.df.iterrows():
            if row['cloud'] == 'azure' and not pd.isnull(row['network_id']):
                print(f"Deleting Azure VNet {row['name']} in resource group {row['resource_group']}")
                network_client = NetworkManagementClient(credential, subscription_id)

                async_vnet_deletion = network_client.virtual_networks.begin_delete(row['resource_group'], row['name'])
                async_vnet_deletion.wait()
                self.df.at[index, 'network_id'] = pd.NA

    def create_gcp_vpcs(self):
        print("Starting GCP VPC creation...")
        for index, row in self.df.iterrows():
            if row['cloud'] == 'gcp' and pd.isnull(row['network_id']):
                print(f"Creating GCP VPC in project {row['project_id']} with name {row['name']}")
                project_id = row['project_id']
                client = compute_v1.NetworksClient()

                network = compute_v1.Network(
                    name=row['name'],
                    auto_create_subnetworks=False,
                )

                try:
                    operation = client.insert(project=project_id, network_resource=network)
                    operation.result()

                    network = client.get(project=project_id, network=row['name'])
                    network_id = network.self_link.split('/')[-1]

                    self.df.at[index, 'network_id'] = network_id
                    print(f"Created VPC {network_id}")

                    networks = list(IPNetwork(row['cidr']).subnet(24))

                    subnetwork_client = compute_v1.SubnetworksClient()

                    for i in range(int(row['num_subnets'])):
                        subnet_name = f"subnet-{uuid.uuid4()}"
                        print(f"Creating subnet {i+1}/{int(row['num_subnets'])}: {subnet_name}")
                        subnet = compute_v1.Subnetwork(
                            name=subnet_name,
                            ip_cidr_range=str(networks[i]),
                            region=row['region'],
                            network=network.self_link
                        )
                        operation = subnetwork_client.insert(project=project_id, region=row['region'], subnetwork_resource=subnet)
                        operation.result()

                except exceptions.GoogleAuthError as e:
                    print(f"Failed to create VPC in GCP for project {project_id}. Error: {e}")

    def delete_gcp_vpcs(self):
        print("Starting GCP VPC deletion...")
        for index, row in self.df.iterrows():
            if row['cloud'] == 'gcp' and not pd.isnull(row['network_id']):
                # Move the assignment of project_id here, before it's used
                project_id = row['project_id']
                print(f"Attempting to delete GCP VPC {row['name']} in project {project_id}")
                client = compute_v1.NetworksClient()

                try:
                    regions_client = compute_v1.RegionsClient()
                    regions = regions_client.list(project=project_id)
                    subnetworks_client = compute_v1.SubnetworksClient()

                    for region in regions:
                        subnets = subnetworks_client.list(project=project_id, region=region.name)
                        for subnet in subnets:
                            if subnet.network.endswith(row['name']):
                                print(f"Deleting subnet {subnet.name} in network {row['name']} and region {region.name}")
                                operation = subnetworks_client.delete(project=project_id, region=region.name, subnetwork=subnet.name)
                                operation.result()

                    print(f"Deleting VPC {row['name']}")
                    operation = client.delete(project=project_id, network=row['name'])
                    operation.result()
                    self.df.at[index, 'network_id'] = pd.NA

                except google_exceptions.NotFound:
                    print(f"Network {row['name']} not found in project {project_id}.")
                except google_exceptions.BadRequest as e:
                    print(f"BadRequest error when deleting network {row['name']} in project {project_id}: {e}")
                except Exception as e:
                    print(f"Unexpected error: {e}")

    def process_networks(self, delete_flag=None):
        if delete_flag == "--delete":
            print("Deleting networks based on DataFrame...")
            self.delete_aws_vpcs()
            self.delete_azure_vnets()
            self.delete_gcp_vpcs()
        else:
            print("Creating networks based on DataFrame...")
            self.create_aws_vpcs()
            self.create_azure_vnets()
            self.create_gcp_vpcs()

        print(f"Saving DataFrame to {self.filename}")
        self.df.to_excel(self.filename, index=False)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 script.py <networks.xlsx> [--delete]")
        sys.exit(1)

    filename = sys.argv[1]
    delete_flag = sys.argv[2] if len(sys.argv) > 2 else None
    df = pd.read_excel(filename)

    print("Loaded DataFrame from file.")
    manager = CloudManager(df, filename)
    manager.process_networks(delete_flag)
    print("Operation completed.")

if __name__ == "__main__":
    main()