## pyMCN _(Python Multi-Cloud Networking)_
Part of my daily routine involves prototyping environments for scenarios spanning multiple _public cloud_ providers. This Python script creates and deletes _networks_ and _subnets_ across **AWS**, **Azure**, and **GCP** from a _.csv_. Once the networks are provisioned, it returns and appends the _id_ of each network to the spreadsheet so it can _delete_ the resource when needed.

:warning: **WARNING**
This is not a _production-grade_ application. Use at your own risk!

## Setup
This script uses [Pandas](https://pandas.pydata.org/) for data manipulation along with the _SDKs_ for each cloud provider. The following packages are required:
```bash
pip3 install -r requirements.txt
```

### Env Variables
This script uses _environment variables_ to securely provide sensitive details, like credentials. These can be set in _shell_.
```bash
export AWS_ACCESS_KEY_ID=aws_access_key_id
export AWS_SECRET_ACCESS_KEY=aws_secret_access_key
export AZURE_TENANT_ID=azure_tenant_id
export AZURE_CLIENT_ID=azure_client_id
export AZURE_CLIENT_SECRET=azure_client_secret
export SUBSCRIPTION_ID=azure_subscription_id
export GOOGLE_APPLICATION_CREDENTIALS=credentials.json
```

## Usage
CSV file should contain the following columns:

- name: The name of the network
- cloud: The cloud provider. Valid options are 'aws', 'azure', or 'gcp'
- region: The region in which to create the network
- cidr: The CIDR block for the network; Must be large enough to accommodate the specified number of /24 subnets
- num_subnets: The number of subnets to create for the network
- resource_group: _(For Azure only)_ The resource group in which to create the VNet
- project_id: _(For GCP only)_ The _id_ of the project in which to create the VPC.
- resource_id: **Leave this empty**; It will be filled with the _id_ of the resource

### Example .csv values
| name | cloud | region | cidr | num_subnets | resource_group | project_id | resource_id |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| vpc-01-npe | aws | us-east-1 | 10.1.0.0/16 | 1 |  |  |  |
| vpc-02-npe | aws | us-east-2 | 10.2.0.0/16 | 2 |  |  |  |
| vnet-01-npe | azure | eastus2 | 10.3.0.0/16 | 1 | rg-eastus2 |  |  |
| vnet-02-npe | azure | centralus | 10.4.0.0/16 | 2 | rg-centralus |  |  |
| vpc-01-npe | gcp | us-east4 | 10.5.0.0/16 | 2 |  | project-a |  |
| vpc-02-npe | gcp | us-central1 | 10.6.0.0/16 | 2 |  | project-b |  |

### Creating Networks
Networks can be created using the following:
```bash
python3 pymcn.py networks.csv
```

> It will then append the _id_ of each network created to the _resource_id_ column

### Deleting Networks
Networks can be deleted using the following:
```bash
python3 pymcn.py networks.csv --delete
```

> The _id_ of each network existing under the _resource_id_ column will be used to reference the network being deleted