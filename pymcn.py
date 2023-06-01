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

def create_aws_vpcs(df):
    for index, row in df.iterrows():
        if row['cloud'] == 'aws' and pd.isnull(row['resource_id']):
            session = boto3.Session(region_name=row['region'])
            ec2_resource = session.resource('ec2')
            vpc = ec2_resource.create_vpc(CidrBlock=row['cidr'])
            vpc.create_tags(Tags=[{"Key": "Name", "Value": row['name']}])
            vpc.wait_until_available()
            df.at[index, 'resource_id'] = vpc.id

            networks = list(IPNetwork(row['cidr']).subnet(24))

            for i in range(2):
                subnet = ec2_resource.create_subnet(VpcId=vpc.id, CidrBlock=str(networks[i]))

def delete_aws_vpcs(df):
    for index, row in df.iterrows():
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
            df.at[index, 'resource_id'] = pd.NA

def create_azure_vnets(df):
    credential = DefaultAzureCredential()
    subscription_id = os.getenv('SUBSCRIPTION_ID')

    for index, row in df.iterrows():
        if row['cloud'] == 'azure' and pd.isnull(row['resource_id']):
            network_client = NetworkManagementClient(credential, subscription_id)

            vnet_params = VirtualNetwork(location=row['region'], address_space={'address_prefixes': [row['cidr']]})
            async_vnet_creation = network_client.virtual_networks.begin_create_or_update(row['resource_group'], row['name'], vnet_params)
            vnet = async_vnet_creation.result()

            df.at[index, 'resource_id'] = vnet.id

            networks = list(IPNetwork(row['cidr']).subnet(24))

            for i in range(2):
                subnet_params = Subnet(address_prefix=str(networks[i]))
                network_client.subnets.begin_create_or_update(row['resource_group'], vnet.name, 'subnet' + str(i), subnet_params)

def delete_azure_vnets(df):
    credential = DefaultAzureCredential()
    subscription_id = os.getenv('SUBSCRIPTION_ID')

    for index, row in df.iterrows():
        if row['cloud'] == 'azure' and not pd.isnull(row['resource_id']):
            network_client = NetworkManagementClient(credential, subscription_id)

            async_vnet_deletion = network_client.virtual_networks.begin_delete(row['resource_group'], row['name'])
            async_vnet_deletion.wait()
            df.at[index, 'resource_id'] = pd.NA

def create_gcp_vpcs(df):
    for index, row in df.iterrows():
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

                df.at[index, 'resource_id'] = network_id

                networks = list(IPNetwork(row['cidr']).subnet(24))

                subnetwork_client = compute_v1.SubnetworksClient()

                num_of_subnets = 2  # Change this to the number of subnets you want to create
                for i in range(num_of_subnets):
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

def delete_gcp_vpcs(df):
    for index, row in df.iterrows():
        if row['cloud'] == 'gcp' and not pd.isnull(row['resource_id']):
            project_id = row['project_id']
            client = compute_v1.NetworksClient()

            # Get the network
            network = client.get(project=project_id, network=row['name'])

            # Get the list of subnetworks
            subnetworks_client = compute_v1.SubnetworksClient()
            aggregated_list = subnetworks_client.aggregated_list(project=project_id)

            for region_uri, subnetworks_scoped_list in aggregated_list:
                if subnetworks_scoped_list.subnetworks:
                    for subnetwork in subnetworks_scoped_list.subnetworks:
                        if subnetwork.network == network.self_link:

                            # Get the region name from the region URI
                            region = region_uri.split('/')[-1]

                            # Delete the subnet
                            operation = subnetworks_client.delete(project=project_id, region=region, subnetwork=subnetwork.name)
                            operation.result()

            # Delete the VPC
            operation = client.delete(project=project_id, network=row['name'])
            operation.result()

            df.at[index, 'resource_id'] = pd.NA

def main():

    if len(sys.argv) < 2:
        print("Usage: python pymcn.py <networks.csv> [--delete]")
        sys.exit(1)

    filename = sys.argv[1]
    delete_flag = sys.argv[2] if len(sys.argv) > 2 else None
    df = pd.read_csv(filename)

    if delete_flag == "--delete":
        delete_aws_vpcs(df)
        delete_azure_vnets(df)
        delete_gcp_vpcs(df)
    else:
        create_aws_vpcs(df)
        create_azure_vnets(df)
        create_gcp_vpcs(df)

    df.to_csv(filename, index=False)

if __name__ == "__main__":
    main()