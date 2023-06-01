import sys
import os
import boto3
import pandas as pd
from netaddr import IPNetwork
from azure.identity import DefaultAzureCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import VirtualNetwork, Subnet

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
    else:
        create_aws_vpcs(df)
        create_azure_vnets(df)

    df.to_csv(filename, index=False)

if __name__ == "__main__":
    main()