import sys
import boto3
import pandas as pd
from netaddr import IPNetwork

def create_aws_vpcs(df, filename):
    df = df[df['cloud'] == 'aws']
    df['vpc_id'] = ''

    for index, row in df.iterrows():
        session = boto3.Session(region_name=row['region'])
        ec2_resource = session.resource('ec2')
        vpc = ec2_resource.create_vpc(CidrBlock=row['cidr'])
        vpc.create_tags(Tags=[{"Key": "Name", "Value": row['name']}])
        vpc.wait_until_available()
        df.at[index, 'vpc_id'] = vpc.id

        networks = list(IPNetwork(row['cidr']).subnet(24))

        for i in range(2):
            subnet = ec2_resource.create_subnet(VpcId=vpc.id, CidrBlock=str(networks[i]))

    df.to_csv(filename, index=False)

def delete_aws_vpcs(df, filename):
    for index, row in df.iterrows():
        if pd.isnull(row['vpc_id']) or row['cloud'] != 'aws':
            continue

        session = boto3.Session(region_name=row['region'])
        ec2_resource = session.resource('ec2')
        vpc = ec2_resource.Vpc(row['vpc_id'])

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

    df = df.drop(columns='vpc_id')
    df.to_csv(filename, index=False)

def main():

    if len(sys.argv) < 2:
        print("Usage: python manage_vpcs.py <filename> [--delete]")
        sys.exit(1)

    filename = sys.argv[1]
    delete_flag = sys.argv[2] if len(sys.argv) > 2 else None
    df = pd.read_csv(filename)

    if delete_flag == "--delete":
        delete_aws_vpcs(df, filename)
    else:
        create_aws_vpcs(df, filename)

if __name__ == "__main__":
    main()