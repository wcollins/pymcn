import sys
import os
import boto3
import pandas as pd
from netaddr import IPNetwork
from azure.identity import DefaultAzureCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import VirtualNetwork, Subnet
from google.cloud import compute_v1
from google.auth import exceptions

class CloudManager:
    '''
    Class that manages base networking for AWS, Azure, and GCP
    '''
    def __init__(self, df, filename):
        self.df = df
        self.filename = filename

    def create_aws_vpcs(self):
        '''
        Iterate over each row in the dataframe and create VPC if cloud == aws
        '''
        for index, row in self.df.iterrows():
            if row['cloud'] == 'aws' and pd.isnull(row['resource_id']):
                session = boto3.Session(region_name=row['region'])
                ec2_resource = session.resource('ec2')
                vpc = ec2_resource.create_vpc(CidrBlock=row['cidr'])
                vpc.create_tags(Tags=[{"Key": "Name", "Value": row['name']}])
                vpc.wait_until_available()
                self.df.at[index, 'resource_id'] = vpc.id

                networks = list(IPNetwork(row['cidr']).subnet(24))

                for i in range(int(row['num_subnets'])):
                    subnet = ec2_resource.create_subnet(VpcId=vpc.id, CidrBlock=str(networks[i]))

    def delete_aws_vpcs(self):
        '''
        Iterate over each row in the dataframe and delete VPC if cloud == aws and 'resource_id' is not null
        '''
        for index, row in self.df.iterrows():
            if row['cloud'] == 'aws' and not pd.isnull(row['resource_id']):
                session = boto3.Session(region_name=row['region'])
                ec2_resource = session.resource('ec2')
                vpc = ec2_resource.Vpc(row['resource_id'])

                for subnet in vpc.subnets.all():
                    subnet.delete()

                for route_table in vpc.route_tables.all():
                    if not route_table.associations_attribute:
                        route_table.delete()

                for network_acl in vpc.network_acls.all():
                    if not network_acl.is_default:
                        network_acl.delete()

                for security_group in vpc.security_groups.all():
                    if security_group.group_name != 'default':
                        security_group.delete()

                vpc.delete()
                self.df.at[index, 'resource_id'] = pd.NA

    def create_azure_vnets(self):
        '''
        Iterate over each row in the dataframe and create VNet if cloud == azure
        '''
        credential = DefaultAzureCredential()
        subscription_id = os.getenv('SUBSCRIPTION_ID')

        for index, row in self.df.iterrows():
            if row['cloud'] == 'azure' and pd.isnull(row['resource_id']):
                network_client = NetworkManagementClient(credential, subscription_id)

                vnet_params = VirtualNetwork(location=row['region'], address_space={'address_prefixes': [row['cidr']]})
                async_vnet_creation = network_client.virtual_networks.begin_create_or_update(row['resource_group'], row['name'], vnet_params)
                vnet = async_vnet_creation.result()

                self.df.at[index, 'resource_id'] = vnet.id

                networks = list(IPNetwork(row['cidr']).subnet(24))

                for i in range(int(row['num_subnets'])):
                    subnet_params = Subnet(address_prefix=str(networks[i]))
                    network_client.subnets.begin_create_or_update(row['resource_group'], vnet.name, 'subnet' + str(i), subnet_params)

    def delete_azure_vnets(self):
        '''
        Iterate over each row in the dataframe and delete VNet if cloud == azure and 'resource_id' is not null
        '''
        credential = DefaultAzureCredential()
        subscription_id = os.getenv('SUBSCRIPTION_ID')

        for index, row in self.df.iterrows():
            if row['cloud'] == 'azure' and not pd.isnull(row['resource_id']):
                network_client = NetworkManagementClient(credential, subscription_id)

                async_vnet_deletion = network_client.virtual_networks.begin_delete(row['resource_group'], row['name'])
                async_vnet_deletion.wait()
                self.df.at[index, 'resource_id'] = pd.NA

    def create_gcp_vpcs(self):
        '''
        Iterate over each row in the dataframe and create VPC if cloud == gcp
        '''
        for index, row in self.df.iterrows():
            if row['cloud'] == 'gcp' and pd.isnull(row['resource_id']):
                project_id = row['project_id']
                client = compute_v1.NetworksClient()

                network = compute_v1.Network(
                    name=row['name'],
                    auto_create_subnetworks=False,
                )

                try:
                    operation = client.insert(project=project_id, network_resource=network)
                    operation.result()

                    # Get the created network
                    network = client.get(project=project_id, network=row['name'])
                    network_id = network.self_link.split('/')[-1]

                    self.df.at[index, 'resource_id'] = network_id

                    networks = list(IPNetwork(row['cidr']).subnet(24))

                    subnetwork_client = compute_v1.SubnetworksClient()

                    for i in range(int(row['num_subnets'])):
                        subnet = compute_v1.Subnetwork(
                            name='subnet' + str(i),
                            ip_cidr_range=str(networks[i]),
                            region=row['region'],
                            network=network.self_link
                        )
                        operation = subnetwork_client.insert(project=project_id, region=row['region'], subnetwork_resource=subnet)
                        operation.result()

                except exceptions.GoogleAuthError as e:
                    print(f"Failed to create VPC in GCP for project {project_id}. Error: {e}")

    def delete_gcp_vpcs(self):
        '''
        Iterate over each row in the dataframe and delete VPC if cloud == gcp and 'resource_id' is not null
        '''
        for index, row in self.df.iterrows():
            if row['cloud'] == 'gcp' and not pd.isnull(row['resource_id']):
                project_id = row['project_id']
                client = compute_v1.NetworksClient()

                # Get network
                network = client.get(project=project_id, network=row['name'])

                # Get list of subnets
                subnetworks_client = compute_v1.SubnetworksClient()
                aggregated_list = subnetworks_client.aggregated_list(project=project_id)

                for region_uri, subnetworks_scoped_list in aggregated_list:
                    if subnetworks_scoped_list.subnetworks:
                        for subnetwork in subnetworks_scoped_list.subnetworks:
                            if subnetwork.network == network.self_link:

                                # Fetch region name from the region URI
                                region = region_uri.split('/')[-1]

                                # Delete the subnet
                                operation = subnetworks_client.delete(project=project_id, region=region, subnetwork=subnetwork.name)
                                operation.result()

                # Delete VPC
                operation = client.delete(project=project_id, network=row['name'])
                operation.result()

                self.df.at[index, 'resource_id'] = pd.NA

    def process_networks(self, delete_flag=None):
        '''
        Logic to call either create or delete methods based on --delete flag
        '''

        # Is delete flag?
        if delete_flag == "--delete":
            self.delete_aws_vpcs()
            self.delete_azure_vnets()
            self.delete_gcp_vpcs()

        # Is not delete flag?
        else:
            self.create_aws_vpcs()
            self.create_azure_vnets()
            self.create_gcp_vpcs()

        self.df.to_excel(self.filename, index=False)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 pymcn.py <networks.xlsx> [--delete]")
        sys.exit(1)

    filename = sys.argv[1]
    delete_flag = sys.argv[2] if len(sys.argv) > 2 else None
    df = pd.read_excel(filename)

    manager = CloudManager(df, filename)
    manager.process_networks(delete_flag)


if __name__ == "__main__":
    main()