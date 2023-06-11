import boto3

DEBUG = True
ZNY_WEB_SERVER_IP = "Not found"


def get_zny_web_ip():
    """
    Get the IP address of the ZNY-Website-Production EC2 instance.
    :return: The IP address of the ZNY-Website-Production EC2 instance.
    """
    # Use EC2 client
    ec2 = boto3.client("ec2")

    # Describe instances with a specific tag
    response = ec2.describe_instances(
        Filters=[
            {
                'Name': 'tag:Name',
                'Values': ['ZNY-Website-Production']
            }
        ]
    )

    # Check if an instance with the name "ZNY-Website-Production" was found
    if len(response['Reservations']) > 0:
        # Get the first instance
        instance = response['Reservations'][0]['Instances'][0]
        if DEBUG:
            print(f"BINGO! Found ZNY-Website-Production with IP {instance['PublicIpAddress']}")
        return instance['PublicIpAddress']
    else:
        if DEBUG:
            print(f"No instance named ZNY-Website-Production found, returning static: {ZNY_WEB_SERVER_IP}")
        return ZNY_WEB_SERVER_IP


if __name__ == "__main__":
    print(get_zny_web_ip())
